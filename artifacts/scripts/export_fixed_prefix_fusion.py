#!/usr/bin/env python3
"""Build a fixed-budget primary-prefix plus secondary-tail ranking."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def ranked_methods(payload: dict) -> list[dict]:
    methods = (payload.get("related_entities") or {}).get("methods") or []
    return sorted(methods, key=lambda item: float(item.get("similarity") or 0.0), reverse=True)


def append_unique(output: list[dict], candidates: list[dict], limit: int) -> None:
    seen = {item.get("signature") for item in output if item.get("signature")}
    for candidate in candidates:
        signature = candidate.get("signature")
        if not signature or signature in seen:
            continue
        output.append(dict(candidate))
        seen.add(signature)
        if len(output) >= limit:
            return


def fuse(primary: list[dict], secondary: list[dict], budget: int, primary_prefix: int, secondary_pool: int) -> list[dict]:
    output: list[dict] = []
    append_unique(output, primary[:primary_prefix], budget)
    append_unique(output, secondary[:secondary_pool], budget)
    append_unique(output, primary[primary_prefix:], budget)
    append_unique(output, secondary[secondary_pool:], budget)
    for rank, item in enumerate(output, start=1):
        item["similarity"] = float(2.0 - 0.01 * (rank - 1))
    return output[:budget]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-dir", required=True, type=Path)
    parser.add_argument("--secondary-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--budget", type=int, default=20)
    parser.add_argument("--primary-prefix", type=int)
    parser.add_argument("--secondary-pool", type=int)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prefix = args.primary_prefix if args.primary_prefix is not None else (args.budget + 1) // 2
    secondary_pool = args.secondary_pool if args.secondary_pool is not None else args.budget
    if args.budget <= 0 or not 0 <= prefix <= args.budget or secondary_pool <= 0:
        raise ValueError("Require budget > 0, 0 <= primary-prefix <= budget, and secondary-pool > 0")
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
        methods = fuse(
            ranked_methods(primary_payload),
            ranked_methods(secondary_payload),
            args.budget,
            prefix,
            secondary_pool,
        )
        primary_entities = primary_payload.get("related_entities") or {}
        secondary_entities = secondary_payload.get("related_entities") or {}
        output = {
            "related_entities": {
                "methods": methods,
                "classes": secondary_entities.get("classes") or primary_entities.get("classes") or [],
                "issues": secondary_entities.get("issues") or primary_entities.get("issues") or [],
            },
            "artifact_stats": primary_payload.get("artifact_stats") or {},
            "fusion_params": {
                "strategy": "fixed_primary_prefix_secondary_tail",
                "budget": args.budget,
                "primary_prefix": prefix,
                "secondary_pool": secondary_pool,
                "primary_dir": str(args.primary_dir),
                "secondary_dir": str(args.secondary_dir),
            },
        }
        destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1
    print(f"wrote {written} fixed-prefix fusions to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
