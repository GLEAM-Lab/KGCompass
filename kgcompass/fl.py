import json
import os
import sys
import time
from pathlib import Path
from bs4 import BeautifulSoup
import requests
import traceback
import git
import re
import pylcs
import hashlib
from github import Github
from datetime import datetime, timedelta, timezone
from dateutil import parser as date_parser
from datasets import load_dataset, DownloadConfig
import html2text
from knowledge_graph import KnowledgeGraph
from utils import (
    extract_methods_from_traceback, 
    get_source_files_by_extensions,
    get_pr_file_line_belongs, 
    get_python_files_from_content,
    get_ref_ids, 
    get_reference_functions_from_text, 
    read_file, 
    TextAnalyzer,
    create_github_client,
)
from links import PatchLinkExpander
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from config import (
    GITHUB_TOKEN,
    NEO4J_URI, 
    NEO4J_USER,
    NEO4J_PASSWORD,
    MAX_CANDIDATE_METHODS,
    MAX_SEARCH_DEPTH,
    DATASET_NAME,
    SEARCH_SPACE,
    WEAK_CONNECTION,
    NORMAL_CONNECTION,
    STRONG_CONNECTION,
    DECAY_FACTOR,
    VECTOR_SIMILARITY_WEIGHT,
)
from language_factory import LanguageConfigFactory, ParserFactory, language_by_extension, EXT_LANG_MAP
from functools import lru_cache
from github_middleware import GitHubAPIMiddleware

UNAVAILABLE_BENCHMARK_FIELDS = {"hint_text", "hints_text"}
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
PGP_SIGNATURE_RE = re.compile(
    r"-----BEGIN PGP SIGNATURE-----.*?-----END PGP SIGNATURE-----",
    re.DOTALL | re.IGNORECASE,
)
BOILERPLATE_DOC_NAMES = {
    "code_of_conduct",
    "contributing",
    "license",
    "security",
    "issue_template",
    "pull_request_template",
}
COMMON_WORD_REFERENCES = {
    "actual", "behavior", "behaviour", "comparing", "description", "difference",
    "expected", "extension", "problem", "reproduce", "result", "sometimes",
    "traceback", "version", "warning", "begin", "end", "signature", "pgp",
    "gnupg", "com", "org", "net", "edu", "gov", "html", "http", "https",
    "value", "values", "comment", "comments", "keyword", "keywords", "gz",
    "array", "collect", "copy", "data", "file", "files", "header", "headers",
    "hdf5", "keyerror", "name", "ndarray", "none", "open", "pytables",
    "true", "false", "attributeerror", "indexerror", "importerror",
    "modulenotfounderror", "notimplemented", "notimplementederror", "runtimeerror",
    "typeerror", "valueerror", "platform", "format", "lower", "append", "count",
    "txt", "fr", "amd64", "arm64", "darwin", "linux", "macos", "ubuntu",
    "win32", "win64", "windows", "x64", "x86", "x86_64",
}
NOISY_DUNDER_REFERENCES = {
    "__call__", "__class__", "__dict__", "__getattr__", "__init__", "__iter__",
    "__len__", "__module__", "__name__", "__repr__", "__setattr__", "__str__",
    "__version__",
}
GENERIC_BASENAME_REFERENCES = {
    "__init__", "base", "common", "compat", "conf", "config", "conftest", "core",
    "io", "test", "tests", "ui", "utils",
}
NON_SOURCE_FILE_EXTENSIONS = {
    ".cfg", ".csv", ".html", ".ini", ".json", ".md", ".rst", ".toml", ".txt",
    ".xml", ".yaml", ".yml",
}
LOCAL_OR_STDLIB_QUALIFIED_PREFIXES = {
    "c", "cls", "df", "filepath", "np", "numpy", "os", "pd", "platform", "self",
    "sys", "tbl", "u",
}
GENERIC_QUALIFIED_TARGETS = {
    "append", "count", "format", "lower", "open", "platform", "read", "version",
    "transform", "write",
}
DOMAIN_OR_EMAIL_RE = re.compile(
    r"(^|[\s<])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|"
    r"\b(?:https?://|www\.)?\w[\w.-]*\.(?:com|org|net|edu|gov|io|dev|ai|fr)\b",
    re.IGNORECASE,
)
MAINTENANCE_COMMIT_RE = re.compile(
    r"\b("
    r"pyupgrade|pre-commit|precommit|black|isort|ruff|flake8|pylint|"
    r"format(?:ting)?|style|lint|whitespace|typo|spelling|"
    r"docstring|sphinx|warning|codestyle|"
    r"D\d{3,4}|B\d{3,4}|SIM\d{3,4}|RUF\d{3,4}|E\d{3,4}|W\d{3,4}|F\d{3,4}|"
    r"dependabot|bump|changelog|release notes"
    r")\b",
    re.IGNORECASE,
)
REPAIR_EXPERIENCE_RE = re.compile(
    r"\b("
    r"fix(?:e[sd])?|bug(?:fix)?|error|fail(?:ed|s|ure)?|regression|"
    r"incorrect(?:ly)?|wrong|crash(?:es|ed)?|exception|broken|repair|"
    r"resolve(?:[sd])?|invalid"
    r")\b",
    re.IGNORECASE,
)
SPHINX_SYMBOL_RE = re.compile(
    r":(?:func|meth|class|mod|attr|obj|data|exc):`([^`]+)`"
)
BACKTICK_SYMBOL_RE = re.compile(r"`([^`\n]{2,120})`")
DOTTED_SYMBOL_RE = re.compile(
    r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)(?:\(\))?"
)
CALL_SYMBOL_RE = re.compile(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]{2,})\(\)")


def _strip_unavailable_benchmark_fields(item):
    return {k: v for k, v in dict(item).items() if k not in UNAVAILABLE_BENCHMARK_FIELDS}


def _clean_issue_text(text):
    text = HTML_COMMENT_RE.sub("\n", text or "")
    text = PGP_SIGNATURE_RE.sub("\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_target_fix_references(text, target_id):
    """Remove explicit references to the benchmark fixing PR/issue id."""
    if not text or not target_id:
        return text or ""
    target = re.escape(str(target_id))
    guarded = re.sub(
        rf"https?://github\.com/[^\s<>)\]]+/(?:pull|pulls|issues)/{target}(?:[#?][^\s<>)\]]*)?",
        "[target fixing reference removed]",
        text,
        flags=re.IGNORECASE,
    )
    guarded = re.sub(
        rf"https?://code\.djangoproject\.com/ticket/{target}(?:[#?][^\s<>)\]]*)?",
        "[target fixing reference removed]",
        guarded,
        flags=re.IGNORECASE,
    )
    guarded = re.sub(
        rf"\b(?:pr|pull\s+request|pull|issue)\s*#?\s*{target}\b",
        "[target fixing reference removed]",
        guarded,
        flags=re.IGNORECASE,
    )
    guarded = re.sub(
        rf"(?<![\w/])#\s*{target}\b",
        "[target fixing reference removed]",
        guarded,
        flags=re.IGNORECASE,
    )
    return guarded


class OfflinePatchLinkExpander:
    def _expand_patch_links(self, text):
        return text

    def extract_structure_changes_from_patch(self, patch):
        return []


class CodeAnalyzer:
    def __init__(self, config):
        self.config = config
        self.language_config = LanguageConfigFactory.get_config(config.get('language', 'python'))
        self.parser = ParserFactory.create_parser(self.language_config.language)
        self.repo_path = config['repo_path']
        self.repo = git.Repo(self.repo_path)
        self.offline_artifacts = os.getenv("KGCOMPASS_OFFLINE_ARTIFACTS", "0") == "1"
        self.github_token = GITHUB_TOKEN
        self.github = None if self.offline_artifacts else create_github_client(self.github_token)
        self.github_api = None if self.offline_artifacts else GitHubAPIMiddleware(self.github_token)
        self.max_search_depth = MAX_SEARCH_DEPTH
        self.kg = KnowledgeGraph(
            NEO4J_URI,
            NEO4J_USER,
            NEO4J_PASSWORD,
            sys.argv[1] # instance_id
        )
        self.kg.clear_graph()
        self.kg._create_indexes()
        self.expand_patch_links = os.getenv("KGCOMPASS_EXPAND_PATCH_LINKS", "0") == "1"
        self.patch_link_expander = (
            PatchLinkExpander(GITHUB_TOKEN, config['repo_name'])
            if self.expand_patch_links and not self.offline_artifacts
            else OfflinePatchLinkExpander()
        )
        self.method_search_cache = {}
        self.method_search_cache_lock = threading.Lock()
        self.method_search_locks = {}
        self.issue_cache = {}
        self.MAX_CANDIDATE_METHODS = MAX_CANDIDATE_METHODS
        self.processed_prs = set()
        self.processed_files = set()
        self.linked_issues = set()
        self.linked_issue_contents = set()
        self.searched_methods = set()
        self.artifact_stats = {"skipped_due_to_time": 0, "valid_related_items": 0}
        self.counted_valid_artifact_ids = set()
        self.counted_skipped_artifact_ids = set()
        self.target_issue_ids = {self._target_issue_number()} - {None, ""}

    def _target_issue_number(self):
        instance_id = str(self.config.get('instance_id') or '')
        if '-' not in instance_id:
            return None
        return instance_id.rsplit('-', 1)[-1]

    def _context_tokens(self, text):
        tokens = {
            token.lower()
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text or "")
            if token.lower() not in {
                "the", "and", "for", "with", "from", "this", "that", "when",
                "should", "would", "could", "error", "issue", "using",
            }
        }
        tokens.update(
            token.lower()
            for token in re.findall(r"\bv?\d+(?:\.\d+){1,4}\b", text or "", re.IGNORECASE)
        )
        return tokens

    def _score_context_text(self, root_tokens, text):
        if not root_tokens or not text:
            return 0
        text_lower = text.lower()
        return sum(1 for token in root_tokens if token in text_lower)

    def _is_boilerplate_doc_path(self, path):
        normalized = path.replace("\\", "/").lower()
        basename = os.path.basename(normalized)
        stem = os.path.splitext(basename)[0]
        if stem in BOILERPLATE_DOC_NAMES:
            return True
        return any(f"/{name}/" in normalized for name in BOILERPLATE_DOC_NAMES)

    def _should_skip_nonprod_context_path(self, path):
        """Optionally exclude test/doc/example trees from expansion-only scans."""
        if os.getenv("FL_SCAN_EXCLUDE_NONPROD_CONTEXT", "0") != "1":
            return False
        normalized = path.replace("\\", "/").lower()
        rel = os.path.relpath(normalized, self.config["repo_path"].lower()).replace("\\", "/")
        parts = [part for part in rel.split("/") if part and part != "."]
        nonprod_parts = {
            "test",
            "tests",
            "__tests__",
            "test_suite",
            "docs",
            "doc",
            "examples",
            "example",
            "tutorial",
            "tutorials",
            "benchmarks",
            "benchmark",
        }
        return any(part in nonprod_parts for part in parts)

    def _should_skip_source_extension(self, path):
        """Respect the paper-valid source-extension guard for expansion scans."""
        raw = os.getenv("KGCOMPASS_SOURCE_EXTENSIONS", "").strip()
        if not raw:
            return False
        allowed = tuple(ext.strip().lower() for ext in raw.split(",") if ext.strip())
        if not allowed:
            return False
        return not path.replace("\\", "/").lower().endswith(allowed)

    def _is_likely_code_reference(self, ref_data):
        _, full_path = ref_data
        full_path = str(full_path).strip().strip("`'\"")
        if not full_path:
            return False
        if DOMAIN_OR_EMAIL_RE.search(full_path):
            return False
        if len(full_path) > 80 and not any(sep in full_path for sep in ("/", "\\")):
            return False
        source_extensions = tuple(
            ext.strip().lower()
            for ext in os.getenv("KGCOMPASS_SOURCE_EXTENSIONS", ".py").split(",")
            if ext.strip()
        )
        path_leaf = re.split(r"[/\\]", full_path)[-1]
        if "." in path_leaf:
            suffix = "." + path_leaf.rsplit(".", 1)[-1].lower()
            if suffix in NON_SOURCE_FILE_EXTENSIONS and suffix not in source_extensions:
                return False
        target = full_path.split('.')[-1]
        if target == 'py' and '.' in full_path:
            target = full_path.split('.')[-2]
        target_lower = target.lower()
        if target_lower in COMMON_WORD_REFERENCES:
            return False
        if target_lower in NOISY_DUNDER_REFERENCES:
            return False
        if path_leaf.endswith(".py") and not any(sep in full_path for sep in ("/", "\\")):
            stem = path_leaf[:-3].lower()
            if stem in GENERIC_BASENAME_REFERENCES:
                return False
        has_qualifier = any(sep in full_path for sep in ('.', '/', '\\'))
        parts = [part for part in re.split(r"[./\\]+", full_path) if part]
        if any(part.lower().startswith("test_") or part.lower() in {"test", "tests"} for part in parts):
            return False
        if has_qualifier:
            if len(target) <= 1:
                return False
            first_part = parts[0].lower() if parts else ""
            target_is_class_like = bool(re.search(r"[A-Z][a-z]+", target))
            first_is_class_like = bool(parts and re.search(r"[A-Z][a-z]+", parts[0]))
            repo_roots = {
                os.path.basename(str(self.config.get('repo_path', '')).rstrip('/')).split("__")[-1].lower(),
                os.path.basename(str(self.config.get('repo_name', '')).rstrip('/')).lower(),
            } - {""}
            if (
                first_part in LOCAL_OR_STDLIB_QUALIFIED_PREFIXES
                and not target_is_class_like
                and "_" not in target
            ):
                return False
            if (
                target_lower in GENERIC_QUALIFIED_TARGETS
                and first_part not in repo_roots
                and not first_is_class_like
            ):
                return False
            return True
        if '_' in target:
            return True
        if target.isupper() and 2 <= len(target) <= 12:
            return True
        if re.search(r"[a-z][A-Z]|[A-Z][a-z]+[A-Z]", target):
            return True
        return False

    def _is_maintenance_commit_message(self, message):
        if os.getenv("KGCOMPASS_SKIP_MAINTENANCE_COMMITS", "1") != "1":
            return False
        first_line = (message or "").strip().splitlines()[0] if (message or "").strip() else ""
        return bool(MAINTENANCE_COMMIT_RE.search(first_line))

    def _is_repair_experience_message(self, message):
        first_lines = "\n".join((message or "").strip().splitlines()[:3])
        return bool(REPAIR_EXPERIENCE_RE.search(first_lines))

    def _mark_target_issue_id(self, issue_id):
        if issue_id is None:
            return
        issue_id = str(issue_id)
        if not issue_id:
            return
        self.target_issue_ids.add(issue_id)
        for cache_key, issue in list(self.issue_cache.items()):
            if cache_key.endswith(f":{issue_id}"):
                issue.full_body = issue.body or ""

    def _is_target_issue_id(self, issue_id, issue=None) -> bool:
        if str(issue_id) in self.target_issue_ids:
            return True
        if issue is not None and hasattr(self, "created_at") and getattr(issue, "created_at", None):
            try:
                return abs(issue.created_at.timestamp() - self.created_at) <= 60
            except Exception:
                return False
        return False

    def _clean_path(self, file_path: str) -> str:
        """Return a normalized absolute path with forward slashes.
        此函数曾经去掉 'playground/' 前缀，导致同一文件在 KG 中出现两种 path 表示
        （绝对路径 vs. 相对路径），从而使 Issue-File 与 File-Method 无法连通。

        为保持一致性，改为简单地规范化路径分隔符，并返回绝对路径。
        """
        # 统一为 Linux 风格分隔符
        path = os.path.normpath(file_path).replace('\\', '/')

        # 去掉 'playground/' 前缀
        prefix = 'playground/'
        if path.startswith(prefix):
            path_after_playground = path[len(prefix):]
        else:
            path_after_playground = path

        # 去掉仓库顶层目录（如 astropy__astropy）
        repo_dir = os.path.basename(os.path.normpath(self.config['repo_path'].rstrip('/')))
        parts = path_after_playground.split('/')
        if parts and parts[0] == repo_dir:
            path_after_playground = '/'.join(parts[1:]) if len(parts) > 1 else ''

        return path_after_playground

    def _check_and_count_artifact_time(self, artifact_timestamp, artifact_unique_id: str) -> bool:
        """
        Checks if artifact_timestamp is not later than self.created_at.
        Updates artifact_stats and counted sets. Returns True if valid, False if skipped.
        """
        unique_id = str(artifact_unique_id) # Ensure string
        if artifact_timestamp > self.created_at:
            if unique_id not in self.counted_skipped_artifact_ids:
                self.artifact_stats["skipped_due_to_time"] += 1
                self.counted_skipped_artifact_ids.add(unique_id)
            return False # Invalid due to time (too late)
        else:
            if unique_id not in self.counted_valid_artifact_ids:
                self.artifact_stats["valid_related_items"] += 1
                self.counted_valid_artifact_ids.add(unique_id)
            return True # Valid by time

    @lru_cache(maxsize=None)
    def _parser_for_file(self, file_path: str):
        if int(os.getenv("FL_SCAN_WORKERS", "1")) > 1:
            lang = language_by_extension(file_path)
            if not lang:
                return None
            return ParserFactory.create_parser(lang)
        lang = language_by_extension(file_path)
        if not lang:
            return None
        return ParserFactory.create_parser(lang)

    def analyze(self):
        """Execute complete analysis flow"""
        try:
            target_sample = self._get_target_sample()
            if not target_sample:
                return
            self._process_repository(target_sample)
            
            # Get related entities
            related_entities = self.kg.get_all_similarities_to_root(limit=SEARCH_SPACE, max_hops=4, sort=True)

            if 'methods' in related_entities:
                related_entities['methods'].sort(key=lambda x: x.get('similarity', 0), reverse=True)
            if 'classes' in related_entities:
                related_entities['classes'].sort(key=lambda x: x.get('similarity', 0), reverse=True)
            
            print("Related entity statistics:")
            for entity_type, entities in related_entities.items():
                print(f"{entity_type}: {len(entities)} entities")
            
            return {
                'related_entities': related_entities,
                'artifact_stats': self.artifact_stats,
            }
            
        except Exception as e:
            print(f"Analysis process error: {str(e)}")
            print(traceback.format_exc())
        finally:
            self._cleanup()

    # Use GitPython to get file commit information
    def get_commit_info(self, file_path):
        try:
            # Get relative file path to repository root
            repo_root = self.repo.working_tree_dir
            relative_file_path = os.path.relpath(file_path, repo_root).replace('\\', '/')
            
            if not os.path.exists(file_path):
                print(f"Warning: File {file_path} does not exist")
                return []

            commits = list(self.repo.iter_commits(paths=relative_file_path, max_count=1))
            if not commits:
                print(f"Warning: File {file_path} has no commit history")
                return []
            
            last_commit = commits[0]
            commit_id = last_commit.hexsha
            commit_message = last_commit.message.strip()

            try:
                # Use relative path to run git blame to get commit information for each line
                blame_info = self.repo.git.blame('HEAD', '--', relative_file_path).splitlines()
            except git.exc.GitCommandError as e:
                print(f"Warning: Unable to get blame information for file {file_path}: {e}")
                return []

            commit_data = []
            total_lines = len(blame_info)
            current_line = 1
            
            print(f"Start processing git blame info for {os.path.basename(file_path)} ({total_lines} lines)")
            
            for i, line in enumerate(blame_info, 1):
                if i % 100 == 0:
                    print(f"Progress: {i}/{total_lines} lines ({(i/total_lines*100):.1f}%)")
                
                try:
                    parts = line.split(')', 1)
                    if len(parts) < 2:
                        continue
                    blame_info = parts[0].split('(', 1)[1].strip()
                    blame_parts = blame_info.rsplit(' ', 2)
                    if len(blame_parts) < 3:
                        continue
                    line_commit_id = parts[0].split()[0]
                    commit_data.append((current_line, line_commit_id, commit_message))
                    current_line += 1
                except Exception as e:
                    print(f"Warning: Error processing line {i}: {e}")
                    continue
            
            print(f"Completed processing git blame info: {total_lines} lines")
            return commit_data
        except Exception as e:
            print(f"git blame error: {e}")
            print(traceback.format_exc())
            return []
    
    def _get_target_sample(self):
        """Get target sample based on configured benchmark."""
        benchmark_name = self.config.get('benchmark_name', 'swe-bench')
        target_sample_from_dataset = None # Raw item from dataset
        final_target_sample = None    # Processed item in consistent format

        print(f"Attempting to load dataset for benchmark: {benchmark_name}")
        
        # 自定义仓库模式：从本地文件或直接从 GitHub 获取
        if benchmark_name == 'custom':
            try:
                print("Custom repository mode: Fetching issue information from GitHub...")
                
                # 从 instance_id 中提取信息 (格式: owner__repo-issue_number)
                parts = self.config['instance_id'].rsplit('-', 1)
                if len(parts) != 2:
                    print(f"Error: Invalid custom instance_id format: {self.config['instance_id']}")
                    return None
                
                repo_identifier = parts[0]  # e.g., "SWE-bench__SWE-bench"
                issue_number = parts[1]      # e.g., "449"
                
                # 从 web_outputs 查找实例文件（如果存在）
                import glob
                instance_files = glob.glob(f"web_outputs/*/{self.config['instance_id']}_instance.json")
                
                if instance_files:
                    # 从本地文件加载
                    print(f"Loading instance data from local file: {instance_files[0]}")
                    with open(instance_files[0], 'r', encoding='utf-8') as f:
                        instance_data = json.load(f)
                    
                    final_target_sample = {
                        'repo': instance_data.get('repo'),
                        'instance_id': instance_data.get('instance_id'),
                        'base_commit': instance_data.get('base_commit', 'HEAD'),
                        'problem_statement': instance_data.get('problem_statement', ''),
                        'created_at': instance_data.get('created_at', datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
                        'test_patch': '',
                        'patch': '',
                        'pull_number': None,
                        'title': instance_data.get('problem_statement', '').split('\n')[0] if instance_data.get('problem_statement') else f"Issue #{issue_number}",
                    }
                    print(f"Successfully loaded custom instance from file")
                else:
                    # 直接从 GitHub 获取
                    print(f"Fetching issue #{issue_number} from GitHub for {self.config['repo_name']}...")
                    
                    try:
                        repo = self.github.get_repo(self.config['repo_name'])
                        issue = repo.get_issue(int(issue_number))
                        
                        if not issue:
                            print(f"Error: Issue #{issue_number} not found in {self.config['repo_name']}")
                            return None
                        
                        # 获取 Issue 创建时间
                        issue_created_at = issue.created_at
                        issue_created_timestamp = issue_created_at.timestamp()
                        
                        print(f"Issue #{issue_number} created at: {issue_created_at}")
                        
                        # 关键：找到 Issue 创建时刻的最新 commit
                        # 这样可以防止使用 Issue 创建之后的代码改动
                        print(f"Finding commit at Issue creation time...")
                        default_branch = repo.default_branch
                        
                        # 获取默认分支在 Issue 创建时刻之前的最新 commit
                        commits = repo.get_commits(sha=default_branch, until=issue_created_at)
                        base_commit = None
                        
                        try:
                            # 获取第一个 commit（最新的）
                            base_commit = commits[0].sha
                            print(f"Found base_commit at Issue creation time: {base_commit}")
                            print(f"  Commit date: {commits[0].commit.author.date}")
                            print(f"  Commit message: {commits[0].commit.message.split(chr(10))[0][:80]}...")
                        except (IndexError, StopIteration):
                            print(f"Warning: Could not find commit before Issue creation time, using default branch HEAD")
                            base_commit = repo.get_branch(default_branch).commit.sha
                        
                        # 设置临时的 created_at 用于后续评论过滤
                        self.created_at = issue_created_timestamp
                        
                        # Discussion comments are intentionally excluded:
                        # even pre-cutoff comments can contain maintainer hints.
                        body = issue.body or ""
                        full_body = body
                        
                        # 构造 final_target_sample
                        problem_statement = f"# {issue.title}\n\n{full_body}"
                        
                        final_target_sample = {
                            'repo': self.config['repo_name'],
                            'instance_id': self.config['instance_id'],
                            'base_commit': base_commit,  # 使用 Issue 创建时刻的 commit
                            'problem_statement': problem_statement,
                            'created_at': issue.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            'test_patch': '',
                            'patch': '',
                            'pull_number': None,
                            'title': issue.title,
                        }
                        
                        print(f"Successfully fetched issue #{issue_number} from GitHub")
                        print(f"  Title: {issue.title}")
                        print(f"  Created: {issue.created_at}")
                        print(f"  Base commit: {base_commit}")
                        print("  Issue comments included: 0")
                        
                    except Exception as e:
                        print(f"Error fetching issue from GitHub: {e}")
                        print(traceback.format_exc())
                        return None
                
                # 返回构造好的样本
                return _strip_unavailable_benchmark_fields(final_target_sample)
                
            except Exception as e:
                print(f"Error in custom repository mode: {e}")
                print(traceback.format_exc())
                return None

        if benchmark_name == 'multi-swe-bench':
            try:
                # 首先尝试从本地 swe-bench_java 目录加载
                local_data_dir = Path("swe-bench_java")
                found_item = None
                
                if local_data_dir.exists():
                    print(f"Loading from local directory: {local_data_dir}")
                    jsonl_files = list(local_data_dir.glob("*_dataset.jsonl"))
                    
                    for jsonl_file in jsonl_files:
                        try:
                            with open(jsonl_file, 'r', encoding='utf-8') as f:
                                for line in f:
                                    try:
                                        item = json.loads(line.strip())
                                        # 生成 instance_id（如果没有的话）
                                        if 'instance_id' not in item:
                                            org = item.get('org', '')
                                            repo = item.get('repo', '')
                                            number = item.get('number', '')
                                            item['instance_id'] = f"{org}__{repo}-{number}"
                                        
                                        # 检查是否匹配
                                        if (item.get('repo') == self.config['repo_name'] and
                                            item.get('instance_id') == self.config['instance_id']):
                                            found_item = item
                                            print(f"Found matching item in {jsonl_file.name}")
                                            break
                                    except json.JSONDecodeError:
                                        continue
                            if found_item:
                                break
                        except Exception as e:
                            print(f"Error reading {jsonl_file}: {e}")
                            continue
                
                # 如果本地没找到，回退到 Hugging Face
                if not found_item:
                    print("Local data not found, falling back to Hugging Face...")
                    print("Loading Daoguang/Multi-SWE-bench (java_verified)...")
                    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
                    os.environ.setdefault("HF_HUB_OFFLINE", "1")
                    ds = load_dataset(
                        "Daoguang/Multi-SWE-bench",
                        split='java_verified',
                        download_config=DownloadConfig(local_files_only=True),
                    )
                    
                    for item in ds:
                        if (item.get('repo') == self.config['repo_name'] and
                            item.get('instance_id') == self.config['instance_id']):
                            found_item = item
                            break
                
                if found_item:
                    target_sample_from_dataset = _strip_unavailable_benchmark_fields(found_item)
                    created_at_value = target_sample_from_dataset.get('created_at')
                    parsed_created_at_str = None
                    
                    if created_at_value:
                        dt_object = None
                        if isinstance(created_at_value, str):
                            try:
                                # Format 1: Already with Z
                                dt_object = datetime.strptime(created_at_value, "%Y-%m-%dT%H:%M:%SZ")
                            except ValueError:
                                try:
                                    # Format 2: Without Z, assume UTC
                                    dt_object = datetime.strptime(created_at_value, "%Y-%m-%dT%H:%M:%S")
                                except ValueError:
                                    print(f"Warning: Could not parse 'created_at' string '{created_at_value}' with known formats for multi-swe-bench.")
                        elif isinstance(created_at_value, datetime): 
                            dt_object = created_at_value
                        else:
                            try:
                                print(f"Warning: 'created_at' field was of unexpected type {type(created_at_value)} for multi-swe-bench. Attempting to convert to string and parse.")
                                dt_object = datetime.strptime(str(created_at_value), "%Y-%m-%dT%H:%M:%S")
                            except (ValueError, TypeError):
                                print(f"Warning: Could not convert or parse 'created_at' of type {type(created_at_value)}: '{created_at_value}' for multi-swe-bench.")
                        
                        if dt_object:
                            if dt_object.tzinfo is None: 
                                dt_object = dt_object.replace(tzinfo=timezone.utc)
                            else: 
                                dt_object = dt_object.astimezone(timezone.utc)
                            parsed_created_at_str = dt_object.strftime("%Y-%m-%dT%H:%M:%SZ")
                    
                    if not parsed_created_at_str:
                        print(f"Warning: 'created_at' field for multi-swe-bench not processed correctly or was missing for {target_sample_from_dataset.get('instance_id')}. Using current UTC time as placeholder.")
                        parsed_created_at_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

                    fetched_title_for_sample = ""
                    raw_issue_numbers = target_sample_from_dataset.get('issue_numbers')
                    if raw_issue_numbers and isinstance(raw_issue_numbers, list) and len(raw_issue_numbers) > 0:
                        first_issue_id_candidate = raw_issue_numbers[0]
                        if isinstance(first_issue_id_candidate, int):
                            try:
                                issue_obj_retrieved = self._get_issue_from_id(self.config['repo_name'], first_issue_id_candidate)
                                if issue_obj_retrieved and hasattr(issue_obj_retrieved, 'title') and issue_obj_retrieved.title:
                                    fetched_title_for_sample = issue_obj_retrieved.title
                            except Exception:
                                pass # Keep silent on error for brevity
                                
                    final_target_sample = {
                        'repo': target_sample_from_dataset.get('repo'),
                        'instance_id': target_sample_from_dataset.get('instance_id'),
                        'base_commit': target_sample_from_dataset.get('base_commit'), 
                        'problem_statement': target_sample_from_dataset.get('problem_statement') if target_sample_from_dataset.get('problem_statement') is not None else '',
                        'created_at': parsed_created_at_str,
                        'test_patch': target_sample_from_dataset.get('test_patch', ''),
                        'patch': target_sample_from_dataset.get('patch', ''),
                        'pull_number': target_sample_from_dataset.get('pull_number'),
                        'title': fetched_title_for_sample,
                    }
            except Exception as e:
                print(f"Error loading or processing Daoguang/Multi-SWE-bench (java_verified) dataset: {e}")
                print(traceback.format_exc())
                return None

        elif benchmark_name == 'swe-bench':
            print(f"Loading SWE-bench dataset: {DATASET_NAME}...")
            try:
                os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
                print(f"Loading {DATASET_NAME} from local cache (offline mode)...")
                ds = load_dataset(
                    DATASET_NAME,
                    download_config=DownloadConfig(local_files_only=True),
                )
                
                data_split_names_to_try = ['test', 'validation', 'train']
                data_split = None
                chosen_split_name = "None"

                for split_name_candidate in data_split_names_to_try:
                    if ds.get(split_name_candidate):
                        data_split = ds.get(split_name_candidate)
                        chosen_split_name = split_name_candidate
                        print(f"Using split: {chosen_split_name}")
                        break
                
                if not data_split: # Fallback to the first available split
                    available_splits = list(ds.keys())
                    if available_splits:
                        chosen_split_name = available_splits[0]
                        data_split = ds[chosen_split_name]
                        print(f"Using fallback split: {chosen_split_name}")
                    else:
                        print(f"Could not find any usable split in {DATASET_NAME}")
                        return None

                if not data_split: # Double check after trying fallbacks
                    print(f"No data split could be loaded from {DATASET_NAME}")
                    return None

                found_item = None
                print(f"Searching for instance_id='{self.config['instance_id']}' and repo='{self.config['repo_name']}' in split '{chosen_split_name}'.")
                
                # 打印前几个条目以供诊断
                for i, item in enumerate(data_split):
                    if i < 5: # 只打印前5个
                        print(f"  Dataset item {i}: instance_id='{item.get('instance_id')}', repo='{item.get('repo')}'")
                    
                    if (item.get('repo') == self.config['repo_name'] and
                        item.get('instance_id') == self.config['instance_id']):
                        found_item = item
                        print(f"Found matching item at index {i}.")
                        break
                
                if found_item:
                    target_sample_from_dataset = _strip_unavailable_benchmark_fields(found_item) # Create a mutable copy
                    created_at_value = target_sample_from_dataset.get('created_at')
                    parsed_created_at_str = None

                    if created_at_value:
                        dt_object = None
                        if isinstance(created_at_value, str):
                            try:
                                # Format 1: Already with Z (expected by downstream)
                                dt_object = datetime.strptime(created_at_value, "%Y-%m-%dT%H:%M:%SZ")
                            except ValueError:
                                try:
                                    # Format 2: Without Z, assume UTC
                                    dt_object = datetime.strptime(created_at_value, "%Y-%m-%dT%H:%M:%S")
                                except ValueError:
                                    print(f"Warning: Could not parse 'created_at' string '{created_at_value}' with known formats for swe-bench.")
                        elif isinstance(created_at_value, datetime):
                            dt_object = created_at_value
                        else:
                            try:
                                print(f"Warning: 'created_at' field was of unexpected type {type(created_at_value)} for swe-bench. Attempting to convert to string and parse.")
                                dt_object = datetime.strptime(str(created_at_value), "%Y-%m-%dT%H:%M:%S")
                            except (ValueError, TypeError):
                                print(f"Warning: Could not convert or parse 'created_at' of type {type(created_at_value)}: '{created_at_value}' for swe-bench.")
                        
                        if dt_object:
                            if dt_object.tzinfo is None:
                                dt_object = dt_object.replace(tzinfo=timezone.utc)
                            else:
                                dt_object = dt_object.astimezone(timezone.utc)
                            parsed_created_at_str = dt_object.strftime("%Y-%m-%dT%H:%M:%SZ")

                    if not parsed_created_at_str:
                        print(f"Warning: 'created_at' field for swe-bench not processed correctly or was missing for {target_sample_from_dataset.get('instance_id')}. Using current UTC time as placeholder.")
                        parsed_created_at_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    
                    # Update the sample with the processed created_at string
                    target_sample_from_dataset['created_at'] = parsed_created_at_str
                    final_target_sample = _strip_unavailable_benchmark_fields(target_sample_from_dataset)

                    if final_target_sample.get('instance_id') == 'django__django-10924':
                        final_target_sample['problem_statement'] = final_target_sample['problem_statement'].replace(
                            'Allow FilePathField path to accept a callable.',
                            'Allowed models.fields.FilePathField to accept a callable path.'
                        )
            except Exception as e:
                print(f"Error loading or processing SWE-bench dataset ({DATASET_NAME}): {e}")
                print(traceback.format_exc())
                return None
        else:
            print(f"Unsupported benchmark_name: {benchmark_name}")
            return None

        if not final_target_sample:
            print(f"No sample found for instance_id '{self.config['instance_id']}' in repo '{self.config['repo_name']}' for benchmark '{benchmark_name}'")
            return None

        print(f"Found target sample for benchmark {benchmark_name}:")
        print(f"  Repo: {final_target_sample.get('repo')}")
        print(f"  Instance ID: {final_target_sample.get('instance_id')}")
        print(f"  Base commit: {final_target_sample.get('base_commit')}")
        # Print only a snippet of the problem statement
        problem_statement_snippet = (final_target_sample.get('problem_statement') or "")[:200]
        print(f"  Problem: {problem_statement_snippet}...")
        print(f"  Created At: {final_target_sample.get('created_at')}")
        
        return _strip_unavailable_benchmark_fields(final_target_sample)

    def _build_file_class_methods(self, file_path):
        parser = self._parser_for_file(file_path)
        if parser is None:
            return

        # 检查文件扩展名
        if not any(file_path.endswith(ext) for ext in self.language_config.config['file_extensions']):
            return

        if self._should_skip_nonprod_context_path(file_path):
            print(f"Skip processing non-production context file: {file_path}")
            return
            
        # 检查是否为测试文件（更精确的判断）
        # 1. 检查路径中是否包含 test/tests 目录
        # 2. 检查文件名是否以测试模式开头
        import os
        path_parts = os.path.normpath(file_path).split(os.sep)
        filename = os.path.basename(file_path)
        test_file_pattern = self.language_config.config.get('test_file_pattern', '')
        
        # 判断是否为测试目录或测试文件
        is_test_dir = any(part in ['test', 'tests', '__tests__', 'test_suite'] for part in path_parts)
        is_test_file = test_file_pattern and filename.startswith(test_file_pattern)
        
        if (is_test_dir or is_test_file):
            print(f"Skip processing test file: {file_path}")
            return
            
        if file_path in self.processed_files:
            print(f"File {file_path} already processed, skipping")
            return
            
        print(f"Processing file: {file_path}")
        self.processed_files.add(file_path)
        
        # 使用语言特定的解析器
        classes = parser.extract_classes(file_path)
        
        clean_file_path = self._clean_path(file_path)
        for class_info in classes:
            class_name = class_info['name'] if class_info['name'] else '__'
            
            # 创建类实体
            self.kg.create_class_entity(
                class_name,
                clean_file_path,
                class_info['start_line'],
                class_info['end_line'],
                class_info.get('source_code', ''),
                class_info.get('doc_string', ''),
                STRONG_CONNECTION
            )
            self.kg.link_class_to_file(class_name, clean_file_path, STRONG_CONNECTION)
            
            # 处理方法
            for method in class_info.get('methods', []):
                method_name = f"{method['name']}"
                
                self.kg.create_method_entity(
                    method_name,
                    method['signature'],
                    clean_file_path,
                    method['start_line'],
                    method['end_line'],
                    method['source_code'],
                    method.get('doc_string', ''),
                    STRONG_CONNECTION
                )
                
                self.kg.link_class_to_method(
                    class_name,
                    clean_file_path,
                    method_name,
                    method['signature'],
                    STRONG_CONNECTION
                )
        # Add global methods and variables so they appear as KG nodes
        global_methods = parser.get_global_methods(file_path, self.config['repo_root'])
        global_methods.extend(parser.get_global_variables(file_path, self.config['repo_root']))
        for method in global_methods:
            self.kg.create_method_entity(
                method['name'],
                method['signature'],
                clean_file_path,
                method['start_line'],
                method['end_line'],
                method.get('source_code', ''),
                method.get('doc_string', ''),
                STRONG_CONNECTION
            )

    def _link_modified_methods_to_pr(self, issue_id):
        """
        Get modified files and methods from PR, establish corresponding entity and association relationships
        
        Args:
            issue_id (str): PR ID
        """
        if issue_id in self.processed_prs:
            print(f"PR #{issue_id} already processed, skipping")
            return
        # Get PR information
        pr = self._get_issues(self.config['repo_name'], int(issue_id))
        if not pr or not pr.pull_request:
            print(f"#{issue_id} is not a PR, skipping")
            return

        if pr.created_at.timestamp() > self.created_at - 100:
            print(f"PR #{issue_id} created later than task creation time, skipping")
            return

        # Get PR file changes
        repo = self.github.get_repo(self.config['repo_name'])
        pull = repo.get_pull(int(issue_id))

        print(f"Processing PR #{issue_id} file changes")
        for file in pull.get_files():
            file_path = os.path.join(self.config['repo_path'], file.filename)

            if self._should_skip_source_extension(file_path):
                print(f"Skipping non-source file from PR #{issue_id}: {file.filename}")
                continue

            if self._should_skip_nonprod_context_path(file_path):
                print(f"Skipping non-production file from PR #{issue_id}: {file.filename}")
                continue
            
            if not os.path.exists(file_path):
                print(f"Skipping file from PR #{issue_id} as it does not exist in the current checkout: {file.filename}")
                continue
                
            print(f"Processing file: {file_path}")
            
            # Dynamically get parser for this file
            parser = self._parser_for_file(file_path)
            if parser is None:
                print(f"No parser found for file {file_path}, skipping PR processing for this file.")
                continue
            
            # Create file entity
            self.kg.create_file_entity(self._clean_path(file_path))
            
            # Get modified line number range
            patch = file.patch
            if not patch:
                continue
                
            # Parse patch to get modified line numbers
            changes = self.patch_link_expander.extract_structure_changes_from_patch(patch)
            
            # Collect all modified line numbers
            modified_lines = set()
            for hunk in changes:
                for change in hunk['changes']:
                    if change['type'] == 'add':
                        modified_lines.add(change['new_line'])
                    elif change['type'] == 'context':
                        modified_lines.add(change['new_line'])
            sorted_lines = sorted(modified_lines)
            segments = []
            if sorted_lines:
                start_line = sorted_lines[0]  # First line number is start of current segment
                end_line = sorted_lines[0]    # Initially, end_line is also first line number

                for i in range(1, len(sorted_lines)):
                    # Check if current line and previous line are consecutive
                    if sorted_lines[i] == sorted_lines[i - 1] + 1:
                        end_line = sorted_lines[i]  # Continued, update end_line
                    else:
                        segments.append([start_line, end_line])  # Save current segment
                        start_line = sorted_lines[i]  # Start of new segment
                        end_line = sorted_lines[i]    # End of new segment
                segments.append([start_line, end_line])  # Add last segment
            
            print(f"Modified line numbers: {segments}")
            print(pull.head.sha)

            for start_line, end_line in segments:
                belongs = get_pr_file_line_belongs(pull, self.config['repo_path'], file_path, start_line, end_line, parser)
                for item in belongs['classes']:
                    print(f"Line {start_line}-{end_line} belongs to class: {item['name']}")
                    self.kg.create_class_entity(item['name'], item['file_path'], item['start_line'], item['end_line'], item.get('source_code', ''), item.get('doc_string', ''), STRONG_CONNECTION)
                    self.kg.link_class_to_issue(item['name'], item['file_path'], issue_id, STRONG_CONNECTION)
                    self.kg.link_class_to_file(item['name'], item['file_path'], STRONG_CONNECTION)
                for item in belongs['methods']:
                    print(f"Line {start_line}-{end_line} belongs to method: {item['name']}")
                    self.kg.create_method_entity(item['name'], item['signature'], item['file_path'], item['start_line'], item['end_line'], item['source_code'], item.get('doc_string', ''), STRONG_CONNECTION)
                    self.kg.link_method_to_issue(item['name'], item['signature'], item['file_path'], issue_id, STRONG_CONNECTION)
                    self.kg.link_method_to_file(item['name'], item['signature'], item['file_path'], STRONG_CONNECTION)
                # 如果未找到任何类或方法，则回退到整体文件级解析
                if not belongs['classes'] and not belongs['methods']:
                    print(f"No class/method matched lines {start_line}-{end_line}, fallback to whole file")
                    # 解析并创建整个文件的类与方法实体，再全部关联到该 PR
                    clean_file_path = self._clean_path(file_path)
                    self._build_file_class_methods(file_path)
                    # 建立文件与 PR 的关系
                    self.kg.link_issue_to_file(issue_id, clean_file_path, STRONG_CONNECTION)
                    # 获取刚刚写入 KG 的类/方法节点评估
                    all_classes = parser.extract_classes(file_path)
                    all_methods = parser.get_global_methods(file_path, self.config['repo_root'])
                    all_methods.extend(parser.get_global_variables(file_path, self.config['repo_root']))
                    for cls in all_classes:
                        self.kg.link_class_to_issue(cls['name'], cls['file_path'], issue_id, NORMAL_CONNECTION)
                    for m in all_methods:
                        self.kg.link_method_to_issue(m['name'], m['signature'], m['file_path'], issue_id, NORMAL_CONNECTION)
                    # 跳过后续按 belongs 处理的逻辑
                    continue
        print(f"Completed processing PR #{issue_id} modified methods")
        # Add to processed cache
        self.processed_prs.add(issue_id)

    def _process_reference(self, issue_id, ref_data, multipler = 1):
        ref_type, full_path = ref_data
        if full_path in self.searched_methods:
            return
        
        with self.lock: # Assuming self.lock is initialized elsewhere (e.g., in _link_reference_to_issue_faster)
            if full_path in self.searched_methods:
                return
            self.searched_methods.add(full_path)
        
        module_parts = full_path.split('.')
        target_name = module_parts[-1]
        if target_name == 'py' and len(module_parts) > 1: # Python-specific heuristic
            target_name = module_parts[-2]
        
        base_path = self.config['repo_path']
        initial_path_resolver_config = self.parser.language_config

        possible_paths_generated = []
        possible_paths_generated.extend(initial_path_resolver_config.resolve_qualified_name_to_file_paths(base_path, module_parts))
        if len(module_parts) > 1:
            possible_paths_generated.extend(initial_path_resolver_config.resolve_qualified_name_to_file_paths(base_path, module_parts[:-1]))

        possible_paths = []
        seen_paths = set()
        for type_hint, path_str in possible_paths_generated:
            if path_str not in seen_paths:
                possible_paths.append((type_hint, path_str))
                seen_paths.add(path_str)

        find_by_kg = self.kg.search_file_by_path(target_name) 
        if find_by_kg:
            for file_node in find_by_kg:
                kg_file_path = file_node['file']['path']
                if kg_file_path not in seen_paths:
                    possible_paths.append(('file', kg_file_path))
                    seen_paths.add(kg_file_path)
        
        found_specific_entity = False
        processed_files_for_this_ref = set()

        for path_type_hint, file_path_candidate in possible_paths:
            resolved_path = file_path_candidate
            if not os.path.exists(resolved_path) and not os.path.isabs(file_path_candidate):
                resolved_path = os.path.join(self.config['repo_path'], file_path_candidate)
            if not os.path.exists(resolved_path):
                continue
            file_path_candidate = resolved_path

            actual_parser = self._parser_for_file(file_path_candidate)
            if not actual_parser:
                continue

            if os.path.isdir(file_path_candidate):
                if path_type_hint == 'package': 
                    print(f"Processing directory import/reference: {file_path_candidate}")
                    self.kg.create_directory_structure(file_path_candidate, self, True, multipler * STRONG_CONNECTION)
                    found_specific_entity = True 
                    current_lang_extensions = actual_parser.language_config.config['file_extensions']
                    for item_name in os.listdir(file_path_candidate):
                        if any(item_name.endswith(ext) for ext in current_lang_extensions):
                            dir_file_path = os.path.join(file_path_candidate, item_name)
                            if os.path.isfile(dir_file_path) and dir_file_path not in processed_files_for_this_ref:
                                print(f"Associated directory file: {dir_file_path}")
                                clean_dir_file_path = self._clean_path(dir_file_path)
                                self.kg.create_file_entity(clean_dir_file_path)
                                self.kg.link_issue_to_file(issue_id, clean_dir_file_path, multipler * NORMAL_CONNECTION)
                                self._build_file_class_methods(dir_file_path)
                                processed_files_for_this_ref.add(dir_file_path)
                continue 
            
            if file_path_candidate in processed_files_for_this_ref:
                continue

            print(f"Processing file candidate for reference '{full_path}': {file_path_candidate} using {actual_parser.language_config.language} parser")
            clean_file_path_candidate = self._clean_path(file_path_candidate)
            classes = actual_parser.extract_classes(file_path_candidate)
            methods = actual_parser.get_global_methods(file_path_candidate, self.config['repo_root'])
            methods.extend(actual_parser.get_global_variables(file_path_candidate, self.config['repo_root']))

            self.kg.link_issue_to_file(issue_id, clean_file_path_candidate, multipler * STRONG_CONNECTION)
            self._build_file_class_methods(file_path_candidate)
            processed_files_for_this_ref.add(file_path_candidate)
            # Marking found_specific_entity = True here because we successfully processed a directly resolved file path.
            # Specific entity linking below is a bonus.
            found_specific_entity = True 

            entity_linked_in_file = False
            for class_info in classes:
                if class_info['name'] == target_name: 
                    print(f"Matched class by target_name: {class_info['name']}")
                    self.kg.link_class_to_issue(class_info['name'], clean_file_path_candidate, issue_id, multipler * NORMAL_CONNECTION)
                    entity_linked_in_file = True
                for method_info in class_info.get('methods', []):
                    if method_info['name'] == target_name:
                        print(f"Matched method by target_name: {method_info['name']}")
                        self.kg.link_method_to_issue(method_info['name'], method_info['signature'], clean_file_path_candidate, issue_id, multipler * NORMAL_CONNECTION)
                        entity_linked_in_file = True
            
            for method_info in methods:
                if method_info['name'] == target_name:
                    print(f"Matched global method/variable by target_name: {method_info['name']}")
                    self.kg.link_method_to_issue(method_info['name'], method_info['signature'], clean_file_path_candidate, issue_id, multipler * NORMAL_CONNECTION)
                    entity_linked_in_file = True
            
            # No need to set found_specific_entity again if entity_linked_in_file is true, as it's already true from file processing.

        if not found_specific_entity:
            print(f"No specific entity found by direct path resolution for '{full_path}'. Falling back to name search for '{target_name}'.")
            found_files_by_name_search = self._search_method_by_name(self.config['repo_path'], target_name)
            
            for file_match_info in found_files_by_name_search:
                file_path_from_search = file_match_info['path']
                match_type_from_search = file_match_info['type']

                if file_path_from_search in processed_files_for_this_ref:
                    continue

                actual_parser_for_searched_file = self._parser_for_file(file_path_from_search)
                if not actual_parser_for_searched_file:
                    continue

                print(f"Found '{target_name}' via name search in file: {file_path_from_search} (match type: {match_type_from_search})")
                clean_file_path_from_search = self._clean_path(file_path_from_search)
                self.kg.link_issue_to_file(issue_id, clean_file_path_from_search, multipler * WEAK_CONNECTION)
                self._build_file_class_methods(file_path_from_search)
                processed_files_for_this_ref.add(file_path_from_search)
                found_specific_entity = True 

                s_classes = actual_parser_for_searched_file.extract_classes(file_path_from_search)
                s_methods = actual_parser_for_searched_file.get_global_methods(file_path_from_search, self.config['repo_root'])
                s_methods.extend(actual_parser_for_searched_file.get_global_variables(file_path_from_search, self.config['repo_root']))

                for class_info in s_classes:
                    if class_info['name'] == target_name: 
                        self.kg.link_class_to_issue(class_info['name'], clean_file_path_from_search, issue_id, multipler * WEAK_CONNECTION)
                    for method_info in class_info.get('methods', []):
                        if method_info['name'] == target_name:
                            self.kg.link_method_to_issue(method_info['name'], method_info['signature'], clean_file_path_from_search, issue_id, multipler * WEAK_CONNECTION)
                for method_info in s_methods:
                    if method_info['name'] == target_name:
                        self.kg.link_method_to_issue(method_info['name'], method_info['signature'], clean_file_path_from_search, issue_id, multipler * WEAK_CONNECTION)

        if not found_specific_entity:
            # Use double quotes for the main f-string to allow single quotes inside for variable values
            print(f"Reference '{full_path}' (target: '{target_name}') could not be resolved to a specific file or entity after all attempts.")

    def _link_reference_to_issue_faster(self, issue_id, issue_content, multipler = 1):
        issue_content = _clean_issue_text(issue_content)
        if issue_id in self.linked_issues or issue_content in self.linked_issue_contents:
            print(f"Issue/PR #{issue_id} already processed, skipping")
            return
        self.linked_issues.add(issue_id)
        self.linked_issue_contents.add(issue_content)
        print(f"Processing Issue/PR #{issue_id} references")
        ref_list = get_reference_functions_from_text(self.config['repo_path'], issue_content, self.parser, self.method_search_cache)
        print(ref_list)
        self._link_reference_candidates_to_issue(issue_id, ref_list, multipler)

    def _link_reference_candidates_to_issue(self, issue_id, ref_list, multipler=1):
        if not ref_list:
            print(f"No references found for Issue/PR #{issue_id}, skipping reference linking.")
            return
        if os.getenv("KGCOMPASS_STRICT_IDENTIFIER_FILTER", "0") == "1":
            before = len(ref_list)
            ref_list = [ref for ref in ref_list if self._is_likely_code_reference(ref)]
            print(f"[identifier-filter] kept {len(ref_list)}/{before} code-like references")
            if not ref_list:
                return
        if not hasattr(self, 'lock'):
            self.lock = threading.Lock()
        # Use thread pool to process references in parallel
        with ThreadPoolExecutor(max_workers=min(16, len(ref_list))) as executor:
            # Create task list
            future_to_ref = {
                executor.submit(self._process_reference, issue_id, ref_data, multipler): (ref_data, issue_id)
                for ref_data in ref_list
            }
            
            # Process completed tasks
            for idx, future in enumerate(as_completed(future_to_ref), 1):
                ref_data = future_to_ref[future]
                try:
                    future.result()
                    print(f"Completed processing reference [{idx}/{len(ref_list)}]: {ref_data[0]} -> {ref_data[1]}")
                except Exception as e:
                    print(f"Error processing reference {ref_data[0]} -> {ref_data[1]}: {str(e)}")

    def _link_stacktrace_to_issue(self, issue_id, issue_content):
        issue_content = _clean_issue_text(issue_content)
        # Extract method information from stack trace
        stack_methods = extract_methods_from_traceback(self.repo.working_tree_dir, self.config['repo_root'], issue_content, self.kg, self.parser)
        for method_info in stack_methods:
            print(f"Found method from stack trace: {method_info}")

            # Reconstruct the full path to check for existence
            full_path_for_check = method_info['file_path']
            if not os.path.isabs(full_path_for_check):
                full_path_for_check = os.path.join(self.config['repo_path'], os.path.normpath(full_path_for_check))
            if os.path.exists(full_path_for_check):
                clean_file_path = self._clean_path(full_path_for_check)
                # Create method entity
                self.kg.create_method_entity(
                    method_info['name'],
                    method_info.get('signature', ''),
                    clean_file_path,
                    method_info.get('line_number', 0),
                    method_info.get('line_number', 0),
                    method_info.get('source_code', ''),
                    method_info.get('doc_string', ''),
                    STRONG_CONNECTION
                )
                
                # Establish method-root_issue association
                self.kg.link_method_to_issue(
                    method_info['name'],
                    method_info.get('signature', ''),
                    clean_file_path,
                    issue_id,
                    STRONG_CONNECTION
                )

    def _link_source_files_to_issue(self, issue_id: str, issue_content: str):
        """Links source files mentioned in the issue content to the issue node."""
        issue_content = _clean_issue_text(issue_content)
        if not issue_content:
            return

        # Extract raw matches, then normalize to a flat source-file list.
        text_analyzer = TextAnalyzer(self.github_token)
        raw_matches = text_analyzer.extract_matches(issue_content, self.config['repo_name'])
        source_files = []
        if isinstance(raw_matches, dict):
            source_files.extend(raw_matches.get('python_files', []))
        elif isinstance(raw_matches, list):
            # Backward compatibility if analyzer output shape changes.
            source_files.extend(raw_matches)
        
        # Fallback for Python-specific extraction if no generic links found and main language is Python
        # This part needs generalization for other languages or better generic link extraction
        if not source_files and self.config.get('language') == 'python':
            python_specific_files = get_python_files_from_content(issue_content, self.repo_path, self.config['repo_name'])
            source_files.extend([f for f in python_specific_files if f not in source_files])

        # New logic to handle multiple language extensions
        # If self.language_config is set (meaning a primary language is defined for the run)
        if hasattr(self, 'language_config') and self.language_config:
            try:
                # Access the 'config' attribute which holds the loaded configuration
                current_lang_extensions = self.language_config.config['file_extensions']
            except KeyError:
                print(f"Warning: 'file_extensions' not found in language_config for {self.language_config.language}")
                current_lang_extensions = []
        else: # Fallback or if no specific language config is primary
            current_lang_extensions = [ext for lang_config in EXT_LANG_MAP.values() 
                                       for ext in LanguageConfigFactory.get_config(lang_config).config['file_extensions']]
            current_lang_extensions = list(set(current_lang_extensions)) # Unique extensions


        # Deduplicate while preserving order.
        source_files = list(dict.fromkeys(source_files))
        linked_files_count = 0

        for file_path_ref in source_files:
            if any(file_path_ref.endswith(ext) for ext in current_lang_extensions):
                resolved_path = file_path_ref
                if not os.path.exists(resolved_path) and not os.path.isabs(file_path_ref):
                    resolved_path = os.path.join(self.config['repo_path'], file_path_ref)
                if os.path.exists(resolved_path):
                    clean_file_path = self._clean_path(resolved_path)
                    print(f"Found file reference in Issue #{issue_id}: {clean_file_path}")
                    # Create file entity and establish association
                    self.kg.create_file_entity(clean_file_path)
                    self.kg.link_issue_to_file(issue_id, clean_file_path)
                    self._build_file_class_methods(resolved_path) # This uses self.parser
                    linked_files_count += 1

        print(f"Found source file references in Issue #{issue_id} (filtered by current language): {linked_files_count}")

    def _get_issue_from_id(self, repo_name, issue_id):
        if self.offline_artifacts:
            print(f"[offline-artifacts] skip GitHub issue lookup for #{issue_id}")
            return None
        # Create cache key
        cache_key = f"{repo_name}:{issue_id}"
        # Check cache
        if cache_key in self.issue_cache:
            print(f"Retrieved issue #{issue_id} from cache")
            return self.issue_cache[cache_key]
        repo = self.github.get_repo(repo_name)
        try:
            issue = repo.get_issue(int(issue_id))
        except:
            return None
        
        # Get original content
        body = _strip_target_fix_references(
            _clean_issue_text(issue.body or ""),
            self._target_issue_number(),
        )
        issue.kg_title = _strip_target_fix_references(
            issue.title or "",
            self._target_issue_number(),
        )
        
        # Discussion comments are excluded for all issue/PR artifacts. Even
        # pre-cutoff comments can contain maintainer-provided localization hints.
        issue.full_body = body

        print(f"Found issue/PR #{issue_id}; comments excluded by design")
        # Save to cache
        self.issue_cache[cache_key] = issue
        return issue

    def _get_issues(self, repo_name, issue_id=None, title=None, time_range=None):
        if self.offline_artifacts:
            if issue_id is None:
                print("[offline-artifacts] skip GitHub issue search")
                return []
            print(f"[offline-artifacts] skip GitHub issue lookup for #{issue_id}")
            return None
        if repo_name == 'django/django':
            print('Django Issues / PRs')
            if issue_id is not None:
                print('issue_id is not None', issue_id)
                cache_key = f"{repo_name}:{issue_id}"
                if cache_key in self.issue_cache:
                    print(f"Retrieved issue #{issue_id} from cache")
                    return self.issue_cache[cache_key]
                try:
                    issue = None
                    if self.github_token:
                        issue = self._get_issue_from_id(repo_name, issue_id)
                    if issue is not None:
                        print('Found issue/PR', issue.number)
                        return issue
                    if self.github_token:
                        print(f"GitHub issue/PR #{issue_id} not found; falling back to Django Trac")
                    else:
                        print(f"No GitHub token configured; using Django Trac for #{issue_id}")
                except Exception as e:
                    print(f"GitHub lookup failed: {e}")
                # If not found on GitHub, try Django Trac. In clean
                # localization runs without a GitHub token this avoids PyGithub
                # rate-limit backoff while preserving the same Trac artifact.
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                print('Issue id is', issue_id)
                url = f"https://code.djangoproject.com/ticket/{issue_id}"

                # 添加重试逻辑处理网络错误
                max_retries = 3
                response = None
                for attempt in range(max_retries):
                    try:
                        response = requests.get(url, headers=headers, timeout=15)
                        break  # 成功则退出循环
                    except (requests.exceptions.SSLError,
                            requests.exceptions.ConnectionError,
                            requests.exceptions.Timeout) as e:
                        if attempt < max_retries - 1:
                            wait_time = 2 ** attempt  # 指数退避: 1s, 2s, 4s
                            print(f"⚠️  Attempt {attempt + 1}/{max_retries} failed for Django ticket #{issue_id}: {type(e).__name__}")
                            print(f"   Retrying in {wait_time} seconds...")
                            time.sleep(wait_time)
                        else:
                            print(f"❌ All {max_retries} attempts failed for Django ticket #{issue_id}: {e}")
                            print(f"   Continuing without this ticket information...")
                            return None
                    except requests.exceptions.RequestException as e:
                        print(f"❌ Unexpected request error for Django ticket #{issue_id}: {e}")
                        return None

                if response is None:
                    print(f"❌ Failed to fetch Django ticket #{issue_id} after {max_retries} attempts")
                    return None
                print('response of django ticket', url, response.status_code)
                if response.status_code == 200:
                        soup = BeautifulSoup(response.text, 'html.parser')
                        
                        # Get title
                        title_element = soup.find('h1', {'class': 'title'})
                        title = title_element.text.strip() if title_element else f"Django Ticket #{issue_id}"
                        title = _strip_target_fix_references(title, self._target_issue_number())
                        
                        # Get time information
                        timeline_link = soup.find('a', {'class': 'timeline'})
                        issue_time = None
                        if timeline_link:
                            href = timeline_link.get('href', '')
                            print(f"Django Ticket #{issue_id}: Found timeline link: {href}")
                            time_param = re.search(r'from=(.*?)(?:&|$)', href)
                            if time_param:
                                time_str = time_param.group(1).replace('%3A', ':')
                                print(f"Django Ticket #{issue_id}: Extracted time string: '{time_str}'")
                                try:
                                    # Process time zone information
                                    if '-' in time_str[10:]:
                                        dt_str, tz_str = time_str.rsplit('-', 1)
                                        dt = datetime.strptime(dt_str, '%Y-%m-%dT%H:%M:%S')
                                        # Convert to UTC
                                        offset = timedelta(hours=int(tz_str.split(':')[0]), 
                                                        minutes=int(tz_str.split(':')[1]))
                                        issue_time = (dt + offset)
                                        
                                        # Check and count ticket time validity
                                        is_valid_ticket_time = self._check_and_count_artifact_time(issue_time.timestamp(), f"django_{issue_id}")
                                        if not is_valid_ticket_time:
                                            print(f"Django Ticket #{issue_id} creation time {issue_time} later than current task time {datetime.fromtimestamp(self.created_at, timezone.utc)}. Skipping.")
                                            return None
                                    else:
                                        issue_time = datetime.strptime(time_str, '%Y-%m-%dT%H:%M:%S')
                                        if issue_time.timestamp() > self.created_at:
                                            print(f"Issue creation time {issue_time} later than current task time {datetime.fromtimestamp(self.created_at)}")
                                            return None
                                except ValueError as e:
                                    print(f"Django Ticket #{issue_id}: Failed to parse time string '{time_str}'. Error: {e}")
                                    return None
                            else:
                                print(f"Django Ticket #{issue_id}: Could not find time parameter in href: {href}")
                        else:
                            print(f"Django Ticket #{issue_id}: Could not find timeline link in HTML.")

                        if not issue_time:
                            print(f"Django Ticket #{issue_id}: Abandoning ticket due to missing or unparsable creation time.")
                            return None
                        
                        # Get author
                        author_element = soup.find('td', {'headers': 'h_reporter'})
                        author = author_element.text.strip() if author_element else "Unknown"
                        
                        # Get content
                        description_element = soup.find('div', {'class': 'description'})
                        content = html2text.html2text(str(description_element))
                        # Discussion comments are excluded for all tickets.
                        full_content = _strip_target_fix_references(
                            _clean_issue_text(content),
                            self._target_issue_number(),
                        )
                        class DjangoTicket:
                            def __init__(self, number, title, author, content, full_body, created_at):
                                self.number = number
                                self.title = title
                                self.body = content
                                self.full_body = full_body
                                self.pull_request = None  # Django tickets are not PRs
                                self.user = type('User', (), {'login': author})()
                                self.created_at = created_at
                                self.state = 'open'  # Default state
                            def get_timeline(self):
                                return []
                        
                        ticket = DjangoTicket(
                            int(issue_id),
                            title,
                            author,
                            content,
                            full_content,
                            issue_time
                        )
                        self.issue_cache[cache_key] = ticket
                        return ticket
                else: # Ticket not found
                    return None
            elif time_range is not None:
                start_time, end_time = time_range
                # Convert timestamp to ISO 8601 format date string
                start_date = datetime.fromtimestamp(start_time).strftime('%Y-%m-%d')
                end_date = datetime.fromtimestamp(end_time).strftime('%Y-%m-%d')
                search_query = f'repo:{repo_name} is:issue created:{start_date}..{end_date} sort:created-desc'
                matching_issues = self.github.search_issues(search_query)
                return matching_issues
        if issue_id is not None:
            issue = self._get_issue_from_id(repo_name, issue_id)
            return issue
        elif title is not None:
            search_query = f'repo:{repo_name} is:issue {title} in:title sort:created-desc'
        elif time_range is not None:
            start_time, end_time = time_range
            # Convert timestamp to ISO 8601 format date string
            start_date = datetime.fromtimestamp(start_time).strftime('%Y-%m-%d')
            end_date = datetime.fromtimestamp(end_time).strftime('%Y-%m-%d')
            search_query = f'repo:{repo_name} is:issue created:{start_date}..{end_date} sort:created-desc'
        else:
            search_query = f'repo:{repo_name} is:issue sort:created-desc'
        matching_issues = self.github_api.search_issues(
            search_query,
            max_results=None,  # 不限制结果数，或设置具体数字如 5000
            use_cache=True     # 启用缓存
        )
        return matching_issues

    def _search_method_by_name(self, repo_root, method_name):
        cache_key = f"{repo_root}:{method_name}"
        with self.method_search_cache_lock:
            if cache_key in self.method_search_cache:
                print(f"Retrieved method {method_name} search results from cache")
                return self.method_search_cache[cache_key]
            search_lock = self.method_search_locks.setdefault(cache_key, threading.Lock())

        with search_lock:
            with self.method_search_cache_lock:
                if cache_key in self.method_search_cache:
                    print(f"Retrieved method {method_name} search results from cache")
                    return self.method_search_cache[cache_key]

            return self._search_method_by_name_uncached(repo_root, method_name, cache_key)

    def _search_method_by_name_uncached(self, repo_root, method_name, cache_key):
        matching_files = []
        print(f"Searching methods or global variables {method_name} in repository {repo_root}")
        strict_name_search = os.getenv("KGCOMPASS_NAME_SEARCH_STRICT", "0") == "1"
        allowed_rule_types = {"method", "class", "global_var"}

        # Get all supported extensions from the language factory
        all_supported_extensions = list(EXT_LANG_MAP.keys())

        cnt = 0
        # Iterate through all files in the repository
        for root, dirs, files in os.walk(repo_root):
            # Skip .git directory and other common non-code directories if needed
            dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', 'node_modules', 'build', 'dist']]
            if os.getenv("FL_SCAN_EXCLUDE_NONPROD_CONTEXT", "0") == "1":
                dirs[:] = [
                    d for d in dirs
                    if d.lower() not in {
                        "test", "tests", "__tests__", "test_suite",
                        "docs", "doc", "examples", "example",
                        "tutorial", "tutorials", "benchmarks", "benchmark",
                    }
                ]
            for file_name in files:
                # Check if the file extension is one of the supported ones
                if not any(file_name.endswith(ext) for ext in all_supported_extensions):
                    continue

                file_path = os.path.join(root, file_name)
                if self._should_skip_nonprod_context_path(file_path):
                    continue
                
                # Skip test files if not relevant (can be made more configurable)
                # This simple check might need to be adapted based on language-specific test file patterns
                if 'test' in file_path.lower() and 'pytest' not in file_path.lower(): 
                    # More robust check would use parser.language_config.get_config().get('test_file_pattern')
                    # but self.parser might not be the right one for the current file_path here.
                    # For now, a simple heuristic.
                    continue

                parser = self._parser_for_file(file_path)
                if not parser:
                    # print(f"No parser for {file_path}, skipping in _search_method_by_name")
                    continue

                # Get language-specific search patterns
                search_patterns = parser.language_config.get_search_patterns(method_name)
                if not search_patterns:
                    continue
                
                try:
                    content = read_file(file_path) # Assuming read_file reads the entire file as a string
                    if method_name not in content: # Quick check to avoid regex on irrelevant files
                        continue

                    # Check each rule for the current language
                    found_in_file = False
                    for rule_type, pattern in search_patterns.items():
                        if strict_name_search and rule_type not in allowed_rule_types:
                            continue
                        if re.search(pattern, content, re.MULTILINE):
                            print(f"Found matching {rule_type} rule: {pattern}, file: {file_path}")
                            matching_files.append({
                                'path': file_path,
                                'type': rule_type # This type is from the perspective of the regex rule
                            })
                            cnt += 1
                            found_in_file = True
                            break # Found a match in this file, move to the next file
                    
                except Exception as e:
                    print(f"Error reading or searching file {file_path}: {e}")
                    continue
                
                if cnt > 20: # Increased limit slightly, can be configured
                    print(f"Search limit of {cnt} reached, stopping search.")
                    break  # Break from inner loop (files in current directory)
            if cnt > 20:
                break # Break from outer loop (os.walk)

        print(f"Completed searching methods or global variables {method_name} in repository {repo_root}, found {len(matching_files)} files after processing {cnt} matches.")
        with self.method_search_cache_lock:
            self.method_search_cache[cache_key] = matching_files
        return matching_files

    def _process_repository(self, target_sample):
        """Process code repository"""
        # Clean hidden issue-template comments before indexing the visible report.
        problem_statement = _strip_target_fix_references(
            _clean_issue_text(target_sample['problem_statement']),
            self._target_issue_number(),
        )
        # Paper-valid runs keep the original issue text only. Expanding linked
        # patches or commit hashes can introduce future repair artifacts.
        if self.expand_patch_links:
            problem_statement = self.patch_link_expander._expand_patch_links(problem_statement)
        else:
            print("[leakage-guard] patch/commit link expansion disabled")
        
        # Update target_sample content
        target_sample['problem_statement'] = problem_statement
        
        # Switch to specified commit
        base_commit = target_sample.get('base_commit')
        if base_commit:
            print(f"Switching to commit: {base_commit}")
            try:
                self._checkout_commit(base_commit)
            except Exception as e:
                print(f"⚠️  Warning: Could not checkout commit {base_commit}: {e}")
                print("📍 Using current HEAD instead")
                # 尝试切换到 main 分支
                try:
                    self.repo.git.checkout('main')
                    print("✅ Switched to main branch")
                except:
                    try:
                        self.repo.git.checkout('master')
                        print("✅ Switched to master branch")
                    except:
                        print("ℹ️  Staying at current HEAD")
        else:
            print("ℹ️  No base_commit specified, using current HEAD")
        # Convert creation time to UTC timestamp
        self.created_at = (
            datetime.strptime(target_sample['created_at'], "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=timezone.utc)
        ).timestamp()

        # 0. Create directory structure
        print('======> Step 0. Creating directory structure')
        self.kg.create_directory_structure(self.config['repo_path'], self, False, STRONG_CONNECTION)

        # 1. Create root node from the original issue description.
        root_id = 'root'
        root_content = f"{target_sample['problem_statement']}"

        # Extract title from first line of problem description
        title = target_sample['problem_statement'].split('\n')[0].strip()
        print(f"======> Step 1. Extracted title from problem description: {title}")
        
        # Create root node
        self.kg.create_issue_entity(
            root_id,
            title,
            '\n'.join(root_content.split('\n')[1:]),        # content
            self.created_at,  # created_at
            #datetime.now(timezone.utc).timestamp(),  # created_at
            "open",             # state
            False,              # is_pr
            "root"        # name
        )
        # The root task itself is always considered a valid item for context.
        if "root_task" not in self.counted_valid_artifact_ids:
             self.artifact_stats["valid_related_items"] += 1
             self.counted_valid_artifact_ids.add("root_task") # Special ID for the root task itself
        
        # # Extract file references and methods from root node content
        if root_content:
            # Extract reference information
            self._link_source_files_to_issue(root_id, root_content)
            self._link_stacktrace_to_issue(root_id, root_content)
            self._link_reference_to_issue_faster(root_id, root_content, 1)
            self._link_documentation_context_to_issue(root_id, root_content)
            self._link_doc_symbol_context_to_issue(root_id, root_content)
            self._link_historical_repair_experience_to_issue(root_id, root_content)
            self._link_historical_commit_context_to_issue(root_id, root_content)
            self._link_tag_context_to_issue(root_id, root_content)

        # 2. Extract related issues from the issue description.
        text = root_content
        issue_ids = set(re.findall(r'#(\d+)', text))
        # Try to find matching issue/PR on GitHub
        print(f"======> Step 2. Extract related issues from issue description\nSearch repository: {self.config['repo_name']}")
        # Use GitHub search API directly to find matching issue
        max_similarity = 0
        best_match_issue = None
        end_time = self.created_at + 8 * 60 * 60
        start_time = end_time - (60 * 24 * 60 * 60)  # Number of seconds in 60 days
        time_range = (start_time, end_time)
        if self.config['repo_name'] == 'django/django':
            import pandas as pd
            df = pd.read_csv('django-tickets.csv')
            candidates = []
            for _, row in df.iterrows():
                title_clean = title.lower().replace('.', '').replace(' ', '')
                issue_title_clean = row['Summary'].lower().replace('.', '').replace(' ', '')
                same_length = pylcs.lcs(title_clean, issue_title_clean)
                similarity = same_length / max(len(title_clean), len(issue_title_clean))
                created_at = datetime.strptime(row['Created'].split()[0], "%Y年%m月%d日").timestamp()
                if created_at > self.created_at:
                    continue
                candidates.append((similarity, int(row['id'])))
            for similarity, candidate_id in sorted(candidates, reverse=True):
                print(f"Trying best Django ticket candidate: {candidate_id} with similarity {similarity}, max_similarity: {max_similarity}")
                potential_issue = self._get_issues('django/django', issue_id=candidate_id)
                print('potential_issue', potential_issue)
                if potential_issue:
                    max_similarity = similarity
                    best_match_issue = potential_issue
                    break
        else:
            for issue in self._get_issues(self.config['repo_name'], time_range=time_range):
                # Time check and count for each issue from search
                if not self._check_and_count_artifact_time(issue.created_at.timestamp(), f"gh_{issue.number}"):
                    print(f"GitHub search result Issue #{issue.number} created at {issue.created_at}, later than task. Skipping for similarity.")
                    continue # Skip this issue for similarity comparison

                title_clean = title.lower().replace('.', '').replace(' ', '')
                issue_title_clean = issue.title.lower().replace('.', '').replace(' ', '')
                # Calculate similarity
                same_length = pylcs.lcs(title_clean, issue_title_clean)
                similarity = same_length / max(len(title_clean), len(issue_title_clean))
                # Update best match
                if similarity > max_similarity:
                    max_similarity = similarity
                    best_match_issue = issue
                
        # If a sufficiently similar issue is found, establish association
        if best_match_issue:
            self._mark_target_issue_id(best_match_issue.number)
            issue_ids.add(str(best_match_issue.number))
            self.kg.create_issue_entity_by_github_issue(self._get_issues(self.config['repo_name'], int(best_match_issue.number)))
            print(f"Found best match {'PR' if best_match_issue.pull_request else 'Issue'} #{best_match_issue.number}, similarity: {max_similarity}")
            print(best_match_issue.title)
        root_related_issues = list(issue_ids)
        # 3. Process issues and related issues
        print('======> Step 3. Start processing issues and related issues')
        issue_ids = self._process_issues(list(issue_ids))
        # 4. Establish root node-related issues association
        print('======> Step 4. Establish root node-related issues association')
        for issue_id in root_related_issues:
            self.kg.link_issues(root_id, str(issue_id), STRONG_CONNECTION)
            print(f"Established root node-issue association: root -[RELATED]-> #{issue_id}")
        # 5. Extract related files from issues content
        print('======> Step 5. Extract related files from issues content')
        for issue_id in issue_ids:
            try:
                issue = self._get_issues(self.config['repo_name'], int(issue_id))
                if issue is None:
                    print(f"Issue #{issue_id} does not exist")
                    continue
                print('Analyzing issue', issue.number)
                content = f"{issue.title}\n{issue.full_body or ''}".strip()
                self._link_source_files_to_issue(issue_id, content)
                self._link_stacktrace_to_issue(issue_id, content)
            except Exception as e:
                print(f"Error processing issue #{issue_id} content: {e}")
        # 6. Optional method-call expansion. Paper-valid evidence-graph runs
        # disable this step because the seed list comes from embedding-ranked
        # methods; the reported graph-only retrieval should be driven by typed
        # evidence paths rather than embedding-selected call expansion.
        if os.getenv("KGCOMPASS_ENABLE_METHOD_CALL_EXPANSION", "1") == "1":
            print("======> Step 6. Starting scanning project to find related methods")
            self._scan_project_for_related_methods(self.kg.get_all_methods(self.MAX_CANDIDATE_METHODS))
        else:
            print("[evidence-graph] method-call expansion disabled")
        print('======> Completed')

    def _scan_project_for_related_methods(self, all_methods):
        """Scan project to find methods with call relationships to existing methods"""
        print("Starting scanning project to find related methods...")

        # Keep legacy behavior by default: scan all supported source extensions.
        # Set FL_SCAN_CURRENT_LANG_ONLY=1 to restrict to benchmark language extensions.
        current_lang_only = os.getenv("FL_SCAN_CURRENT_LANG_ONLY", "0") == "1"
        if current_lang_only:
            scan_extensions = self.language_config.config.get('file_extensions', [])
            print(f"[scan] FL_SCAN_CURRENT_LANG_ONLY=1, scanning current language only: {scan_extensions}")
        else:
            scan_extensions = list(EXT_LANG_MAP.keys())
            print(f"[scan] scanning all supported extensions: {scan_extensions}")

        source_files = get_source_files_by_extensions(self.config['repo_path'], scan_extensions)
        # Exclude heavy vendored/native trees from call scanning by default.
        # Can be overridden via FL_SCAN_EXCLUDE_SUBPATHS, comma-separated.
        exclude_raw = os.getenv(
            "FL_SCAN_EXCLUDE_SUBPATHS",
            "extern/,vendor/,vendored/,_vendor/,third_party/,.pyinstaller/",
        )
        exclude_subpaths = [
            p.strip().replace("\\", "/")
            for p in exclude_raw.split(",")
            if p.strip()
        ]
        if exclude_subpaths:
            before_cnt = len(source_files)
            source_files = [
                fp for fp in source_files
                if not any(sub in fp.replace("\\", "/") for sub in exclude_subpaths)
            ]
            print(
                f"[scan] excluded {before_cnt - len(source_files)} files "
                f"by subpaths={exclude_subpaths}"
            )
        if os.getenv("FL_SCAN_EXCLUDE_NONPROD_CONTEXT", "0") == "1":
            before_cnt = len(source_files)
            source_files = [
                fp for fp in source_files
                if not self._should_skip_nonprod_context_path(fp)
            ]
            print(
                f"[scan] excluded {before_cnt - len(source_files)} "
                f"non-production context files"
            )

        total_files = len(source_files)
        scan_workers = max(1, int(os.getenv("FL_SCAN_WORKERS", "1")))
        if scan_workers == 1:
            for idx, file_path in enumerate(source_files, 1):
                self._scan_single_file_for_related_methods(file_path, idx, total_files, all_methods)
            return

        with ThreadPoolExecutor(max_workers=min(scan_workers, total_files)) as executor:
            future_to_file = {
                executor.submit(
                    self._scan_single_file_for_related_methods,
                    file_path,
                    idx,
                    total_files,
                    all_methods,
                ): file_path
                for idx, file_path in enumerate(source_files, 1)
            }
            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"Error processing file {file_path} for method calls: {str(e)}")

    def _scan_single_file_for_related_methods(self, file_path, idx, total_files, all_methods):
        parser = self._parser_for_file(file_path)
        if parser is None:
            return

        print(f"\nScanning for method calls in [{idx}/{total_files}]: {file_path}")
        try:
            clean_file_path = self._clean_path(file_path)
            parser_lang = parser.language_config.language
            # C++ parser currently does not implement call-edge extraction; skip import/call-analysis overhead.
            analyze_calls = parser_lang != 'cpp'
            imports = parser.get_imports(file_path) if analyze_calls else {}
            local_methods = []
            global_methods = parser.get_global_methods(file_path, self.config['repo_root'])
            local_methods.extend(global_methods)

            classes = parser.extract_classes(file_path)
            for class_info in classes:
                class_name = class_info.get('name') or '__'
                self.kg.create_class_entity(
                    class_name,
                    clean_file_path,
                    class_info['start_line'],
                    class_info['end_line'],
                    class_info.get('source_code', ''),
                    class_info.get('doc_string', ''),
                    STRONG_CONNECTION
                )
                self.kg.link_class_to_file(class_name, clean_file_path, STRONG_CONNECTION)
                for method in class_info.get('methods', []):
                    local_methods.append(method)
                    method_name = method.get('name', '')
                    self.kg.create_method_entity(
                        method_name,
                        method.get('signature', method_name),
                        clean_file_path,
                        method.get('start_line', 0),
                        method.get('end_line', method.get('start_line', 0)),
                        method.get('source_code', ''),
                        method.get('doc_string', ''),
                        STRONG_CONNECTION
                    )
                    if method_name:
                        self.kg.link_class_to_method(
                            class_name,
                            clean_file_path,
                            method_name,
                            method.get('signature', method_name),
                            STRONG_CONNECTION
                        )

            for local_method_info in local_methods:
                local_method_name = local_method_info.get('name', '')
                local_method_info['file_path'] = clean_file_path
                self.kg.create_method_entity(
                    local_method_name,
                    local_method_info.get('signature', local_method_name),
                    clean_file_path,
                    local_method_info.get('start_line', 0),
                    local_method_info.get('end_line', local_method_info.get('start_line', 0)),
                    local_method_info.get('source_code', ''),
                    local_method_info.get('doc_string', ''),
                    STRONG_CONNECTION
                )
                if analyze_calls:
                    parser.analyze_method_calls_in_method(
                        local_method_info,
                        all_methods,
                        self.kg,
                        imports,
                        self.config['repo_root']
                    )
        except Exception as e:
            print(f"Error processing file {file_path} for method calls: {str(e)}")

    def extend_issue_connection(self, issue_id):
        extended_issue_ids = set()
        issue = self._get_issues(self.config['repo_name'], int(issue_id))
        if issue is None:
            print(f"Issue #{issue_id} does not exist")
            return extended_issue_ids
        # Get basic information
        title = issue.title
        content = issue.full_body or ""
        created_at_ts = issue.created_at.timestamp() # Renamed to avoid conflict
        is_pr = issue.pull_request is not None

        # Check and count the main issue being extended
        issue_unique_id = f"gh_{issue_id}" if not self.config['repo_name'] == 'django/django' else f"django_{issue_id}"
        if not self._check_and_count_artifact_time(created_at_ts, issue_unique_id):
            print(f"Branch 0: Issue/PR #{issue_id} created at {issue.created_at}, later than current repair task, skipping extension.")
            return extended_issue_ids
        
        # avoid the potential data leakage of issues and pull requests
        # This specific PR time check seems redundant if covered by the above _check_and_count_artifact_time
        # if created_at_ts > self.created_at or created_at_ts > self.created_at - 100 and is_pr:
        #     print(f"Branch 0: Issue/PR #{issue_id} created at {issue.created_at}, later than current repair task, skipping")
        #     return extended_issue_ids
        if content:
            # Find all referenced issues/PRs
            refs = get_ref_ids(self.config['repo_name'], title + '\n' + content)             
            # Process each reference
            for ref_id in refs:
                try:
                    ref_issue = self._get_issues(self.config['repo_name'], int(ref_id))
                    if ref_issue is None:
                        print(f"Issue #{ref_id} does not exist")
                        continue
                    
                    # Check and count referenced issue time
                    ref_issue_unique_id = f"gh_{ref_id}" if not self.config['repo_name'] == 'django/django' else f"django_{ref_id}"
                    if not self._check_and_count_artifact_time(ref_issue.created_at.timestamp(), ref_issue_unique_id):
                        print(f"Branch 2: Referenced Issue #{ref_issue.number} created at {ref_issue.created_at}, later than current repair task, skipping.")
                        continue

                    ref_is_pr = ref_issue.pull_request is not None
                    if ref_id in extended_issue_ids:
                        continue
                    # Use unified creation method
                    extended_issue_ids.add(ref_id)
                    self.kg.create_issue_entity_by_github_issue(self._get_issues(self.config['repo_name'], int(ref_id)))
                    
                    # Use unified association method
                    self.kg.link_issues(str(issue_id), str(ref_id), NORMAL_CONNECTION)
                    print(f"Established issue text cross-reference relationship: #{issue_id} -[RELATED]-> #{ref_id}")
                    
                except Exception as e:
                    print(f"Error processing reference #{ref_id}: {e}")
        
        # Timeline cross-reference events can be generated by comments. Keep them
        # disabled for the no-comments paper setting.
        if os.getenv("KGCOMPASS_USE_TIMELINE", "0") != "1":
            print(f"Skip timeline cross-reference events for #{issue_id} in no-comments mode")
        else:
            print(f"Timeline cross-reference events are disabled in this no-comments implementation")
        print(f"Successfully processed {'PR' if is_pr else 'Issue'} #{issue_id}: {title} ")
        return extended_issue_ids

    def _link_documentation_context_to_issue(self, issue_id, root_content):
        if os.getenv("KGCOMPASS_ENABLE_DOC_CONTEXT", "0") != "1":
            return

        limit = max(0, int(os.getenv("KGCOMPASS_DOC_CONTEXT_LIMIT", "8")))
        if limit <= 0:
            return

        root_tokens = self._context_tokens(root_content)
        candidates = []
        allowed_exts = {".md", ".rst", ".txt"}
        for root, dirs, files in os.walk(self.config["repo_path"]):
            rel_root = os.path.relpath(root, self.config["repo_path"]).replace("\\", "/")
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d not in {"build", "dist", "__pycache__", "node_modules"}
            ]
            in_doc_tree = rel_root == "docs" or rel_root.startswith("docs/")
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in allowed_exts:
                    continue
                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, self.config["repo_path"]).replace("\\", "/")
                if self._is_boilerplate_doc_path(rel_path):
                    continue
                basename = filename.lower()
                if not in_doc_tree and not basename.startswith(("readme", "changelog", "whatsnew", "release")):
                    continue
                try:
                    if os.path.getsize(file_path) > 250_000:
                        continue
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        text = _clean_issue_text(f.read())
                except Exception:
                    continue
                score = self._score_context_text(root_tokens, f"{rel_path}\n{text[:40000]}")
                if score > 0:
                    candidates.append((score, rel_path, text[:40000]))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        selected = candidates[:limit]
        print(f"[doc-context] selected {len(selected)} documentation files")
        for score, rel_path, text in selected:
            print(f"[doc-context] score={score} file={rel_path}")
            self._link_source_files_to_issue(issue_id, text)
            ref_list = get_reference_functions_from_text(
                self.config["repo_path"],
                text,
                self.parser,
                self.method_search_cache,
            )
            self._link_reference_candidates_to_issue(issue_id, ref_list, multipler=1.5)

    def _clean_doc_symbol(self, raw_symbol):
        symbol = (raw_symbol or "").strip()
        if "<" in symbol and ">" in symbol:
            symbol = symbol.rsplit("<", 1)[-1].split(">", 1)[0]
        symbol = symbol.strip("`'\" \t\r\n.,:;[]{}")
        symbol = symbol.lstrip("~")
        symbol = re.sub(r"\(\)$", "", symbol)
        symbol = symbol.split("#", 1)[0].strip()
        if not symbol or " " in symbol or len(symbol) > 100:
            return None
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", symbol):
            return None
        if symbol.startswith(".") or symbol.endswith("."):
            return None
        if (
            "." not in symbol
            and "_" not in symbol
            and not symbol.isupper()
            and not re.search(r"[a-z][A-Z]|[A-Z][a-z]+[A-Z]", symbol)
        ):
            return None
        ref_data = ("doc_symbol", symbol)
        if not self._is_likely_code_reference(ref_data):
            return None
        return symbol

    def _extract_doc_symbols(self, text, limit):
        symbols = []
        seen = set()
        for pattern in (SPHINX_SYMBOL_RE, BACKTICK_SYMBOL_RE, DOTTED_SYMBOL_RE, CALL_SYMBOL_RE):
            for raw_symbol in pattern.findall(text or ""):
                symbol = self._clean_doc_symbol(raw_symbol)
                if not symbol or symbol in seen:
                    continue
                seen.add(symbol)
                symbols.append(symbol)
                if len(symbols) >= limit:
                    return symbols
        return symbols

    def _resolve_symbol_to_source_files(self, symbol, max_files=3, allow_name_search=False):
        clean_symbol = re.sub(r"\(\)$", "", symbol or "").strip()
        if not clean_symbol:
            return []
        module_parts = clean_symbol.split(".")
        target_name = module_parts[-1]
        if target_name == "py" and len(module_parts) > 1:
            target_name = module_parts[-2]

        possible_paths = []
        seen = set()
        generated = []
        generated.extend(
            self.parser.language_config.resolve_qualified_name_to_file_paths(
                self.config["repo_path"],
                module_parts,
            )
        )
        if len(module_parts) > 1:
            generated.extend(
                self.parser.language_config.resolve_qualified_name_to_file_paths(
                    self.config["repo_path"],
                    module_parts[:-1],
                )
            )
        for _, path_str in generated:
            resolved_path = path_str
            if not os.path.exists(resolved_path) and not os.path.isabs(path_str):
                resolved_path = os.path.join(self.config["repo_path"], path_str)
            if os.path.isfile(resolved_path) and resolved_path not in seen:
                possible_paths.append(resolved_path)
                seen.add(resolved_path)

        find_by_kg = self.kg.search_file_by_path(target_name)
        if find_by_kg:
            for file_node in find_by_kg:
                kg_file_path = file_node["file"]["path"]
                resolved_path = kg_file_path
                if not os.path.exists(resolved_path) and not os.path.isabs(kg_file_path):
                    resolved_path = os.path.join(self.config["repo_path"], kg_file_path)
                if os.path.isfile(resolved_path) and resolved_path not in seen:
                    possible_paths.append(resolved_path)
                    seen.add(resolved_path)

        if allow_name_search and len(possible_paths) < max_files:
            for file_match in self._search_method_by_name(self.config["repo_path"], target_name):
                path = file_match.get("path")
                if os.path.isfile(path) and path not in seen:
                    possible_paths.append(path)
                    seen.add(path)
                    if len(possible_paths) >= max_files:
                        break

        source_paths = []
        current_lang_extensions = self.language_config.config.get("file_extensions", [])
        for file_path in possible_paths:
            if current_lang_extensions and not any(file_path.endswith(ext) for ext in current_lang_extensions):
                continue
            if self._should_skip_nonprod_context_path(file_path):
                continue
            if self._parser_for_file(file_path) is None:
                continue
            source_paths.append(file_path)
            if len(source_paths) >= max_files:
                break
        return source_paths

    def _link_doc_symbol_context_to_issue(self, issue_id, root_content):
        if os.getenv("KGCOMPASS_ENABLE_DOC_SYMBOL_CONTEXT", "0") != "1":
            return

        limit = max(0, int(os.getenv("KGCOMPASS_DOC_SYMBOL_CONTEXT_LIMIT", "8")))
        max_symbols_per_doc = max(1, int(os.getenv("KGCOMPASS_DOC_SYMBOL_MAX_SYMBOLS", "24")))
        max_files_per_symbol = max(1, int(os.getenv("KGCOMPASS_DOC_SYMBOL_MAX_FILES", "3")))
        allow_name_search = os.getenv("KGCOMPASS_DOC_SYMBOL_NAME_SEARCH", "0") == "1"
        if limit <= 0:
            return

        root_tokens = self._context_tokens(root_content)
        allowed_exts = {".md", ".rst", ".txt"}
        candidates = []
        for root, dirs, files in os.walk(self.config["repo_path"]):
            rel_root = os.path.relpath(root, self.config["repo_path"]).replace("\\", "/")
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d not in {"build", "dist", "__pycache__", "node_modules"}
            ]
            in_doc_tree = rel_root in {".", "docs", "doc"} or rel_root.startswith(("docs/", "doc/"))
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in allowed_exts:
                    continue
                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, self.config["repo_path"]).replace("\\", "/")
                if self._is_boilerplate_doc_path(rel_path):
                    continue
                basename = filename.lower()
                if not in_doc_tree and not basename.startswith(("readme", "changelog", "whatsnew", "release", "history")):
                    continue
                try:
                    if os.path.getsize(file_path) > 250_000:
                        continue
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        text = _clean_issue_text(f.read())
                except Exception:
                    continue
                score = self._score_context_text(root_tokens, f"{rel_path}\n{text[:40000]}")
                if score > 0:
                    candidates.append((score, rel_path, text[:40000]))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        selected = candidates[:limit]
        print(f"[doc-symbol-context] selected {len(selected)} documentation files")
        for score, rel_path, text in selected:
            symbols = self._extract_doc_symbols(text, max_symbols_per_doc)
            linked_files = set()
            print(f"[doc-symbol-context] score={score} file={rel_path} symbols={len(symbols)}")
            for symbol in symbols:
                for file_path in self._resolve_symbol_to_source_files(
                    symbol,
                    max_files=max_files_per_symbol,
                    allow_name_search=allow_name_search,
                ):
                    linked_files.add(file_path)

            if not linked_files:
                continue
            doc_hash = hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:12]
            doc_id = f"doc:{issue_id}:{doc_hash}"
            self.kg.create_documentation_entity(doc_id, os.path.basename(rel_path), text[:2000], rel_path)
            self.kg.link_issue_to_documentation(issue_id, doc_id, NORMAL_CONNECTION)
            for file_path in sorted(linked_files):
                clean_file_path = self._clean_path(file_path)
                self.kg.create_file_entity(clean_file_path)
                self.kg.link_documentation_to_file(doc_id, clean_file_path, NORMAL_CONNECTION)
                self._build_file_class_methods(file_path)

    def _link_historical_repair_experience_to_issue(self, issue_id, root_content):
        if os.getenv("KGCOMPASS_ENABLE_REPAIR_EXPERIENCE_CONTEXT", "0") != "1":
            return

        limit = max(0, int(os.getenv("KGCOMPASS_REPAIR_EXPERIENCE_LIMIT", "12")))
        min_score = max(0, int(os.getenv("KGCOMPASS_REPAIR_EXPERIENCE_MIN_SCORE", "3")))
        max_scan = max(limit, int(os.getenv("KGCOMPASS_REPAIR_EXPERIENCE_SCAN", "600")))
        max_files = max(1, int(os.getenv("KGCOMPASS_REPAIR_EXPERIENCE_MAX_FILES", "20")))
        if limit <= 0:
            return

        root_tokens = self._context_tokens(root_content)
        until_dt = datetime.fromtimestamp(self.created_at, timezone.utc)
        try:
            commits = list(
                self.repo.iter_commits(
                    "HEAD",
                    max_count=max_scan,
                    until=until_dt.isoformat(),
                )
            )
        except Exception as e:
            print(f"[repair-experience] unable to read local commit history: {e}")
            return

        current_lang_extensions = self.language_config.config.get("file_extensions", [])
        candidates = []
        for commit in commits:
            if len(commit.parents) != 1:
                continue
            message = _clean_issue_text(commit.message or "")
            if self._is_maintenance_commit_message(message):
                continue
            if not self._is_repair_experience_message(message):
                continue
            try:
                changed_files = list(commit.stats.files.keys())
            except Exception:
                changed_files = []
            if len(changed_files) > max_files:
                continue
            source_files = [
                rel_path for rel_path in changed_files
                if not self._is_boilerplate_doc_path(rel_path)
                and (
                    not current_lang_extensions
                    or any(rel_path.endswith(ext) for ext in current_lang_extensions)
                )
                and not self._should_skip_nonprod_context_path(
                    os.path.join(self.config["repo_path"], rel_path)
                )
            ]
            if not source_files:
                continue
            score_text = message + "\n" + "\n".join(source_files)
            score = self._score_context_text(root_tokens, score_text)
            if score < min_score:
                continue
            candidates.append((score, commit, source_files))

        candidates.sort(key=lambda item: (-item[0], -item[1].committed_date))
        selected = candidates[:limit]
        print(
            f"[repair-experience] selected {len(selected)} repair commits before "
            f"{until_dt.isoformat()} (min_score={min_score})"
        )
        for score, commit, changed_files in selected:
            message = _clean_issue_text(commit.message or "")
            exp_id = f"repair:{commit.hexsha}"
            title = commit.summary[:160]
            print(f"[repair-experience] score={score} commit={commit.hexsha[:12]} {title}")
            self.kg.create_experience_entity(
                exp_id,
                title,
                message[:2000],
                "historical_repair_commit",
                commit.committed_date,
            )
            self.kg.link_issue_to_experience(issue_id, exp_id, STRONG_CONNECTION)
            for rel_path in changed_files[:max_files]:
                if self._is_boilerplate_doc_path(rel_path):
                    continue
                if current_lang_extensions and not any(rel_path.endswith(ext) for ext in current_lang_extensions):
                    continue
                file_path = os.path.join(self.config["repo_path"], rel_path)
                if not os.path.exists(file_path):
                    continue
                if self._should_skip_nonprod_context_path(file_path):
                    continue
                clean_file_path = self._clean_path(file_path)
                self.kg.create_file_entity(clean_file_path)
                self.kg.link_experience_to_file(exp_id, clean_file_path, NORMAL_CONNECTION)
                self._build_file_class_methods(file_path)

    def _link_historical_commit_context_to_issue(self, issue_id, root_content):
        if os.getenv("KGCOMPASS_ENABLE_COMMIT_CONTEXT", "0") != "1":
            return

        limit = max(0, int(os.getenv("KGCOMPASS_COMMIT_CONTEXT_LIMIT", "20")))
        max_scan = max(limit, int(os.getenv("KGCOMPASS_COMMIT_CONTEXT_SCAN", "300")))
        max_files = max(1, int(os.getenv("KGCOMPASS_COMMIT_CONTEXT_MAX_FILES", "40")))
        if limit <= 0:
            return

        root_tokens = self._context_tokens(root_content)
        until_dt = datetime.fromtimestamp(self.created_at, timezone.utc)
        try:
            commits = list(
                self.repo.iter_commits(
                    "HEAD",
                    max_count=max_scan,
                    until=until_dt.isoformat(),
                )
            )
        except Exception as e:
            print(f"[commit-context] unable to read local commit history: {e}")
            return

        current_lang_extensions = self.language_config.config.get("file_extensions", [])
        candidates = []
        for commit in commits:
            if len(commit.parents) != 1:
                continue
            message = _clean_issue_text(commit.message or "")
            if self._is_maintenance_commit_message(message):
                continue
            try:
                changed_files = list(commit.stats.files.keys())
            except Exception:
                changed_files = []
            if len(changed_files) > max_files:
                continue
            source_files = [
                rel_path for rel_path in changed_files
                if not self._is_boilerplate_doc_path(rel_path)
                and (
                    not current_lang_extensions
                    or any(rel_path.endswith(ext) for ext in current_lang_extensions)
                )
                and not self._should_skip_nonprod_context_path(
                    os.path.join(self.config["repo_path"], rel_path)
                )
            ]
            if not source_files:
                continue
            score_text = message + "\n" + "\n".join(source_files)
            score = self._score_context_text(root_tokens, score_text)
            if score <= 0:
                continue
            candidates.append((score, commit, source_files))

        candidates.sort(key=lambda item: (-item[0], -item[1].committed_date))
        selected = candidates[:limit]
        print(f"[commit-context] selected {len(selected)} commits before {until_dt.isoformat()}")
        for score, commit, changed_files in selected:
            commit_id = commit.hexsha
            message = _clean_issue_text(commit.message or "")
            print(f"[commit-context] score={score} commit={commit_id[:12]} {commit.summary[:100]}")
            self.kg.create_commit_entity(commit_id, message)
            self.kg.link_issue_to_commit(issue_id, commit_id, NORMAL_CONNECTION)

            if os.getenv("KGCOMPASS_COMMIT_CONTEXT_PARSE_MESSAGE_REFS", "0") == "1":
                ref_list = get_reference_functions_from_text(
                    self.config["repo_path"],
                    message,
                    self.parser,
                    self.method_search_cache,
                )
                self._link_reference_candidates_to_issue(issue_id, ref_list, multipler=1.5)

            for rel_path in changed_files[:30]:
                if self._is_boilerplate_doc_path(rel_path):
                    continue
                if current_lang_extensions and not any(rel_path.endswith(ext) for ext in current_lang_extensions):
                    continue
                file_path = os.path.join(self.config["repo_path"], rel_path)
                if not os.path.exists(file_path):
                    continue
                clean_file_path = self._clean_path(file_path)
                self.kg.create_file_entity(clean_file_path)
                self.kg.link_commit_to_file(commit_id, clean_file_path, NORMAL_CONNECTION)
                self._build_file_class_methods(file_path)

    def _link_tag_context_to_issue(self, issue_id, root_content):
        if os.getenv("KGCOMPASS_ENABLE_TAG_CONTEXT", "0") != "1":
            return

        limit = max(0, int(os.getenv("KGCOMPASS_TAG_CONTEXT_LIMIT", "8")))
        if limit <= 0:
            return

        root_tokens = self._context_tokens(root_content)
        current_lang_extensions = self.language_config.config.get("file_extensions", [])
        candidates = []
        for tag in self.repo.tags:
            try:
                tag_ref = getattr(tag, "tag", None)
                tag_message = tag_ref.message if tag_ref and getattr(tag_ref, "message", None) else ""
                tag_time = (
                    tag_ref.tagged_date
                    if tag_ref and getattr(tag_ref, "tagged_date", None)
                    else tag.commit.committed_date
                )
                if tag_time and tag_time > self.created_at:
                    continue
                score_text = f"{tag.name}\n{tag_message}\n{tag.commit.summary}"
                score = self._score_context_text(root_tokens, score_text)
                if score <= 0:
                    continue
                candidates.append((score, tag_time or 0, tag, tag_message))
            except Exception:
                continue

        candidates.sort(key=lambda item: (-item[0], -item[1], item[2].name))
        selected = candidates[:limit]
        print(f"[tag-context] selected {len(selected)} tags")
        for score, _, tag, tag_message in selected:
            commit = tag.commit
            commit_id = commit.hexsha
            message = _clean_issue_text(f"Tag {tag.name}\n{tag_message}\n{commit.message or ''}")
            print(f"[tag-context] score={score} tag={tag.name} commit={commit_id[:12]}")
            self.kg.create_commit_entity(commit_id, message)
            self.kg.link_issue_to_commit(issue_id, commit_id, NORMAL_CONNECTION)

            try:
                changed_files = list(commit.stats.files.keys())
            except Exception:
                changed_files = []
            for rel_path in changed_files[:20]:
                if self._is_boilerplate_doc_path(rel_path):
                    continue
                if current_lang_extensions and not any(rel_path.endswith(ext) for ext in current_lang_extensions):
                    continue
                file_path = os.path.join(self.config["repo_path"], rel_path)
                if not os.path.exists(file_path):
                    continue
                clean_file_path = self._clean_path(file_path)
                self.kg.create_file_entity(clean_file_path)
                self.kg.link_commit_to_file(commit_id, clean_file_path, WEAK_CONNECTION)
                self._build_file_class_methods(file_path)

    def _process_issues(self, issue_ids, depth=0):
        """Process collected issues/PRs and establish association relationships"""
        print(f"Recursively processing issues/PRs: {self.kg.encountered_issues}, depth: {depth}")
        for issue_id in issue_ids:
            self._link_modified_methods_to_pr(issue_id)

        if depth >= self.max_search_depth:
            print(f"Recursion depth exceeds {self.max_search_depth} layers, skipping")
            return issue_ids
        
        new_issue_ids = set(issue_ids)
        added_issue_ids = set()
        for issue_id in issue_ids:
            print(f"Processing ID: {issue_id}")
            added_issue_ids.update(self.extend_issue_connection(issue_id))
            self.kg.encountered_issues.update(added_issue_ids)
        print(f'New Issue IDs: {added_issue_ids}')
        if added_issue_ids:
            new_issue_ids.update(self._process_issues(added_issue_ids, depth + 1))
        return list(new_issue_ids)

    def _cleanup(self):
        """Clean up resources"""
        # First clean working directory
        try:
            print("Cleaning working directory...")
            # Force clean untracked files
            self.repo.git.clean('-fd')
            # Abandon local modifications
            self.repo.git.reset('--hard')
            print("Working directory cleaned")                    
        except Exception as e:
            print(f"Error during cleanup: {e}")
        print('Cleanup completed')

    def _checkout_commit(self, commit_hash):
        """
        Switch to specified commit
        
        Args:
            commit_hash (str): Commit hash to switch to
        """
        try:
            print(f"Switching to commit: {commit_hash}")
            # Use -f parameter to force switch, will discard all local changes
            self.repo.git.checkout('-f', commit_hash)
            print(f"Successfully switched to commit: {commit_hash}")
            
        except Exception as e:
            print(f"Error switching commit: {e}")
            print(traceback.format_exc())
            raise

    def _extract_references_from_commit_message(self, commit, pr_node_id=None, issue_node_id=None):
        if not commit.message:
            return

        # Use the main parser for analyzing commit messages
        references = get_reference_functions_from_text(
            self.config['repo_name'], 
            commit.message, 
            self.parser, 
            exclude_set=set()
        )

        print(f"Commit {commit.sha} message references: {references}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print('[USAGE] python fl.py <instance_id> <repo_path> <fl_location_dir> [benchmark_name]')
        print('benchmark_name defaults to \'swe-bench\' if not provided. Use \'multi-swe-bench\' for Java Multi-SWE-bench instances.')
        sys.exit(1)

    start_time = datetime.now()
    print(f"Starting execution time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    instance_id_arg = sys.argv[1]
    repo_path_arg = sys.argv[2]
    fl_location_dir_arg = sys.argv[3]
    benchmark_name_arg = 'swe-bench' # Default value
    if len(sys.argv) > 4:
        benchmark_name_arg = sys.argv[4]

    repo_name = None
    if benchmark_name_arg == 'custom':
        # Custom repository format: OWNER__REPO-ISSUENUMBER (e.g., SWE-bench__SWE-bench-449)
        # Repo name format: OWNER/REPO (e.g., SWE-bench/SWE-bench)
        parts = instance_id_arg.rsplit('-', 1)  # Split from right to handle repo names with hyphens
        if len(parts) == 2:
            owner_repo_part = parts[0]  # e.g., "SWE-bench__SWE-bench"
            if '__' in owner_repo_part:
                repo_name = owner_repo_part.replace('__', '/', 1)  # "SWE-bench/SWE-bench"
            else:
                # Fallback if no double underscore
                repo_name = owner_repo_part.replace('_', '/', 1)
                print(f"Warning: Instance_id '{instance_id_arg}' for custom repo did not contain '__'. Used single '_' replacement: '{repo_name}'")
        else:
            print(f"Error: Could not parse custom instance_id '{instance_id_arg}' to extract owner/repo part.")
            sys.exit(1)
        
        if not repo_name or '/' not in repo_name:
            print(f"Error: Failed to derive a valid 'owner/repo' format from instance_id '{instance_id_arg}' for custom repo. Result: '{repo_name}'")
            sys.exit(1)
            
        print(f"Custom repository mode: repo_name='{repo_name}'")
        
    elif benchmark_name_arg == 'multi-swe-bench':
        # Instance ID format: OWNER__REPO-ISSUENUMBER (e.g., apache__dubbo-10638)
        # Dataset 'repo' field format: OWNER/REPO (e.g., apache/dubbo)
        parts = instance_id_arg.split('-')
        if len(parts) > 0: # Ensure there is content before any hyphen
            owner_repo_part = '-'.join(parts[:-1]) # Takes the part before the first hyphen, e.g., "apache__dubbo"
            if '__' in owner_repo_part:
                repo_name = owner_repo_part.replace('__', '/', 1) # Replace the first double underscore
            else:
                # Fallback if no double underscore, try single (less likely for this format based on example)
                repo_name = owner_repo_part.replace('_', '/', 1)
                print(f"Warning: Instance_id '{instance_id_arg}' for multi-swe-bench did not contain '__'. Used single '_' replacement: '{repo_name}'")
        else:
            print(f"Error: Could not parse multi-swe-bench instance_id '{instance_id_arg}' to extract owner/repo part.")
            sys.exit(1)
        
        if not repo_name or '/' not in repo_name:
             print(f"Error: Failed to derive a valid 'owner/repo' format from instance_id '{instance_id_arg}' ('{owner_repo_part}') for multi-swe-bench. Result: '{repo_name}'. Please check instance_id.")
             sys.exit(1)

    else: # swe-bench (default)
        instance_parts = instance_id_arg.split('-')
        repo_part = '-'.join(instance_parts[:-1])
        repo_name = repo_part.replace('__', '/')

    # 确定语言
    if benchmark_name_arg == 'multi-swe-bench':
        language = 'java'
    elif benchmark_name_arg == 'custom':
        # 对于自定义仓库，默认使用 Python，后续可以根据仓库实际情况自动检测
        language = 'python'
    else:  # swe-bench
        language = 'python'
    
    config = {
        'repo_path': f'playground/{repo_path_arg}/',
        'repo_name': repo_name, 
        'repo_root': repo_name.split('/')[-1],
        'instance_id': instance_id_arg,
        'benchmark_name': benchmark_name_arg,
        'language': language
    }

    print(f"Configuration: {config}")

    analyzer = CodeAnalyzer(config)
    result = analyzer.analyze()

    if result is None:
        # _get_target_sample() 已经打印了 "No sample found..."
        # _cleanup() 已经在 analyze() 方法的 finally 中被调用
        print(f"Analysis returned no result for {instance_id_arg}. Exiting with error status.")
        sys.exit(1) # 以非零状态码退出
    
    result["kg_params"] = {
        "decay_factor": DECAY_FACTOR,
        "vector_similarity_weight": VECTOR_SIMILARITY_WEIGHT,
    }
    result["run_meta"] = {
        "instance_id": instance_id_arg,
        "repo_name": repo_name,
        "benchmark_name": benchmark_name_arg,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }

    output_file_path = os.path.join(fl_location_dir_arg, f"{instance_id_arg}.json")
    with open(output_file_path, 'w') as f:
        json.dump(result, f, indent=4)
    print(f"Results saved to: {output_file_path}")
    
    end_time = datetime.now()
    print(f"Completed execution time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    duration = end_time - start_time
    print(f"Total execution duration: {duration}")
