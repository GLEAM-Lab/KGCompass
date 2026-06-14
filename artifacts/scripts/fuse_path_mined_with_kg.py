#!/usr/bin/env python3
"""Fuse original KGCompass ranking with file-local path-mined ranking."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Dict, List


def load_ids(ids_file: Path) -> List[str]:
    ids: List[str] = []
    with ids_file.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ids.append(json.loads(line)["instance_id"] if line.startswith("{") else line)
    return ids


def entity_key(item: dict) -> str:
    return str(item.get("signature") or item.get("name") or "")


def fuse_entity_lists(original: List[dict], mined: List[dict]) -> List[dict]:
    by_key: Dict[str, dict] = {}
    for rank, item in enumerate(original, start=1):
        key = entity_key(item)
        if not key:
            continue
        out = deepcopy(item)
        out["_kg_rank"] = rank
        out["_path_mined_rank"] = 9999
        by_key[key] = out
    for rank, item in enumerate(mined, start=1):
        key = entity_key(item)
        if not key:
            continue
        if key in by_key:
            out = by_key[key]
            out["_path_mined_rank"] = rank
            out["path_details"] = item.get("path_details") or out.get("path_details")
            out.setdefault("evidence", {})["path_mining"] = (
                (item.get("evidence") or {}).get("path_mining") or {}
            )
        else:
            out = deepcopy(item)
            out["_kg_rank"] = 9999
            out["_path_mined_rank"] = rank
            by_key[key] = out

    fused = []
    for item in by_key.values():
        kg_rank = int(item.pop("_kg_rank"))
        path_rank = int(item.pop("_path_mined_rank"))
        evidence = item.setdefault("evidence", {})
        evidence["rank_union"] = {
            "kg_rank": None if kg_rank >= 9999 else kg_rank,
            "path_mined_rank": None if path_rank >= 9999 else path_rank,
        }
        item["ranking_key"] = [
            min(kg_rank, path_rank),
            0 if kg_rank < 9999 else 1,
            kg_rank,
            path_rank,
            item.get("file_path") or "",
            int(item.get("start_line") or 0),
            item.get("name") or "",
        ]
        fused.append(item)
    return sorted(fused, key=lambda item: item["ranking_key"])


def fuse_one(original_data: dict, mined_data: dict, output_tag: str, limit: int) -> dict:
    out = deepcopy(original_data)
    original_entities = original_data.get("related_entities") or {}
    mined_entities = mined_data.get("related_entities") or {}
    out.setdefault("related_entities", {})
    out["related_entities"]["methods"] = fuse_entity_lists(
        original_entities.get("methods") or [],
        mined_entities.get("methods") or [],
    )[:limit]
    out["related_entities"]["classes"] = fuse_entity_lists(
        original_entities.get("classes") or [],
        mined_entities.get("classes") or [],
    )[:limit]
    out["related_entities"]["issues"] = original_entities.get("issues") or []
    out["kg_params"] = {
        **(original_data.get("kg_params") or {}),
        "retrieval_mode": "rank_union_kg_and_file_local_path_mining",
        "score": "min_rank_union_original_kg_file_local_path_mining",
        "uses_embeddings": False,
        "uses_edge_weights": False,
        "uses_discussion_comments": False,
        "tunable_retrieval_parameters": [],
    }
    out.setdefault("run_meta", {})["path_mining_source_dir"] = str(
        mined_data.get("run_meta", {}).get("path_mining_source_dir", "")
    )
    out["run_meta"]["rank_union_tag"] = output_tag
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kg-dir", required=True, type=Path)
    parser.add_argument("--path-mined-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--ids-file", default="SWE-bench_Verified_ids.jsonl", type=Path)
    parser.add_argument("--limit", default=50, type=int)
    args = parser.parse_args()

    ids = load_ids(args.ids_file)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    for iid in ids:
        kg_file = args.kg_dir / f"{iid}.json"
        mined_file = args.path_mined_dir / f"{iid}.json"
        if not kg_file.exists() or not mined_file.exists():
            continue
        original = json.loads(kg_file.read_text())
        mined = json.loads(mined_file.read_text())
        out = fuse_one(original, mined, args.output_dir.name, args.limit)
        (args.output_dir / f"{iid}.json").write_text(json.dumps(out, separators=(",", ":")))
        done += 1
    print(f"Saved {done} fused instances to {args.output_dir}")


if __name__ == "__main__":
    main()
