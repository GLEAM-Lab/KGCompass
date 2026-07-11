#!/usr/bin/env python3
"""Fuse two ranked code-entity sources with deterministic equal-weight RRF."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ranked_entities(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    entities = (payload.get("related_entities") or {}).get(key) or []
    # Python's sort is stable, so source-defined order resolves equal scores.
    return sorted(entities, key=lambda item: -float(item.get("similarity") or 0.0))


def entity_id(item: dict[str, Any]) -> str:
    signature = item.get("signature") or item.get("name")
    if signature:
        return str(signature)
    return "|".join(
        [
            str(item.get("file_path") or ""),
            str(item.get("start_line") or ""),
            str(item.get("entity_type") or ""),
        ]
    )


def rank_map(entities: list[dict[str, Any]]) -> dict[str, tuple[int, dict[str, Any]]]:
    output: dict[str, tuple[int, dict[str, Any]]] = {}
    for rank, entity in enumerate(entities, start=1):
        identifier = entity_id(entity)
        if identifier and identifier not in output:
            output[identifier] = (rank, entity)
    return output


def fuse_entities(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
    rrf_k: int,
    limit: int,
) -> list[dict[str, Any]]:
    primary_map = rank_map(primary)
    secondary_map = rank_map(secondary)
    rows: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    for identifier in sorted(primary_map.keys() | secondary_map.keys()):
        primary_entry = primary_map.get(identifier)
        secondary_entry = secondary_map.get(identifier)
        primary_rank = primary_entry[0] if primary_entry else None
        secondary_rank = secondary_entry[0] if secondary_entry else None
        score = 0.0
        if primary_rank is not None:
            score += 1.0 / (rrf_k + primary_rank)
        if secondary_rank is not None:
            score += 1.0 / (rrf_k + secondary_rank)

        base = primary_entry[1] if primary_entry else secondary_entry[1]
        fused = dict(base)
        fused["similarity"] = score
        fused["fusion_evidence"] = {
            "primary_rank": primary_rank,
            "secondary_rank": secondary_rank,
            "rrf_score": score,
        }
        present_count = int(primary_rank is not None) + int(secondary_rank is not None)
        best_rank = min(rank for rank in (primary_rank, secondary_rank) if rank is not None)
        source_priority = 0 if primary_rank is not None else 1
        stable_key = (
            -score,
            -present_count,
            best_rank,
            source_priority,
            str(fused.get("file_path") or ""),
            int(fused.get("start_line") or 0),
            identifier,
        )
        rows.append((stable_key, fused))

    rows.sort(key=lambda row: row[0])
    return [entity for _, entity in rows[:limit]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-dir", required=True, type=Path)
    parser.add_argument("--secondary-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.top_k <= 0 or args.rrf_k < 0:
        raise ValueError("Require top-k > 0 and rrf-k >= 0")

    primary_ids = {path.stem for path in args.primary_dir.glob("*.json")}
    secondary_ids = {path.stem for path in args.secondary_dir.glob("*.json")}
    instance_ids = sorted(primary_ids & secondary_ids)
    if not instance_ids:
        raise ValueError("No shared JSON instances between the two input directories")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for instance_id in instance_ids:
        destination = args.output_dir / f"{instance_id}.json"
        if destination.exists() and not args.force:
            continue

        primary_payload = load(args.primary_dir / destination.name)
        secondary_payload = load(args.secondary_dir / destination.name)
        primary_related = primary_payload.get("related_entities") or {}
        secondary_related = secondary_payload.get("related_entities") or {}
        output = {
            "related_entities": {
                "methods": fuse_entities(
                    ranked_entities(primary_payload, "methods"),
                    ranked_entities(secondary_payload, "methods"),
                    args.rrf_k,
                    args.top_k,
                ),
                "classes": fuse_entities(
                    ranked_entities(primary_payload, "classes"),
                    ranked_entities(secondary_payload, "classes"),
                    args.rrf_k,
                    args.top_k,
                ),
                "issues": primary_related.get("issues") or secondary_related.get("issues") or [],
            },
            "artifact_stats": {
                "primary": primary_payload.get("artifact_stats") or {},
                "secondary": secondary_payload.get("artifact_stats") or {},
            },
            "fusion_params": {
                "strategy": "equal_weight_reciprocal_rank_fusion",
                "rrf_k": args.rrf_k,
                "top_k": args.top_k,
                "tie_break": "source_count,best_rank,primary_source,file_path,start_line,entity_id",
                "primary_dir": str(args.primary_dir),
                "secondary_dir": str(args.secondary_dir),
            },
        }
        destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1

    print(f"wrote {written} equal-weight RRF fusions to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
