import json
import os
import sys
from bs4 import BeautifulSoup
import requests
import traceback
import git
import re
import pylcs
from github import Github
from datetime import datetime, timedelta, timezone
from datasets import load_dataset
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
    TextAnalyzer
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
)
from language_factory import LanguageConfigFactory, ParserFactory, language_by_extension, EXT_LANG_MAP
from functools import lru_cache

class CodeAnalyzer:
    def __init__(self, config):
        self.config = config
        self.language_config = LanguageConfigFactory.get_config(config.get('language', 'python'))
        self.parser = ParserFactory.create_parser(self.language_config.language)
        self.repo_path = config['repo_path']
        self.repo = git.Repo(self.repo_path)
        self.github_token = GITHUB_TOKEN
        self.github = Github(self.github_token)
        self.max_search_depth = MAX_SEARCH_DEPTH
        self.kg = KnowledgeGraph(
            NEO4J_URI,
            NEO4J_USER,
            NEO4J_PASSWORD,
            sys.argv[1] # instance_id
        )
        self.kg.clear_graph()
        self.kg._create_indexes()
        self.patch_link_expander = PatchLinkExpander(GITHUB_TOKEN, config['repo_name'])
        self.method_search_cache = {}
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

        if benchmark_name == 'multi-swe-bench':
            try:
                print("Loading Daoguang/Multi-SWE-bench (java_verified)...")
                ds = load_dataset("Daoguang/Multi-SWE-bench", split='java_verified')
                
                found_item = None
                for item in ds:
                    if (item.get('repo') == self.config['repo_name'] and
                        item.get('instance_id') == self.config['instance_id']):
                        found_item = item
                        break
                
                if found_item:
                    target_sample_from_dataset = found_item
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
                # 尝试强制重新下载数据集
                print(f"Attempting to load {DATASET_NAME} with force_redownload...")
                ds = load_dataset(DATASET_NAME, download_mode="force_redownload")
                
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
                    target_sample_from_dataset = dict(found_item) # Create a mutable copy
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
                    final_target_sample = target_sample_from_dataset

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
        
        return final_target_sample

    def _build_file_class_methods(self, file_path):
        parser = self._parser_for_file(file_path)
        if parser is None:
            return

        # 检查文件扩展名
        if not any(file_path.endswith(ext) for ext in self.language_config.config['file_extensions']):
            return
            
        if 'test' in file_path and not file_path.endswith(self.language_config.config['test_file_pattern']):
            print(f"Skip processing test file: {file_path}")
            return
            
        if file_path in self.processed_files:
            print(f"File {file_path} already processed, skipping")
            return
            
        print(f"Processing file: {file_path}")
        self.processed_files.add(file_path)
        
        # 使用语言特定的解析器
        classes = parser.extract_classes(file_path)
        
        for class_info in classes:
            class_name = class_info['name'] if class_info['name'] else '__'
            
            # 创建类实体
            self.kg.create_class_entity(
                class_name,
                class_info['file_path'],
                class_info['start_line'],
                class_info['end_line'],
                class_info.get('source_code', ''),
                class_info.get('doc_string', ''),
                STRONG_CONNECTION
            )
            self.kg.link_class_to_file(class_name, class_info['file_path'], STRONG_CONNECTION)
            
            # 处理方法
            for method in class_info.get('methods', []):
                method_name = f"{method['name']}"
                
                self.kg.create_method_entity(
                    method_name,
                    method['signature'],
                    method['file_path'],
                    method['start_line'],
                    method['end_line'],
                    method['source_code'],
                    method.get('doc_string', ''),
                    STRONG_CONNECTION
                )
                
                self.kg.link_class_to_method(
                    class_name,
                    class_info['file_path'],
                    method_name,
                    method['signature'],
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
            if not file.filename.endswith('.py'):
                continue

            file_path = os.path.join(self.config['repo_path'], file.filename)
            
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
            if not os.path.exists(file_path_candidate):
                continue

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
                    self.kg.link_class_to_issue(class_info['name'], class_info['file_path'], issue_id, multipler * NORMAL_CONNECTION)
                    entity_linked_in_file = True
                for method_info in class_info.get('methods', []):
                    if method_info['name'] == target_name:
                        print(f"Matched method by target_name: {method_info['name']}")
                        self.kg.link_method_to_issue(method_info['name'], method_info['signature'], method_info['file_path'], issue_id, multipler * NORMAL_CONNECTION)
                        entity_linked_in_file = True
            
            for method_info in methods:
                if method_info['name'] == target_name:
                    print(f"Matched global method/variable by target_name: {method_info['name']}")
                    self.kg.link_method_to_issue(method_info['name'], method_info['signature'], method_info['file_path'], issue_id, multipler * NORMAL_CONNECTION)
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
                        self.kg.link_class_to_issue(class_info['name'], class_info['file_path'], issue_id, multipler * WEAK_CONNECTION)
                    for method_info in class_info.get('methods', []):
                        if method_info['name'] == target_name:
                            self.kg.link_method_to_issue(method_info['name'], method_info['signature'], method_info['file_path'], issue_id, multipler * WEAK_CONNECTION)
                for method_info in s_methods:
                    if method_info['name'] == target_name:
                        self.kg.link_method_to_issue(method_info['name'], method_info['signature'], method_info['file_path'], issue_id, multipler * WEAK_CONNECTION)

        if not found_specific_entity:
            # Use double quotes for the main f-string to allow single quotes inside for variable values
            print(f"Reference '{full_path}' (target: '{target_name}') could not be resolved to a specific file or entity after all attempts.")

    def _link_reference_to_issue_faster(self, issue_id, issue_content, multipler = 1):
        if issue_id in self.linked_issues or issue_content in self.linked_issue_contents:
            print(f"Issue/PR #{issue_id} already processed, skipping")
            return
        self.linked_issues.add(issue_id)
        self.linked_issue_contents.add(issue_content)
        print(f"Processing Issue/PR #{issue_id} references")
        ref_list = get_reference_functions_from_text(self.config['repo_path'], issue_content, self.parser, self.method_search_cache)
        print(ref_list)
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
        # Extract method information from stack trace
        stack_methods = extract_methods_from_traceback(self.repo.working_tree_dir, self.config['repo_root'], issue_content, self.kg, self.parser)
        for method_info in stack_methods:
            # method_info['file_path'] is now cleaned by the extractor
            full_path_for_check = os.path.join(self.config['repo_path'], os.path.normpath(method_info['file_path']))
            # A simpler way to reconstruct, assuming repo_path is like 'playground/repo_name'
            full_path_for_check_alt = os.path.join('playground', self._clean_path(method_info['file_path']))

            print(f"Found method from stack trace: {method_info}")

            # Reconstruct the full path to check for existence
            # This is necessary because method_info['file_path'] is now the cleaned, relative path.
            # self.repo_path is 'playground/<repo_name>/'
            full_path_for_check = os.path.join(self.config['repo_path'], os.path.normpath(method_info['file_path']))

            # A simpler way might be to join 'playground' with the cleaned path if the structure is fixed
            # For now, let's trust that the parser gives a path relative to repo root (without repo name)
            # And self.repo_path is the full path to the checkout dir.
            
            # The previous logic in `_clean_path` makes it relative to cwd.
            # A better way to reconstruct:
            # The cleaned path is relative to 'playground'. So we join 'playground' and the cleaned path.
            reconstructed_path = os.path.join('playground', method_info['file_path'])

            if os.path.exists(reconstructed_path):
                # Create method entity
                self.kg.create_method_entity(
                    method_info['name'],
                    method_info.get('signature', ''),
                    method_info['file_path'],
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
                    method_info['file_path'],
                    issue_id,
                    STRONG_CONNECTION
                )

    def _link_source_files_to_issue(self, issue_id: str, issue_content: str):
        """Links source files mentioned in the issue content to the issue node."""
        if not issue_content:
            return

        # Correctly initialize TextAnalyzer and use its extract_matches method
        text_analyzer = TextAnalyzer(self.github_token) 
        # Assuming extract_matches takes the text and repo_name (or repo_path if more appropriate)
        # And that its return format is suitable for source_files
        source_files = text_analyzer.extract_matches(issue_content, self.config['repo_name']) 
        
        # Fallback for Python-specific extraction if no generic links found and main language is Python
        # This part needs generalization for other languages or better generic link extraction
        if not source_files and self.config.get('language') == 'python':
            python_specific_files = get_python_files_from_content(issue_content, self.repo_path, self.config['repo_name'])
            if not isinstance(source_files, list):
                print(f"Warning: source_files was a {type(source_files)} before python_specific_files. Resetting to list.")
                source_files = [] # Reset to list if it was, for example, an empty dict
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


        linked_files_count = 0
        # Ensure source_files is iterable (list) before the loop
        if not isinstance(source_files, list):
            print(f"Warning: source_files is {type(source_files)} before final loop. Attempting to use keys if dict, else treating as empty.")
            if isinstance(source_files, dict):
                # Assuming keys of the dict are the file paths if it's a dict
                # This is a guess; actual structure of dict from extract_matches matters
                source_files = list(source_files.keys()) 
            else:
                source_files = [] # Treat as empty if not list or dict

        for file_path_ref in source_files:
            if any(file_path_ref.endswith(ext) for ext in current_lang_extensions):
                if os.path.exists(file_path_ref):
                    clean_file_path = self._clean_path(file_path_ref)
                    print(f"Found file reference in Issue #{issue_id}: {clean_file_path}")
                    # Create file entity and establish association
                    self.kg.create_file_entity(clean_file_path)
                    self.kg.link_issue_to_file(issue_id, clean_file_path)
                    self._build_file_class_methods(file_path_ref) # This uses self.parser
                    linked_files_count += 1

        print(f"Found source file references in Issue #{issue_id} (filtered by current language): {linked_files_count}")

    def _get_issue_from_id(self, repo_name, issue_id):
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
        body = issue.body or ""
        
        # Get all comments, but only include comments before current task
        comments = []
        for comment in issue.get_comments():
            if comment.created_at.timestamp() > self.created_at:
                print(f"Skip comment created at {comment.created_at}, later than current task")
                # Call helper even if we print skip, to ensure it's counted if not already
                self._check_and_count_artifact_time(comment.created_at.timestamp(), f"gh_comment_{comment.id}")
                continue
            # If not skipped by time, it's a candidate for a valid comment
            if self._check_and_count_artifact_time(comment.created_at.timestamp(), f"gh_comment_{comment.id}"):
                comments.append(f"\nComment by {comment.user.login}:\n{comment.body}")
        
        # Merge original content and comments
        issue.full_body = body + "\n\n" + "\n".join(comments)
        
        print(f"Found issue/PR #{issue_id} with {len(comments)} valid comments before {datetime.fromtimestamp(self.created_at, timezone.utc)}")
        # Save to cache
        self.issue_cache[cache_key] = issue
        return issue

    def _get_issues(self, repo_name, issue_id=None, title=None, time_range=None):
        if repo_name == 'django/django':
            print('Django Issues / PRs')
            if issue_id is not None:
                print('issue_id is not None', issue_id)
                try:
                    issue = self._get_issue_from_id(repo_name, issue_id)
                    print('Found issue/PR', issue.number)
                    return issue
                except Exception as e:
                    print(f"GitHub lookup failed: {e}")
                    # If not found on GitHub, try Django Trac
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                    print('Issue id is', issue_id)
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                    url = f"https://code.djangoproject.com/ticket/{issue_id}"
                    response = requests.get(url, headers=headers)
                    print('response of django ticket', url, response.status_code)
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, 'html.parser')
                        
                        # Get title
                        title_element = soup.find('h1', {'class': 'title'})
                        title = title_element.text.strip() if title_element else f"Django Ticket #{issue_id}"
                        
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
                        # Get comments
                        comments = []
                        comment_elements = soup.find_all('div', {'class': 'change'})
                        for comment in comment_elements:
                            # Get comment time
                            time_element = comment.find('a', {'class': 'timeline'})
                            if time_element:
                                href = time_element.get('href', '')
                                time_param = re.search(r'from=(.*?)(?:&|$)', href)
                                if time_param:
                                    time_str = time_param.group(1).replace('%3A', ':')
                                    try:
                                        # Process time zone information
                                        if '-' in time_str[10:]:
                                            dt_str, tz_str = time_str.rsplit('-', 1)
                                            dt = datetime.strptime(dt_str, '%Y-%m-%dT%H:%M:%S')
                                            # Convert to UTC
                                            offset = timedelta(hours=int(tz_str.split(':')[0]), 
                                                            minutes=int(tz_str.split(':')[1]))
                                            comment_time = (dt + offset)
                                        else:
                                            comment_time = datetime.strptime(time_str, '%Y-%m-%dT%H:%M:%S')
                                        
                                        # Check and count comment time validity
                                        # Construct a unique ID for Django comments, e.g., using an index
                                        comment_unique_id = f"django_comment_{issue_id}_{len(comments)}"
                                        if self._check_and_count_artifact_time(comment_time.timestamp(), comment_unique_id):
                                            comment_text = html2text.html2text(str(comment))
                                            comments.append(comment_text)
                                        # Else, it's skipped and counted by the helper
                                    except ValueError as e:
                                        print(f"Failed to parse comment time: {e}")
                            else:
                                print("Comment has no time information")
                        # Merge description and comments
                        full_content = content + "\n\n" + "\n\n".join(comments)
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
                        
                        return DjangoTicket(
                            int(issue_id),
                            title,
                            author,
                            content,
                            full_content,
                            issue_time
                        )
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
        matching_issues = self.github.search_issues(search_query)
        return matching_issues

    def _search_method_by_name(self, repo_root, method_name):
        cache_key = f"{repo_root}:{method_name}"
        if cache_key in self.method_search_cache:
            print(f"Retrieved method {method_name} search results from cache")
            return self.method_search_cache[cache_key]

        matching_files = []
        print(f"Searching methods or global variables {method_name} in repository {repo_root}")

        # Get all supported extensions from the language factory
        all_supported_extensions = list(EXT_LANG_MAP.keys())

        cnt = 0
        # Iterate through all files in the repository
        for root, dirs, files in os.walk(repo_root):
            # Skip .git directory and other common non-code directories if needed
            dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', 'node_modules', 'build', 'dist']]
            for file_name in files:
                # Check if the file extension is one of the supported ones
                if not any(file_name.endswith(ext) for ext in all_supported_extensions):
                    continue

                file_path = os.path.join(root, file_name)
                
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
        self.method_search_cache[cache_key] = matching_files
        return matching_files

    def _process_repository(self, target_sample):
        """Process code repository"""
        # Before processing problem description, first parse and add patch content
        problem_statement = self.patch_link_expander._expand_patch_links(target_sample['problem_statement'])
        
        # Update target_sample content
        target_sample['problem_statement'] = problem_statement
        
        # Switch to specified commit
        print(f"Switching to commit: {target_sample['base_commit']}")
        self._checkout_commit(target_sample['base_commit'])
        # Convert creation time to UTC timestamp
        self.created_at = (
            datetime.strptime(target_sample['created_at'], "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=timezone.utc)
        ).timestamp()

        # 0. Create directory structure
        print('======> Step 0. Creating directory structure')
        self.kg.create_directory_structure(self.config['repo_path'], self, False, STRONG_CONNECTION)

        # 1. Create root node, containing problem description and hint information
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
        
        # Extract file references and methods from root node content
        if root_content:
            # Extract reference information
            self._link_source_files_to_issue(root_id, root_content)
            self._link_stacktrace_to_issue(root_id, root_content)
            self._link_reference_to_issue_faster(root_id, root_content, 1)

        # 2. Extract related issues from problem description and hint
        text = root_content
        issue_ids = set(re.findall(r'#(\d+)', text))
        # Try to find matching issue/PR on GitHub
        print(f"======> Step 2. Extract related issues from problem description and hint\nSearch repository: {self.config['repo_name']}")
        # Use GitHub search API directly to find matching issue
        max_similarity = 0
        best_match_issue = None
        end_time = self.created_at + 8 * 60 * 60
        start_time = end_time - (7 * 24 * 60 * 60)  # Number of seconds in 7 days
        time_range = (start_time, end_time)
        
        if self.config['repo_name'] == 'django/django':
            import pandas as pd
            df = pd.read_csv('django-tickets.csv')
            best_id = None
            for _, row in df.iterrows():
                title_clean = title.lower().replace('.', '').replace(' ', '')
                issue_title_clean = row['Summary'].lower().replace('.', '').replace(' ', '')
                same_length = pylcs.lcs(title_clean, issue_title_clean)
                similarity = same_length / max(len(title_clean), len(issue_title_clean))
                # Update best match
                if similarity > max_similarity:
                    # Potential best match, fetch to check time
                    potential_issue = self._get_issues('django/django', issue_id=row['id'])
                    if potential_issue: # _get_issues for Django already does time check and counting
                        max_similarity = similarity
                        best_id = row['id'] # Keep track of ID
                        best_match_issue = potential_issue # Store the already time-checked issue
                    # If potential_issue is None, it was time-skipped by _get_issues
            # best_match_issue is now either a valid one or None
            if best_id and not best_match_issue: # if we had a best_id but it resolved to None (time skipped)
                 pass # Already handled by _get_issues's call to _check_and_count_artifact_time
            elif best_match_issue: # If it's a valid issue
                 pass # Already handled by _get_issues
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
                content = issue.full_body or ""
                self._link_source_files_to_issue(issue_id, content)
                self._link_stacktrace_to_issue(issue_id, content)
            except Exception as e:
                print(f"Error processing issue #{issue_id} content: {e}")
        # 6. Process method call relationships
        print("======> Step 6. Starting scanning project to find related methods")
        self._scan_project_for_related_methods(self.kg.get_all_methods(self.MAX_CANDIDATE_METHODS))
        print('======> Completed')

    def _scan_project_for_related_methods(self, all_methods):
        """Scan project to find methods with call relationships to existing methods"""
        print("Starting scanning project to find related methods...")
        
        # Use all supported extensions from EXT_LANG_MAP
        all_supported_extensions = list(EXT_LANG_MAP.keys())
        source_files = get_source_files_by_extensions(self.config['repo_path'], all_supported_extensions)
        total_files = len(source_files)
        
        for idx, file_path in enumerate(source_files, 1):
            parser = self._parser_for_file(file_path)
            if parser is None:
                # print(f"Skipping file {file_path} in _scan_project_for_related_methods, no parser.")
                continue # Skip unsupported file types

            print(f"\nScanning for method calls in [{idx}/{total_files}]: {file_path}")
            
            # Example of skipping specific paths - make this more configurable if needed
            # if '/rubi/rules/' in file_path: 
            #     continue
            try:
                imports = parser.get_imports(file_path)
                local_methods = []
                global_methods = parser.get_global_methods(file_path, self.config['repo_root'])
                local_methods.extend(global_methods)
                
                classes = parser.extract_classes(file_path)
                for class_info in classes:
                    for method in class_info.get('methods', []):
                        local_methods.append(method)
                
                for local_method_info in local_methods:
                    # The analyze_method_calls_in_method is part of the parser interface
                    # and should be implemented by each language-specific parser.
                    parser.analyze_method_calls_in_method(
                        local_method_info,
                        all_methods, 
                        self.kg,
                        imports,
                        self.config['repo_root'] # repo_root might be specific to Python's module naming
                    )
            except Exception as e:
                print(f"Error processing file {file_path} for method calls: {str(e)}")
                # import traceback
                # print(traceback.format_exc())
                continue

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
        
        # Process timeline associations
        try:
            timeline = issue.get_timeline()
            for event in timeline:
                if event.event == "cross-referenced" and hasattr(event.source, 'issue'):
                    timeline_issue = event.source.issue
                    timeline_issue_id = str(timeline_issue.number)
                    
                    # Check creation time and count
                    # Ensure timeline_issue.created_at exists before trying to access its timestamp
                    if not hasattr(timeline_issue, 'created_at') or not timeline_issue.created_at:
                        print(f"Timeline event for issue #{issue_id} references issue #{timeline_issue_id} but it lacks created_at. Skipping.")
                        continue

                    timeline_issue_unique_id = f"gh_{timeline_issue_id}" # Assuming timeline issues are GitHub issues
                    if not self._check_and_count_artifact_time(timeline_issue.created_at.timestamp(), timeline_issue_unique_id):
                        print(f"Timeline Issue #{timeline_issue_id} created at {timeline_issue.created_at} later than current repair task, skipping.")
                        continue
                        
                    # Avoid duplicate processing
                    if timeline_issue_id in extended_issue_ids:
                        continue
                        
                    # Add to extended set
                    extended_issue_ids.add(timeline_issue_id)
                    
                    # Create referenced issue entity - Use _get_issue_from_id instead of directly using timeline_issue
                    processed_issue = self._get_issue_from_id(self.config['repo_name'], int(timeline_issue_id))
                    if processed_issue:
                        self.kg.create_issue_entity_by_github_issue(processed_issue)
                        
                        # Establish association relationship
                        self.kg.link_issues(str(issue_id), timeline_issue_id, STRONG_CONNECTION)
                        print(f"Established issue timeline cross-reference relationship: #{issue_id} -[RELATED]-> #{timeline_issue_id}")
                        
        except Exception as e:
            print(f"Error processing #{issue_id} timeline: {e}")
                
        print(f"Successfully processed {'PR' if is_pr else 'Issue'} #{issue_id}: {title} ")
        return extended_issue_ids

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
    if benchmark_name_arg == 'multi-swe-bench':
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

    config = {
        'repo_path': f'playground/{repo_path_arg}/',
        'repo_name': repo_name, 
        'repo_root': repo_name.split('/')[-1],
        'instance_id': instance_id_arg,
        'benchmark_name': benchmark_name_arg,
        'language': 'java' if benchmark_name_arg == 'multi-swe-bench' else 'python'
    }

    print(f"Configuration: {config}")

    analyzer = CodeAnalyzer(config)
    result = analyzer.analyze()

    if result is None:
        # _get_target_sample() 已经打印了 "No sample found..."
        # _cleanup() 已经在 analyze() 方法的 finally 中被调用
        print(f"Analysis returned no result for {instance_id_arg}. Exiting with error status.")
        sys.exit(1) # 以非零状态码退出
    
    output_file_path = os.path.join(fl_location_dir_arg, f"{instance_id_arg}.json")
    with open(output_file_path, 'w') as f:
        json.dump(result, f, indent=4)
    print(f"Results saved to: {output_file_path}")
    
    end_time = datetime.now()
    print(f"Completed execution time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    duration = end_time - start_time
    print(f"Total execution duration: {duration}")
