#!/usr/bin/env python3
"""Export KG-grounded file expansion ablations.

The ablations start from a completed strict KGCompass export. They reuse only
the KG-grounded files, reparse base-commit source, and rank file-local symbols
with deliberately simpler policies than the full path-mined selector.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Dict, List

from export_path_mined_filelocal import (
    class_for_method,
    file_evidence_from_export,
    field_terms,
    issue_sections,
    load_dataset_items,
    load_ids,
    merge_item,
    normalize_file_path,
    parse_file_entities,
    path_for_item,
)


def symbol_rank_key(item: dict, file_ev: dict, sections: dict, original_rank: int | None) -> List[object]:
    symbol_exact, symbol_terms = field_terms(item.get("name"), item.get("signature"), item.get("file_path"))
    path_exact, path_terms = field_terms(item.get("file_path"))
    title_symbol = sections["title_terms"] & symbol_terms
    title_path = sections["title_terms"] & path_terms
    narrative_symbol = sections["narrative_terms"] & symbol_terms
    narrative_path = sections["narrative_terms"] & path_terms
    exact_symbol = sections["exact_terms"] & symbol_exact
    exact_path = sections["exact_terms"] & path_exact
    evidence = item.setdefault("evidence", {})
    evidence["file_expansion_ablation"] = {
        "mode": "symbol_rank",
        "file_best_rank": int(file_ev.get("best_rank") or 999),
        "file_support": int(file_ev.get("support") or 0),
        "file_distance": int(file_ev.get("distance") or 999),
        "title_symbol_matches": sorted(title_symbol),
        "title_path_matches": sorted(title_path),
        "narrative_symbol_matches": sorted(narrative_symbol),
        "narrative_path_matches": sorted(narrative_path),
        "exact_symbol_matches": sorted(exact_symbol),
        "exact_path_matches": sorted(exact_path),
        "original_kg_rank": original_rank,
    }
    return [
        -len(title_symbol),
        -len(exact_symbol),
        -len(title_path),
        -len(exact_path),
        -len(narrative_symbol),
        -len(narrative_path),
        -int(file_ev.get("support") or 0),
        int(file_ev.get("distance") or 999),
        0 if file_ev.get("anchor_match") else 1,
        int(file_ev.get("best_rank") or 999),
        int(original_rank or 9999),
        int(item.get("start_line") or 0),
        item.get("name") or "",
    ]


def source_order_key(item: dict, file_ev: dict, original_rank: int | None) -> List[object]:
    item.setdefault("evidence", {})["file_expansion_ablation"] = {
        "mode": "source_order",
        "file_best_rank": int(file_ev.get("best_rank") or 999),
        "file_support": int(file_ev.get("support") or 0),
        "file_distance": int(file_ev.get("distance") or 999),
        "original_kg_rank": original_rank,
    }
    return [
        int(file_ev.get("best_rank") or 999),
        -int(file_ev.get("support") or 0),
        int(file_ev.get("distance") or 999),
        int(item.get("start_line") or 0),
        item.get("name") or "",
    ]


def original_rank_map(items: List[dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for idx, item in enumerate(items, start=1):
        key = item.get("signature") or item.get("name")
        if key and key not in out:
            out[key] = idx
    return out


def rerank_instance(data: dict, dataset_item: dict, mode: str) -> dict:
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
            if mode == "source_order":
                key = source_order_key(method, file_ev, rank_map.get(sig))
            elif mode == "symbol_rank":
                key = symbol_rank_key(method, file_ev, sections, rank_map.get(sig))
            else:
                raise ValueError(f"Unknown mode: {mode}")
            method["ranking_key"] = key
            candidates[sig] = merge_item(candidates.get(sig), method)

    methods = sorted(candidates.values(), key=lambda item: item.get("ranking_key") or [])
    out = deepcopy(data)
    out.setdefault("related_entities", {})
    out["related_entities"]["methods"] = methods
    out["related_entities"]["classes"] = []
    out["kg_params"] = {
        **(out.get("kg_params") or {}),
        "retrieval_mode": f"kg_grounded_file_expansion_{mode}",
        "score": mode,
        "uses_embeddings": False,
        "uses_edge_weights": False,
        "uses_discussion_comments": False,
        "tunable_retrieval_parameters": [],
    }
    out.setdefault("artifact_stats", {})["kg_grounded_files_expanded"] = len(file_map)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=["source_order", "symbol_rank"], required=True)
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
        out = rerank_instance(data, dataset[iid], args.mode)
        out["related_entities"]["methods"] = out["related_entities"]["methods"][: args.limit]
        out.setdefault("run_meta", {})["file_expansion_source_dir"] = str(args.input_dir)
        out["run_meta"]["tag"] = args.output_dir.name
        (args.output_dir / f"{iid}.json").write_text(json.dumps(out, separators=(",", ":")))
        done += 1
        if done % 50 == 0 or done == len(ids):
            print(f"[{args.mode}] {done}/{len(ids)}", flush=True)
    print(f"Saved {done} instances to {args.output_dir}")


if __name__ == "__main__":
    main()
