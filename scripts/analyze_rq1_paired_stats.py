#!/usr/bin/env python3
"""Paired statistics for RQ-1 localization comparisons."""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Callable, Dict, List

from eval_controls_v3 import evaluate_one_instance, load_ids, load_or_build_gt_cache


def parse_group(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise ValueError(f"Invalid group spec: {spec}")
    name, path = spec.split("=", 1)
    return name.strip(), Path(path.strip())


def load_eval(group_dir: Path, ids: List[str], gt_map: Dict[str, dict], top_k: int) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for iid in ids:
        fp = group_dir / f"{iid}.json"
        if not fp.exists():
            continue
        out[iid] = evaluate_one_instance(json.loads(fp.read_text()), gt_map[iid], top_k)
    return out


def mrr_value(row: dict) -> float:
    rank = row.get("best_rank")
    return 0.0 if rank is None else 1.0 / float(rank)


METRICS: Dict[str, Callable[[dict], float]] = {
    "file": lambda row: float(row["find_file"]),
    "method": lambda row: float(row["ratio"]),
    "mrr": mrr_value,
    "hit": lambda row: float(row["hit"]),
}


def bootstrap_ci(diffs: List[float], rounds: int = 10000) -> tuple[float, float]:
    rng = random.Random(20260531)
    n = len(diffs)
    means = []
    for _ in range(rounds):
        total = 0.0
        for _ in range(n):
            total += diffs[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    return means[int(0.025 * rounds)], means[int(0.975 * rounds)]


def exact_mcnemar_p(wins: int, losses: int) -> float | None:
    n = wins + losses
    if n == 0:
        return None
    k = min(wins, losses)
    # Two-sided exact binomial test under p=0.5 for discordant pairs.
    prob = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return min(1.0, 2.0 * prob)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", required=True, help="Main group as name=dir")
    parser.add_argument("--baseline", action="append", required=True, help="Baseline group as name=dir")
    parser.add_argument("--ids-file", default="SWE-bench_Verified_ids.jsonl", type=Path)
    parser.add_argument("--gt-cache", default="temp_run/output/gt_eval_cache_verified_v3_entities.json", type=Path)
    parser.add_argument("--top-k", default=20, type=int)
    parser.add_argument("--output-tsv", required=True, type=Path)
    args = parser.parse_args()

    ids = load_ids(args.ids_file)
    gt_map = load_or_build_gt_cache(ids, args.gt_cache)
    main_name, main_dir = parse_group(args.main)
    main_eval = load_eval(main_dir, ids, gt_map, args.top_k)
    baselines = [(name, path, load_eval(path, ids, gt_map, args.top_k)) for name, path in map(parse_group, args.baseline)]

    args.output_tsv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_tsv.open("w") as f:
        f.write("main\tbaseline\tmetric\tN\tdelta_pp\tci_low_pp\tci_high_pp\twins\tlosses\tmcnemar_p\n")
        for base_name, _path, base_eval in baselines:
            common = [iid for iid in ids if iid in main_eval and iid in base_eval]
            for metric, getter in METRICS.items():
                diffs = [getter(main_eval[iid]) - getter(base_eval[iid]) for iid in common]
                mean = sum(diffs) / len(diffs)
                low, high = bootstrap_ci(diffs)
                wins = sum(1 for diff in diffs if diff > 1e-12)
                losses = sum(1 for diff in diffs if diff < -1e-12)
                p = exact_mcnemar_p(wins, losses) if metric in {"file", "hit"} else None
                f.write(
                    f"{main_name}\t{base_name}\t{metric}\t{len(common)}\t"
                    f"{mean * 100:.3f}\t{low * 100:.3f}\t{high * 100:.3f}\t"
                    f"{wins}\t{losses}\t{'' if p is None else f'{p:.6g}'}\n"
                )
    print(f"Saved: {args.output_tsv}")


if __name__ == "__main__":
    main()
