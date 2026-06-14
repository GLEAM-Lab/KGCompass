#!/usr/bin/env python3
"""Expand existing KG file paths into file-local method paths.

This script is intentionally export-only: it does not query Neo4j and it does
not use ground-truth patches. It starts from an existing KGCompass JSON export,
keeps the issue->file evidence discovered by KGCompass, and then mines local
source structure inside those files to rank candidate methods/classes.
"""

from __future__ import annotations

import argparse
import ast
import json
import keyword
import os
import re
import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from datasets import Dataset


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "kgcompass"))
import utils  # type: ignore  # noqa: E402


STOPWORDS = {
    "and",
    "are",
    "about",
    "after",
    "again",
    "against",
    "also",
    "because",
    "before",
    "between",
    "but",
    "cannot",
    "can",
    "could",
    "does",
    "doesn",
    "during",
    "else",
    "error",
    "expected",
    "file",
    "files",
    "for",
    "from",
    "have",
    "had",
    "has",
    "her",
    "his",
    "if",
    "into",
    "its",
    "issue",
    "least",
    "line",
    "may",
    "model",
    "models",
    "more",
    "most",
    "none",
    "only",
    "our",
    "out",
    "over",
    "problem",
    "raise",
    "return",
    "root",
    "same",
    "self",
    "should",
    "some",
    "such",
    "that",
    "the",
    "their",
    "there",
    "these",
    "they",
    "this",
    "traceback",
    "through",
    "too",
    "true",
    "false",
    "under",
    "very",
    "when",
    "where",
    "while",
    "will",
    "within",
    "without",
    "with",
    "would",
    "you",
    "your",
} | set(keyword.kwlist)


def split_identifier(value: object) -> List[str]:
    if not value:
        return []
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value))
    raw_tokens = re.split(r"[^A-Za-z0-9]+", spaced)
    out: List[str] = []
    def add(token: str) -> None:
        if len(token) >= 3 and token not in STOPWORDS:
            out.append(token)

    for token in raw_tokens:
        token = token.lower()
        if len(token) < 3 or token in STOPWORDS:
            continue
        add(token)
        if token.endswith("ing") and len(token) > 5:
            add(token[:-3])
        if token.endswith("ies") and len(token) > 5:
            add(token[:-3] + "y")
        if token.endswith("s") and len(token) > 4:
            add(token[:-1])
    return out


def identifier_exact_terms(value: object) -> set[str]:
    if not value:
        return set()
    out: set[str] = set()
    for token in re.findall(
        r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*",
        str(value),
    ):
        token = token.lower()
        if len(token) < 3 or token in STOPWORDS:
            continue
        out.add(token)
        for part in re.split(r"[._]+", token):
            if len(part) >= 3 and part not in STOPWORDS:
                out.add(part)
    return out


def issue_code_like_exact_terms(value: object) -> set[str]:
    """Return exact anchors that look like symbols rather than prose words."""
    if not value:
        return set()
    out: set[str] = set()
    for raw_token in re.findall(
        r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*",
        str(value),
    ):
        if not (
            "_" in raw_token
            or "." in raw_token
            or re.search(r"[a-z][A-Z]", raw_token)
            or re.search(r"\d", raw_token)
        ):
            continue
        token = raw_token.lower()
        if len(token) < 3 or token in STOPWORDS:
            continue
        out.add(token)
        if "." in token:
            tail = token.rsplit(".", 1)[-1]
            if len(tail) >= 3 and tail not in STOPWORDS:
                out.add(tail)
        else:
            for part in re.split(r"[_]+", token):
                if len(part) >= 3 and part not in STOPWORDS:
                    out.add(part)
    return out


def issue_sections(root_meta: dict) -> dict:
    title = str(root_meta.get("title") or "")
    body = str(root_meta.get("content") or "")
    name = str(root_meta.get("name") or "")
    diagnostic_lines = []
    narrative_lines = []
    in_traceback = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("Traceback") or stripped == "Traceback:":
            in_traceback = True
        is_stack_line = bool(
            re.match(r'File ["\'].*["\'], line \d+', stripped)
            or re.match(r"[A-Za-z_][A-Za-z0-9_.]*Error:", stripped)
        )
        if in_traceback or is_stack_line:
            diagnostic_lines.append(line)
        else:
            narrative_lines.append(line)
    narrative = "\n".join(narrative_lines)
    diagnostic = "\n".join(diagnostic_lines)
    code_spans = " ".join(re.findall(r"`([^`]+)`", "\n".join([title, body, name])))
    quoted = " ".join(re.findall(r"['\"]([A-Za-z_][A-Za-z0-9_.-]+)['\"]", body))
    title_terms = set(split_identifier(title))
    narrative_terms = set(split_identifier(narrative))
    title_exact_terms = identifier_exact_terms(title)
    exact_terms = (
        title_exact_terms
        | identifier_exact_terms(code_spans)
        | identifier_exact_terms(quoted)
        | {
            term
            for term in identifier_exact_terms(narrative)
            if "_" in term or "." in term
        }
    )
    diagnostic_terms = identifier_exact_terms(diagnostic)
    return {
        "title_terms": title_terms,
        "narrative_terms": narrative_terms,
        "issue_terms": title_terms | narrative_terms | set(split_identifier(code_spans)) | set(split_identifier(quoted)),
        "title_exact_terms": title_exact_terms,
        "exact_terms": exact_terms,
        "diagnostic_terms": diagnostic_terms,
    }


def field_terms(*fields: object) -> Tuple[set[str], set[str]]:
    exact: set[str] = set()
    lexical: set[str] = set()
    for field in fields:
        exact |= identifier_exact_terms(field)
        lexical.update(split_identifier(field))
    return exact, lexical


def local_symbol_text(item: dict) -> str:
    file_path = normalize_file_path(item.get("file_path") or "")
    module = file_path[:-3].replace("/", ".") if file_path.endswith(".py") else ""
    values = []
    for key in ("name", "signature"):
        value = str(item.get(key) or "")
        if module and value.startswith(module + "."):
            value = value[len(module) + 1 :]
        values.append(value)
    return "\n".join(values)


def owner_symbol_text(item: dict) -> str:
    name = str(item.get("name") or "")
    file_path = normalize_file_path(item.get("file_path") or "")
    module = file_path[:-3].replace("/", ".") if file_path.endswith(".py") else ""
    if module and name.startswith(module + "."):
        name = name[len(module) + 1 :]
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[0]


def discover_arrow() -> Path:
    root = Path.home() / ".cache/huggingface/datasets/princeton-nlp___swe-bench_verified/default/0.0.0"
    cands = sorted(root.glob("*/swe-bench_verified-test.arrow"), key=os.path.getmtime)
    if not cands:
        raise FileNotFoundError("Cannot locate cached SWE-bench Verified arrow file")
    return cands[-1]


def load_dataset_items(ids: Iterable[str]) -> Dict[str, dict]:
    id_set = set(ids)
    ds = Dataset.from_file(str(discover_arrow()))
    return {item["instance_id"]: dict(item) for item in ds if item.get("instance_id") in id_set}


def load_ids(ids_file: Path) -> List[str]:
    out: List[str] = []
    with ids_file.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line)["instance_id"] if line.startswith("{") else line)
    return out


def iter_local_repo_roots(repo_full_name: str) -> Iterable[Path]:
    repo_id = repo_full_name.replace("/", "__")
    repo_name = repo_full_name.split("/")[-1]
    for root in [REPO_ROOT / "playground" / repo_id, REPO_ROOT / "playground" / repo_name]:
        if root.is_dir():
            yield root


def get_local_commit_file_content(repo_full_name: str, commit_sha: str, file_path: str) -> str | None:
    for repo_root in iter_local_repo_roots(repo_full_name):
        content = utils._get_file_content_by_commit(str(repo_root), commit_sha, file_path)
        if content is not None:
            return content
    return None


def normalize_file_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def is_boilerplate(item: dict) -> bool:
    name = (item.get("name") or "").lower()
    base = name.rsplit(".", 1)[-1]
    if base in {"__all__", "__version__", "__doc__", "__bibtex__", "__citation__"}:
        return True
    if base.startswith("__") and base.endswith("__") and base not in {"__init__"}:
        return True
    return False


def file_evidence_from_export(data: dict) -> Dict[str, dict]:
    per_file: Dict[str, dict] = {}
    items = (data.get("related_entities") or {}).get("methods", []) + (
        (data.get("related_entities") or {}).get("classes", [])
    )
    for rank, item in enumerate(items, start=1):
        file_path = normalize_file_path(item.get("file_path") or "")
        if not file_path:
            continue
        evidence = item.get("evidence") or {}
        current = per_file.setdefault(
            file_path,
            {
                "file_path": file_path,
                "best_rank": rank,
                "support": 0,
                "distance": 999,
                "anchor_match": False,
                "issue_exact_anchor_matches": set(),
                "issue_token_matches": set(),
                "issue_path_token_matches": set(),
                "root_file_path_details": None,
            },
        )
        current["best_rank"] = min(current["best_rank"], rank)
        current["support"] = max(current["support"], int(evidence.get("support") or 0))
        current["distance"] = min(current["distance"], int(evidence.get("distance") or 999))
        current["anchor_match"] = bool(current["anchor_match"] or evidence.get("anchor_match"))
        for key in ("issue_exact_anchor_matches", "issue_token_matches", "issue_path_token_matches"):
            current[key].update(evidence.get(key) or [])
        if current["root_file_path_details"] is None:
            for detail in item.get("path_details") or []:
                if (
                    detail.get("start_type") == "issue"
                    and detail.get("end_type") == "file"
                    and normalize_file_path(str(detail.get("end_node") or "")) in {file_path, normalize_file_path(file_path)}
                ):
                    current["root_file_path_details"] = [deepcopy(detail)]
                    break
            if current["root_file_path_details"] is None:
                current["root_file_path_details"] = [
                    {
                        "start_node": "root",
                        "end_node": file_path,
                        "start_labels": ["Issue"],
                        "end_labels": ["File"],
                        "start_type": "issue",
                        "end_type": "file",
                        "type": "RELATED",
                        "description": "referenced by KGCompass candidate file",
                    }
                ]
    for value in per_file.values():
        for key in ("issue_exact_anchor_matches", "issue_token_matches", "issue_path_token_matches"):
            value[key] = sorted(value[key])
    return per_file


def class_for_method(method: dict, classes: List[dict]) -> dict | None:
    start = int(method.get("start_line") or 0)
    end = int(method.get("end_line") or start)
    best = None
    best_span = None
    for cls in classes:
        cstart = int(cls.get("start_line") or 0)
        cend = int(cls.get("end_line") or 0)
        if cstart <= start and end <= cend:
            span = cend - cstart
            if best_span is None or span < best_span:
                best = cls
                best_span = span
    return best


def path_for_item(file_ev: dict, item: dict, cls: dict | None) -> List[dict]:
    path = deepcopy(file_ev.get("root_file_path_details") or [])
    file_path = file_ev["file_path"]
    if cls is not None and cls.get("name") and cls.get("name") != item.get("name"):
        path.append(
            {
                "start_node": file_path,
                "end_node": cls.get("name"),
                "start_labels": ["File"],
                "end_labels": ["Class"],
                "start_type": "file",
                "end_type": "class",
                "type": "CONTAINS",
                "description": "file-local class scope",
            }
        )
        path.append(
            {
                "start_node": cls.get("name"),
                "end_node": item.get("name"),
                "start_labels": ["Class"],
                "end_labels": ["Method"],
                "start_type": "class",
                "end_type": "method",
                "type": "CONTAINS",
                "description": "class-local method scope",
            }
        )
    else:
        path.append(
            {
                "start_node": file_path,
                "end_node": item.get("name"),
                "start_labels": ["File"],
                "end_labels": ["Method"],
                "start_type": "file",
                "end_type": "method",
                "type": "CONTAINS",
                "description": "file-local method scope",
            }
        )
    return path


def parse_file_entities(repo: str, base_commit: str, file_path: str) -> Tuple[List[dict], List[dict]]:
    content = get_local_commit_file_content(repo, base_commit, file_path)
    if content is None:
        return [], []
    classes, methods = utils.get_class_and_method_from_content(content, file_path, repo)
    return classes or [], methods or []


def score_item(item: dict, file_ev: dict, sections: dict, original_rank: int | None) -> dict:
    symbol_exact, symbol_terms = field_terms(item.get("name"), item.get("signature"), item.get("file_path"))
    path_exact, path_terms = field_terms(item.get("file_path"))
    source_exact, source_terms = field_terms(item.get("source_code"), item.get("doc_string"))
    title_symbol = sections["title_terms"] & symbol_terms
    title_path = sections["title_terms"] & path_terms
    title_source = sections["title_terms"] & source_terms
    narrative_symbol = sections["narrative_terms"] & symbol_terms
    narrative_path = sections["narrative_terms"] & path_terms
    narrative_source = sections["narrative_terms"] & source_terms
    exact_symbol = sections["exact_terms"] & symbol_exact
    exact_path = sections["exact_terms"] & path_exact
    exact_source = sections["exact_terms"] & source_exact
    diagnostic_symbol = sections["diagnostic_terms"] & symbol_exact
    source_only_signal = (sections["issue_terms"] & source_terms) - (sections["issue_terms"] & symbol_terms)
    strong_exact_symbol = {
        term
        for term in exact_symbol
        if len(term) >= 6 or "_" in term or "." in term or any(ch.isdigit() for ch in term)
    }
    owner_exact, _ = field_terms(owner_symbol_text(item))
    owner_anchor = sections["title_exact_terms"] & owner_exact
    evidence = item.setdefault("evidence", {})
    evidence["path_mining"] = {
        "file_best_rank": int(file_ev.get("best_rank") or 999),
        "file_support": int(file_ev.get("support") or 0),
        "file_distance": int(file_ev.get("distance") or 999),
        "file_anchor_match": bool(file_ev.get("anchor_match")),
        "title_symbol_matches": sorted(title_symbol),
        "title_path_matches": sorted(title_path),
        "title_source_matches": sorted(title_source),
        "narrative_symbol_matches": sorted(narrative_symbol),
        "narrative_path_matches": sorted(narrative_path),
        "narrative_source_matches": sorted(narrative_source),
        "exact_symbol_matches": sorted(exact_symbol),
        "exact_path_matches": sorted(exact_path),
        "strong_exact_symbol_matches": sorted(strong_exact_symbol),
        "owner_anchor_matches": sorted(owner_anchor),
        "exact_source_matches": sorted(exact_source),
        "diagnostic_symbol_matches": sorted(diagnostic_symbol),
        "source_only_matches": sorted(source_only_signal),
        "original_kg_rank": original_rank,
    }
    # Lexicographic and parameter-free: issue title/source agreement dominates,
    # KG file support constrains the search space, then original KG order breaks ties.
    key = [
        -len(title_symbol),
        -len(title_source),
        -len(exact_symbol),
        -len(exact_source),
        -len(narrative_symbol),
        -len(source_only_signal),
        -len(narrative_source),
        -int(file_ev.get("support") or 0),
        int(file_ev.get("distance") or 999),
        0 if file_ev.get("anchor_match") else 1,
        1 if is_boilerplate(item) else 0,
        int(file_ev.get("best_rank") or 999),
        int(original_rank or 9999),
        int(item.get("start_line") or 0),
        item.get("name") or "",
    ]
    if diagnostic_symbol and not (title_symbol or exact_symbol or narrative_symbol or source_only_signal):
        key[10] += 1
    item["ranking_key"] = key
    return item


def original_rank_map(items: List[dict]) -> Dict[str, int]:
    out = {}
    for idx, item in enumerate(items, start=1):
        sig = item.get("signature") or item.get("name")
        if sig and sig not in out:
            out[sig] = idx
    return out


def merge_item(existing: dict | None, new_item: dict) -> dict:
    if existing is None:
        return new_item
    return existing if existing.get("ranking_key", []) <= new_item.get("ranking_key", []) else new_item


def rerank_instance(data: dict, dataset_item: dict) -> dict:
    root_meta = (data.get("run_meta") or {}).get("active_root") or {}
    sections = issue_sections(root_meta)
    file_map = file_evidence_from_export(data)
    original_methods = (data.get("related_entities") or {}).get("methods", [])
    rank_map = original_rank_map(original_methods)
    repo = dataset_item["repo"]
    base_commit = dataset_item["base_commit"]

    candidates: Dict[str, dict] = {}
    for file_path, file_ev in file_map.items():
        classes, methods = parse_file_entities(repo, base_commit, file_path)
        for method in methods:
            method = deepcopy(method)
            method["entity_type"] = "method"
            method["file_path"] = normalize_file_path(method.get("file_path") or file_path)
            cls = class_for_method(method, classes)
            method["path_details"] = path_for_item(file_ev, method, cls)
            sig = method.get("signature") or method.get("name")
            method = score_item(method, file_ev, sections, rank_map.get(sig))
            candidates[sig] = merge_item(candidates.get(sig), method)
        for cls in classes:
            cls = deepcopy(cls)
            cls["entity_type"] = "class"
            cls["file_path"] = normalize_file_path(cls.get("file_path") or file_path)
            cls["signature"] = cls.get("name")
            cls["path_details"] = [
                *deepcopy(file_ev.get("root_file_path_details") or []),
                {
                    "start_node": file_path,
                    "end_node": cls.get("name"),
                    "start_labels": ["File"],
                    "end_labels": ["Class"],
                    "start_type": "file",
                    "end_type": "class",
                    "type": "CONTAINS",
                    "description": "file-local class scope",
                },
            ]
            sig = cls.get("signature") or cls.get("name")
            cls = score_item(cls, file_ev, sections, rank_map.get(sig))
            candidates[sig] = merge_item(candidates.get(sig), cls)

    methods = sorted(
        [item for item in candidates.values() if item.get("entity_type") == "method"],
        key=lambda item: item.get("ranking_key") or [],
    )
    classes = sorted(
        [item for item in candidates.values() if item.get("entity_type") == "class"],
        key=lambda item: item.get("ranking_key") or [],
    )
    out = deepcopy(data)
    out["related_entities"]["methods"] = methods
    out["related_entities"]["classes"] = classes
    kg_params = out.setdefault("kg_params", {})
    kg_params["retrieval_mode"] = "path_mined_file_local_expansion"
    kg_params["score"] = "lexicographic_issue_file_source_path_mining"
    kg_params["uses_embeddings"] = False
    kg_params["uses_edge_weights"] = False
    kg_params["uses_discussion_comments"] = False
    kg_params["tunable_retrieval_parameters"] = []
    out.setdefault("artifact_stats", {})["path_mined_files"] = len(file_map)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--ids-file", default="SWE-bench_Verified_ids.jsonl", type=Path)
    parser.add_argument("--limit", default=50, type=int)
    args = parser.parse_args()

    ids = load_ids(args.ids_file)
    dataset = load_dataset_items(ids)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    for iid in ids:
        src = args.input_dir / f"{iid}.json"
        if not src.exists():
            continue
        data = json.loads(src.read_text())
        out = rerank_instance(data, dataset[iid])
        out["related_entities"]["methods"] = out["related_entities"]["methods"][: args.limit]
        out["related_entities"]["classes"] = out["related_entities"]["classes"][: args.limit]
        out.setdefault("run_meta", {})["path_mining_source_dir"] = str(args.input_dir)
        out.setdefault("run_meta", {})["tag"] = args.output_dir.name
        (args.output_dir / f"{iid}.json").write_text(json.dumps(out, separators=(",", ":")))
        done += 1
        if done % 50 == 0 or done == len(ids):
            print(f"[path-mined] {done}/{len(ids)}", flush=True)
    print(f"Saved {done} instances to {args.output_dir}")


if __name__ == "__main__":
    main()
