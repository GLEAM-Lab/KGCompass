#!/usr/bin/env python3
"""Summarize calc_prefl JSONL cache files into table-ready metrics."""

import argparse
import json
from pathlib import Path


def _best_positive_rank(entry: dict) -> int | None:
    ranks = entry.get("ranks") or {}
    positive = []
    for raw_rank, count in ranks.items():
        try:
            rank = int(raw_rank)
            count = int(count)
        except (TypeError, ValueError):
            continue
        if rank > 0 and count > 0:
            positive.append(rank)
    return min(positive) if positive else None


def summarize(cache_file: Path) -> dict:
    n = 0
    file_hits = 0
    method_sum = 0.0
    top20_hits = 0
    reciprocal_rank_sum = 0.0
    statuses = {}

    with cache_file.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            status = entry.get("status", "unknown")
            statuses[status] = statuses.get(status, 0) + 1
            if not entry.get("tot_included"):
                continue
            n += 1
            file_hits += int(entry.get("find_file", 0) or 0)
            method_sum += float(entry.get("found_methods_ratio", 0.0) or 0.0)
            if int(entry.get("morethanone", 0) or 0) > 0:
                top20_hits += 1
            best_rank = _best_positive_rank(entry)
            if best_rank:
                reciprocal_rank_sum += 1.0 / best_rank

    return {
        "cache_file": str(cache_file),
        "N": n,
        "file_rate": file_hits / n if n else 0.0,
        "method_or_entity_rate": method_sum / n if n else 0.0,
        "mrr": reciprocal_rank_sum / n if n else 0.0,
        "top20_hit_rate": top20_hits / n if n else 0.0,
        "statuses": statuses,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache_file", help="calc_prefl JSONL cache file")
    parser.add_argument("--name", default=None, help="Optional row name")
    parser.add_argument("--tsv", action="store_true", help="Print TSV instead of JSON")
    args = parser.parse_args()

    summary = summarize(Path(args.cache_file))
    if args.name:
        summary["name"] = args.name

    if args.tsv:
        print("name\tN\tfile_rate\tmethod_or_entity_rate\tmrr\ttop20_hit_rate\tcache_file")
        name = summary.get("name") or Path(args.cache_file).stem
        print(
            f"{name}\t{summary['N']}\t{summary['file_rate']:.6f}\t"
            f"{summary['method_or_entity_rate']:.6f}\t{summary['mrr']:.6f}\t"
            f"{summary['top20_hit_rate']:.6f}\t{summary['cache_file']}"
        )
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
