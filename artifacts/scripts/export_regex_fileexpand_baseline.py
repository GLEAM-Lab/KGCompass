#!/usr/bin/env python3
"""Export a strict regex/symbol file-expansion localization baseline.

This baseline is intentionally simple and independent of KGCompass outputs:
it reads each SWE-bench Verified issue, extracts file/module/symbol anchors
with regular expressions, finds matching files in the base-commit repository
with git commands, expands the selected files to Python methods/classes, and
emits Top-K candidates in the same JSON schema used by the localization metric
scripts.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pyarrow.ipc as pa_ipc


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IDS_FILE = REPO_ROOT / "SWE-bench_Verified_ids.jsonl"
DEFAULT_REPOS_DIR = REPO_ROOT / "playground_text_baselines"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runs/regex_fileexpand_strict/tse_timesafe_main_20260531_v1"
DEFAULT_TOP_K = 50

STOPWORDS = {
    "about", "after", "again", "also", "because", "before", "between", "cannot",
    "class", "could", "does", "during", "error", "expected", "false", "file",
    "from", "function", "have", "into", "issue", "method", "module", "none",
    "only", "problem", "return", "should", "that", "their", "there", "these",
    "this", "true", "when", "where", "while", "with", "would",
}


@dataclass
class Candidate:
    name: str
    signature: str
    file_path: str
    source_code: str
    doc_string: str
    start_line: int
    end_line: int | None

    def to_json(self, score: float, evidence: dict) -> dict:
        return {
            "type": "method",
            "name": self.name,
            "signature": self.signature,
            "file_path": self.file_path,
            "documentation": self.doc_string,
            "source_code": self.source_code,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "issue_id": None,
            "title": None,
            "content": None,
            "distance": None,
            "path": [],
            "similarity": float(score),
            "evidence": evidence,
        }


def run_git(repo: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        errors="replace",
        capture_output=True,
        check=check,
    )


def discover_verified_arrow() -> Path:
    root = Path.home() / ".cache/huggingface/datasets/princeton-nlp___swe-bench_verified/default/0.0.0"
    candidates = sorted(root.glob("*/swe-bench_verified-test.arrow"), key=os.path.getmtime)
    if not candidates:
        raise FileNotFoundError("Cannot locate cached SWE-bench Verified arrow")
    return candidates[-1]


def load_instances(path: Path) -> list[dict]:
    with pa_ipc.open_stream(str(path)) as reader:
        return reader.read_all().to_pylist()


def load_ids(path: Path) -> list[str]:
    ids: list[str] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                ids.append(json.loads(line)["instance_id"])
            else:
                ids.append(line)
    return ids


def repo_dir_for_instance(repos_dir: Path, instance_id: str) -> Path:
    repo_id = instance_id.rsplit("-", 1)[0]
    repo_dir = repos_dir / repo_id
    if not repo_dir.is_dir():
        raise FileNotFoundError(f"Missing local repo: {repo_dir}")
    return repo_dir


def split_identifier(value: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value or "")
    raw = re.split(r"[^A-Za-z0-9]+", spaced)
    return [
        token.lower()
        for token in raw
        if len(token) >= 3 and token.lower() not in STOPWORDS
    ]


def strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", " ", text or "", flags=re.DOTALL)


def extract_anchors(issue_text: str) -> dict:
    text = strip_html_comments(issue_text)
    code_spans = re.findall(r"`([^`]+)`", text)
    code_text = "\n".join(code_spans)
    combined = f"{code_text}\n{text}"

    file_paths = {
        m.group(0).strip("./")
        for m in re.finditer(r"(?<![A-Za-z0-9_./-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.py(?![A-Za-z0-9_./-])", combined)
    }
    dotted = {
        token
        for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b", combined)
        if len(token) >= 5
    }
    identifiers = set()
    for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", combined):
        if token.lower() in STOPWORDS or len(token) < 3:
            continue
        if "_" in token or re.search(r"[a-z][A-Z]", token) or token.isupper():
            identifiers.add(token)
    lexical = set(split_identifier(text))
    code_tokens = set(split_identifier(code_text))
    return {
        "file_paths": sorted(file_paths),
        "dotted": sorted(dotted),
        "identifiers": sorted(identifiers),
        "lexical": sorted(lexical),
        "code_tokens": sorted(code_tokens),
    }


def list_python_files(repo: Path, commit: str) -> list[str]:
    proc = run_git(repo, ["ls-tree", "-r", "--name-only", commit], check=True)
    out = []
    for line in proc.stdout.splitlines():
        if not line.endswith(".py"):
            continue
        norm = line.strip().replace("\\", "/")
        if not norm:
            continue
        out.append(norm)
    return out


def dotted_to_candidate_files(dotted: Iterable[str]) -> set[str]:
    out = set()
    for symbol in dotted:
        parts = symbol.split(".")
        for cut in range(len(parts), 0, -1):
            out.add("/".join(parts[:cut]) + ".py")
            out.add("/".join(parts[:cut]) + "/__init__.py")
    return out


def git_grep_files(repo: Path, commit: str, anchors: list[str], max_anchors: int) -> Counter:
    selected = []
    seen = set()
    for anchor in anchors:
        if anchor in seen or len(anchor) < 3:
            continue
        seen.add(anchor)
        selected.append(anchor)
        if len(selected) >= max_anchors:
            break
    if not selected:
        return Counter()
    # File-level matching is enough for this strict ablation and avoids
    # producing huge line-level grep outputs for common issue tokens.
    cmd = ["grep", "-I", "-l", "-F"]
    for anchor in selected:
        cmd.extend(["-e", anchor])
    cmd.extend([commit, "--", "*.py"])
    proc = run_git(repo, cmd, check=False)
    counts: Counter = Counter()
    if proc.returncode not in (0, 1):
        return counts
    prefix = f"{commit}:"
    for line in proc.stdout.splitlines():
        if not line.startswith(prefix):
            continue
        rest = line[len(prefix):]
        path = rest.split(":", 1)[0].replace("\\", "/")
        if path.endswith(".py"):
            counts[path] += 1
    return counts


def read_file_at_commit(repo: Path, commit: str, file_path: str) -> str | None:
    proc = run_git(repo, ["show", f"{commit}:{file_path}"], check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout


def source_segment(source: str, node: ast.AST) -> str:
    try:
        return ast.get_source_segment(source, node) or ""
    except Exception:
        return ""


def extract_candidates_from_source(source: str, rel_path: str) -> list[Candidate]:
    try:
        tree = ast.parse(source)
    except Exception:
        return []
    module_path = rel_path.replace("/", ".").removesuffix(".py")
    out: list[Candidate] = []

    def add_function(node: ast.AST, prefix: str) -> None:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return
        params = ", ".join(arg.arg for arg in node.args.args)
        full_name = f"{prefix}.{node.name}" if prefix else f"{module_path}.{node.name}"
        out.append(
            Candidate(
                name=full_name,
                signature=f"{full_name}({params})",
                file_path=rel_path,
                source_code=source_segment(source, node),
                doc_string=ast.get_docstring(node) or "",
                start_line=int(getattr(node, "lineno", 0) or 0),
                end_line=getattr(node, "end_lineno", None),
            )
        )

    def add_assign(node: ast.Assign, prefix: str) -> None:
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            full_name = f"{prefix}.{target.id}" if prefix else f"{module_path}.{target.id}"
            out.append(
                Candidate(
                    name=full_name,
                    signature=f"{full_name} = {source_segment(source, node.value)[:80]}",
                    file_path=rel_path,
                    source_code=source_segment(source, node),
                    doc_string="",
                    start_line=int(getattr(node, "lineno", 0) or 0),
                    end_line=getattr(node, "end_lineno", None),
                )
            )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add_function(node, "")
        elif isinstance(node, ast.Assign):
            add_assign(node, "")
        elif isinstance(node, ast.ClassDef):
            class_name = f"{module_path}.{node.name}"
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add_function(item, class_name)
                elif isinstance(item, ast.Assign):
                    add_assign(item, class_name)
    return [c for c in out if not ("test" in c.name.lower() and "pytest" not in c.name.lower())]


def file_token_score(file_path: str, issue_terms: set[str]) -> int:
    return len(set(split_identifier(file_path)).intersection(issue_terms))


def candidate_symbol_score(candidate: Candidate, anchors: dict) -> tuple[int, list[str]]:
    fields = f"{candidate.name}\n{candidate.signature}\n{candidate.file_path}".lower()
    exact_matches = []
    for symbol in anchors["dotted"]:
        s = symbol.lower()
        if s and s in fields:
            exact_matches.append(symbol)
    for ident in anchors["identifiers"]:
        i = ident.lower()
        if re.search(rf"(?<![a-z0-9_]){re.escape(i)}(?![a-z0-9_])", fields):
            exact_matches.append(ident)
    method_terms = set(split_identifier(candidate.name + " " + candidate.signature))
    token_matches = method_terms.intersection(set(anchors["lexical"]) | set(anchors["code_tokens"]))
    return 25 * len(set(exact_matches)) + 3 * len(token_matches), sorted(set(exact_matches) | token_matches)


def rank_instance(item: dict, repo: Path, args: argparse.Namespace) -> tuple[list[dict], dict]:
    commit = item["base_commit"]
    issue_text = item.get("problem_statement") or ""
    anchors = extract_anchors(issue_text)
    repo_files = set(list_python_files(repo, commit))

    file_scores: Counter = Counter()
    score_reasons: dict[str, list[str]] = defaultdict(list)

    for path in anchors["file_paths"]:
        suffix_hits = [f for f in repo_files if f == path or f.endswith("/" + path)]
        for hit in suffix_hits:
            file_scores[hit] += 1000
            score_reasons[hit].append(f"explicit_path:{path}")

    for path in dotted_to_candidate_files(anchors["dotted"]):
        if path in repo_files:
            file_scores[path] += 800
            score_reasons[path].append("dotted_module")

    grep_anchors = anchors["dotted"] + anchors["identifiers"]
    grep_counts = git_grep_files(repo, commit, grep_anchors, args.max_grep_anchors)
    for path, count in grep_counts.items():
        if path in repo_files:
            file_scores[path] += min(count, 20) * 15
            score_reasons[path].append(f"git_grep:{min(count, 20)}")

    issue_terms = set(anchors["lexical"]) | set(anchors["code_tokens"])
    for path in repo_files:
        overlap = file_token_score(path, issue_terms)
        if overlap:
            file_scores[path] += overlap * 4
            score_reasons[path].append(f"path_tokens:{overlap}")

    top_files = [
        path
        for path, score in file_scores.most_common(args.max_files)
        if score > 0
    ]
    methods = []
    for path in top_files:
        source = read_file_at_commit(repo, commit, path)
        if source is None:
            continue
        for cand in extract_candidates_from_source(source, path):
            sym_score, matches = candidate_symbol_score(cand, anchors)
            score = file_scores[path] * 1000 + sym_score * 10 - (cand.start_line or 0) / 100000.0
            evidence = {
                "file_score": int(file_scores[path]),
                "file_reasons": score_reasons.get(path, []),
                "symbol_matches": matches,
                "baseline": "regex_fileexpand_strict",
            }
            methods.append(cand.to_json(score, evidence))

    methods.sort(key=lambda x: x.get("similarity", 0.0), reverse=True)
    deduped = []
    seen = set()
    for method in methods:
        sig = method.get("signature")
        if not sig or sig in seen:
            continue
        seen.add(sig)
        deduped.append(method)
        if len(deduped) >= args.top_k:
            break
    stats = {
        "candidate_files": len(top_files),
        "candidate_methods": len(methods),
        "anchors": {k: len(v) for k, v in anchors.items()},
    }
    return deduped, stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids-file", type=Path, default=DEFAULT_IDS_FILE)
    parser.add_argument("--repos-dir", type=Path, default=DEFAULT_REPOS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dataset-arrow", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--max-files", type=int, default=80)
    parser.add_argument("--max-grep-anchors", type=int, default=40)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def export_one(item: dict, args: argparse.Namespace) -> tuple[str, str, int, int]:
    iid = item["instance_id"]
    out_file = args.output_dir / f"{iid}.json"
    if out_file.exists() and not args.force:
        return "skip", iid, -1, -1
    repo = repo_dir_for_instance(args.repos_dir, iid)
    methods, stats = rank_instance(item, repo, args)
    payload = {
        "related_entities": {"methods": methods, "classes": [], "issues": []},
        "artifact_stats": stats,
        "kg_params": {
            "baseline": "regex_fileexpand_strict",
            "uses_kg": False,
            "uses_llm": False,
            "uses_hints": False,
            "uses_comments": False,
            "candidate_source": "base_commit_git_regex_and_file_expansion",
        },
        "run_meta": {
            "instance_id": iid,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "base_commit": item.get("base_commit"),
            "repo": item.get("repo"),
        },
    }
    out_file.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return "done", iid, len(methods), int(stats["candidate_files"])


def main() -> None:
    args = parse_args()
    ids = load_ids(args.ids_file)
    id_set = set(ids)
    arrow = args.dataset_arrow or discover_verified_arrow()
    by_id = {item["instance_id"]: item for item in load_instances(arrow) if item.get("instance_id") in id_set}
    selected = [by_id[iid] for iid in ids if iid in by_id]
    if args.limit is not None:
        selected = selected[: args.limit]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Using dataset arrow: {arrow}", flush=True)
    print(f"Total instances: {len(selected)}", flush=True)
    if args.workers <= 1:
        for idx, item in enumerate(selected, start=1):
            status, iid, method_count, file_count = export_one(item, args)
            if idx % 25 == 0 or idx == len(selected):
                print(f"[{status}] {idx}/{len(selected)} {iid} methods={method_count} files={file_count}", flush=True)
        return

    completed = 0
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(export_one, item, args) for item in selected]
        for future in as_completed(futures):
            completed += 1
            status, iid, method_count, file_count = future.result()
            if completed % 25 == 0 or completed == len(selected):
                print(f"[{status}] {completed}/{len(selected)} {iid} methods={method_count} files={file_count}", flush=True)


if __name__ == "__main__":
    main()
