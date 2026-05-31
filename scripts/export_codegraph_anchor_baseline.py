#!/usr/bin/env python3
"""Export the no-history issue-anchored code-graph localization baseline.

This baseline is KG-free and LLM-free. It uses only the original issue text
and the base-commit repository snapshot. The baseline first extracts explicit
anchors from the issue, maps them to seed files and symbols, then follows
base-code containment/import/reference evidence before ranking AST-level
methods with the same JSON schema as the KGCompass localization evaluators.
It intentionally disables all historical issue/PR artifacts, comments, hints,
and target patch content.

The constants below are fixed priority scales for this defensive control.
They were not tuned on SWE-bench Verified; the ordering encodes a conservative
preference for explicit issue anchors, then base-code definition/reference
evidence, then broad lexical file evidence.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from export_regex_fileexpand_baseline import (
    DEFAULT_IDS_FILE,
    DEFAULT_REPOS_DIR,
    DEFAULT_TOP_K,
    Candidate,
    candidate_symbol_score,
    discover_verified_arrow,
    dotted_to_candidate_files,
    extract_anchors,
    extract_candidates_from_source,
    file_token_score,
    git_grep_files,
    list_python_files,
    load_ids,
    load_instances,
    read_file_at_commit,
    repo_dir_for_instance,
    run_git,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runs/codegraph_anchor/tse_timesafe_main_20260531_v1"
EXPLICIT_PATH_FILE_SCORE = 1000
DOTTED_MODULE_FILE_SCORE = 800
DEFINITION_FILE_SCORE = 120
GIT_GREP_FILE_SCORE = 15
PATH_TOKEN_FILE_SCORE = 4
IMPORT_NEIGHBOR_DECAY = 0.55
DISTANCE_SCORE = 1_000_000.0
FILE_SCORE_SCALE = 100.0
SYMBOL_SCORE = 1000.0


def module_name_for_path(path: str) -> str:
    module = path.replace("/", ".").removesuffix(".py")
    if module.endswith(".__init__"):
        module = module.removesuffix(".__init__")
    return module


def module_to_files(repo_files: set[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for path in repo_files:
        out[module_name_for_path(path)].add(path)
    return out


def resolve_module(module: str, mod_index: dict[str, set[str]]) -> set[str]:
    if not module:
        return set()
    parts = module.split(".")
    hits: set[str] = set()
    for cut in range(len(parts), 0, -1):
        prefix = ".".join(parts[:cut])
        hits.update(mod_index.get(prefix, set()))
        if hits:
            break
    return hits


def resolve_relative_import(current_path: str, level: int, module: str | None) -> str:
    current_module = module_name_for_path(current_path)
    parts = current_module.split(".")
    if not current_path.endswith("__init__.py") and parts:
        parts = parts[:-1]
    if level > 0:
        parts = parts[: max(0, len(parts) - (level - 1))]
    if module:
        parts.extend(module.split("."))
    return ".".join(p for p in parts if p)


def import_neighbor_files(source: str, current_path: str, mod_index: dict[str, set[str]]) -> dict[str, list[str]]:
    try:
        tree = ast.parse(source)
    except Exception:
        return {}

    hits: dict[str, list[str]] = defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for path in resolve_module(alias.name, mod_index):
                    hits[path].append(f"import:{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            base = resolve_relative_import(current_path, int(node.level or 0), node.module)
            for path in resolve_module(base, mod_index):
                hits[path].append(f"from:{base}")
            for alias in node.names:
                if alias.name == "*":
                    continue
                child = f"{base}.{alias.name}" if base else alias.name
                for path in resolve_module(child, mod_index):
                    hits[path].append(f"from:{child}")
    hits.pop(current_path, None)
    return hits


def definition_anchor_files(repo: Path, commit: str, anchors: dict, repo_files: set[str]) -> Counter:
    names: list[str] = []
    seen: set[str] = set()
    for dotted in anchors["dotted"]:
        for part in dotted.split("."):
            if len(part) >= 3 and part not in seen:
                names.append(part)
                seen.add(part)
    for ident in anchors["identifiers"]:
        if ident not in seen:
            names.append(ident)
            seen.add(ident)

    patterns: list[str] = []
    for name in names[:50]:
        patterns.extend([f"def {name}", f"async def {name}", f"class {name}"])
    counts: Counter = Counter()
    if not patterns:
        return counts
    # We only need candidate files, not every matching line. `-l` keeps large
    # projects such as SymPy from producing massive grep output for common
    # issue anchors.
    cmd = ["grep", "-I", "-l", "-F"]
    for pattern in patterns:
        cmd.extend(["-e", pattern])
    cmd.extend([commit, "--", "*.py"])
    proc = run_git(repo, cmd, check=False)
    if proc.returncode not in (0, 1):
        return counts
    prefix = f"{commit}:"
    for line in proc.stdout.splitlines():
        if not line.startswith(prefix):
            continue
        rest = line[len(prefix):]
        path = rest.strip().replace("\\", "/")
        if path in repo_files:
            counts[path] += 1
    return counts


def compute_seed_file_scores(item: dict, repo: Path, repo_files: set[str], anchors: dict, max_grep_anchors: int) -> tuple[Counter, dict[str, list[str]]]:
    commit = item["base_commit"]
    file_scores: Counter = Counter()
    reasons: dict[str, list[str]] = defaultdict(list)

    for path in anchors["file_paths"]:
        for hit in [f for f in repo_files if f == path or f.endswith("/" + path)]:
            file_scores[hit] += EXPLICIT_PATH_FILE_SCORE
            reasons[hit].append(f"explicit_path:{path}")

    for path in dotted_to_candidate_files(anchors["dotted"]):
        if path in repo_files:
            file_scores[path] += DOTTED_MODULE_FILE_SCORE
            reasons[path].append("dotted_module")

    grep_counts = git_grep_files(repo, commit, anchors["dotted"] + anchors["identifiers"], max_grep_anchors)
    for path, count in grep_counts.items():
        if path in repo_files:
            file_scores[path] += min(count, 20) * GIT_GREP_FILE_SCORE
            reasons[path].append(f"git_grep:{min(count, 20)}")

    definition_counts = definition_anchor_files(repo, commit, anchors, repo_files)
    for path, count in definition_counts.items():
        file_scores[path] += min(count, 10) * DEFINITION_FILE_SCORE
        reasons[path].append(f"code_definition:{min(count, 10)}")

    issue_terms = set(anchors["lexical"]) | set(anchors["code_tokens"])
    for path in repo_files:
        overlap = file_token_score(path, issue_terms)
        if overlap:
            file_scores[path] += overlap * PATH_TOKEN_FILE_SCORE
            reasons[path].append(f"path_tokens:{overlap}")
    return file_scores, reasons


def rank_instance(item: dict, repo: Path, args: argparse.Namespace) -> tuple[list[dict], dict]:
    commit = item["base_commit"]
    issue_text = item.get("problem_statement") or ""
    anchors = extract_anchors(issue_text)
    repo_files = set(list_python_files(repo, commit))
    mod_index = module_to_files(repo_files)
    seed_scores, reasons = compute_seed_file_scores(item, repo, repo_files, anchors, args.max_grep_anchors)

    graph_files: dict[str, dict] = {}
    for rank, (path, score) in enumerate(seed_scores.most_common(args.max_seed_files), start=1):
        if score <= 0:
            continue
        graph_files[path] = {
            "distance": 0,
            "score": int(score),
            "rank": rank,
            "reasons": list(reasons.get(path, [])),
        }

    for seed_path, seed_meta in list(graph_files.items()):
        source = read_file_at_commit(repo, commit, seed_path)
        if source is None:
            continue
        for neighbor, edge_reasons in import_neighbor_files(source, seed_path, mod_index).items():
            if neighbor not in repo_files:
                continue
            meta = graph_files.get(neighbor)
            neighbor_score = max(1, int(seed_meta["score"] * IMPORT_NEIGHBOR_DECAY))
            if meta is None or (meta["distance"], -meta["score"]) > (1, -neighbor_score):
                graph_files[neighbor] = {
                    "distance": 1,
                    "score": neighbor_score,
                    "rank": int(seed_meta["rank"]),
                    "reasons": [f"{seed_path}->{r}" for r in sorted(set(edge_reasons))[:3]],
                }

    methods: list[dict] = []
    for path, meta in graph_files.items():
        source = read_file_at_commit(repo, commit, path)
        if source is None:
            continue
        distance = int(meta["distance"])
        file_score = float(meta["score"])
        for cand in extract_candidates_from_source(source, path):
            sym_score, matches = candidate_symbol_score(cand, anchors)
            score = (
                (DISTANCE_SCORE / (distance + 1))
                + file_score * FILE_SCORE_SCALE
                + sym_score * SYMBOL_SCORE
                - float(cand.start_line or 0) / 100_000.0
            )
            evidence = {
                "baseline": "no_history_codegraph",
                "distance": distance,
                "file_score": int(file_score),
                "file_rank": int(meta["rank"]),
                "file_reasons": meta["reasons"],
                "symbol_matches": matches,
                "uses_base_code_graph": True,
            }
            item_json = cand.to_json(score, evidence)
            item_json["distance"] = distance
            item_json["path"] = ["issue_anchor", path, cand.signature]
            methods.append(item_json)

    methods.sort(key=lambda x: x.get("similarity", 0.0), reverse=True)
    deduped: list[dict] = []
    seen: set[str] = set()
    for method in methods:
        sig = method.get("signature")
        if not sig or sig in seen:
            continue
        seen.add(sig)
        deduped.append(method)
        if len(deduped) >= args.top_k:
            break

    stats = {
        "seed_files": sum(1 for m in graph_files.values() if m["distance"] == 0),
        "import_neighbor_files": sum(1 for m in graph_files.values() if m["distance"] == 1),
        "candidate_files": len(graph_files),
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
    parser.add_argument("--max-seed-files", type=int, default=40)
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
            "baseline": "no_history_codegraph",
            "uses_kg": False,
            "uses_llm": False,
            "uses_hints": False,
            "uses_comments": False,
            "uses_historical_artifacts": False,
            "candidate_source": "target_issue_and_base_commit_code_graph",
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
