#!/usr/bin/env python3
"""Evaluate ranked context sources and emit paired uncertainty ledgers."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import random
from pathlib import Path
from typing import Any, Callable


Metric = tuple[str, Callable[[dict[str, Any]], float]]
METRICS: list[Metric] = [
    ("file", lambda row: float(row["find_file"])),
    ("method", lambda row: float(row["ratio"])),
    ("mrr", lambda row: 0.0 if row.get("best_rank") is None else 1.0 / float(row["best_rank"])),
    ("hit", lambda row: float(row["hit"])),
]


def load_eval_module() -> Any:
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        repo_root / "scripts" / "eval_controls_v3.py",
        Path(__file__).with_name("eval_controls_v3.py"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location("eval_controls_v3", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    raise FileNotFoundError("Cannot locate eval_controls_v3.py")


def parse_named_path(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise ValueError(f"Expected NAME=DIR, got {raw!r}")
    name, path = raw.split("=", 1)
    if not name.strip() or not path.strip():
        raise ValueError(f"Expected NAME=DIR, got {raw!r}")
    return name.strip(), Path(path.strip())


def parse_budget_group(raw: str) -> tuple[str, Path, int]:
    parts = raw.split("=", 2)
    if len(parts) != 3:
        raise ValueError(f"Expected NAME=TOP_K=DIR, got {raw!r}")
    name, top_k_raw, path = (part.strip() for part in parts)
    if not name or not top_k_raw or not path:
        raise ValueError(f"Expected NAME=TOP_K=DIR, got {raw!r}")
    top_k = int(top_k_raw)
    if top_k <= 0:
        raise ValueError(f"TOP_K must be positive, got {top_k}")
    return name, Path(path), top_k


def parse_comparison(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ValueError(f"Expected BASELINE=TREATMENT, got {raw!r}")
    baseline, treatment = (part.strip() for part in raw.split("=", 1))
    if not baseline or not treatment:
        raise ValueError(f"Expected BASELINE=TREATMENT, got {raw!r}")
    return baseline, treatment


def exact_mcnemar_p(wins: int, losses: int) -> float:
    discordant = wins + losses
    if discordant == 0:
        return 1.0
    tail = min(wins, losses)
    probability = sum(math.comb(discordant, index) for index in range(tail + 1)) / (2**discordant)
    return min(1.0, 2.0 * probability)


def bootstrap_ci(
    pairs: list[tuple[float, float]],
    iterations: int,
    seed: int,
) -> tuple[float, float]:
    if not pairs:
        return 0.0, 0.0
    rng = random.Random(seed)
    size = len(pairs)
    deltas: list[float] = []
    for _ in range(iterations):
        total = 0.0
        for _ in range(size):
            old, new = pairs[rng.randrange(size)]
            total += new - old
        deltas.append(total / size)
    deltas.sort()
    low = deltas[int(0.025 * iterations)]
    high = deltas[min(iterations - 1, int(0.975 * iterations))]
    return low, high


def load_group(
    eval_module: Any,
    ids: list[str],
    gt_map: dict[str, dict],
    directory: Path,
    top_k: int,
) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for instance_id in ids:
        path = directory / f"{instance_id}.json"
        if not path.exists():
            continue
        rows[instance_id] = eval_module.evaluate_one_instance(
            json.loads(path.read_text(encoding="utf-8")),
            gt_map[instance_id],
            top_k,
        )
    return rows


def summarize(name: str, directory: Path, ids: list[str], rows: dict[str, dict], top_k: int) -> dict[str, Any]:
    common = [instance_id for instance_id in ids if instance_id in rows]
    if not common:
        raise ValueError(f"No rows found for {name}: {directory}")
    values = {
        metric: sum(extractor(rows[instance_id]) for instance_id in common) / len(common)
        for metric, extractor in METRICS
    }
    return {
        "name": name,
        "N": len(common),
        "top_k": top_k,
        "file_rate": values["file"],
        "method_or_entity_rate": values["method"],
        "mrr": values["mrr"],
        "hit_rate": values["hit"],
        "dir": str(directory),
    }


def paired_rows(
    baseline: str,
    treatment: str,
    ids: list[str],
    groups: dict[str, dict[str, dict]],
    top_k: int,
    iterations: int,
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    old_rows = groups[baseline]
    new_rows = groups[treatment]
    common = [instance_id for instance_id in ids if instance_id in old_rows and instance_id in new_rows]
    output: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    for metric_index, (metric, extractor) in enumerate(METRICS):
        values = [(extractor(old_rows[iid]), extractor(new_rows[iid])) for iid in common]
        wins = sum(1 for old, new in values if new > old + 1e-12)
        losses = sum(1 for old, new in values if new < old - 1e-12)
        old_mean = sum(old for old, _ in values) / len(values)
        new_mean = sum(new for _, new in values) / len(values)
        low, high = bootstrap_ci(values, iterations, seed + metric_index)
        output.append(
            {
                "baseline": baseline,
                "treatment": treatment,
                "top_k": top_k,
                "metric": metric,
                "N": len(common),
                "baseline_value": old_mean,
                "treatment_value": new_mean,
                "delta": new_mean - old_mean,
                "ci95_low": low,
                "ci95_high": high,
                "wins": wins,
                "losses": losses,
                "ties": len(values) - wins - losses,
                "exact_mcnemar_p": exact_mcnemar_p(wins, losses) if metric in {"file", "hit"} else "NA",
            }
        )
        if metric != "hit":
            continue
        for instance_id, (old, new) in zip(common, values):
            if old == new:
                continue
            disagreements.append(
                {
                    "baseline": baseline,
                    "treatment": treatment,
                    "top_k": top_k,
                    "instance_id": instance_id,
                    "direction": "treatment_only" if new > old else "baseline_only",
                    "baseline_rank": old_rows[instance_id].get("best_rank") or "NA",
                    "treatment_rank": new_rows[instance_id].get("best_rank") or "NA",
                }
            )
    return output, disagreements


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids-file", type=Path, default=Path("temp_run/SWE-bench_Verified_ids.jsonl"))
    parser.add_argument("--gt-cache", type=Path, default=Path("temp_run/output/gt_eval_cache_verified_v3_entities.json"))
    parser.add_argument("--group", action="append", default=[], help="NAME=DIR; repeat for each source")
    parser.add_argument(
        "--budget-group",
        action="append",
        default=[],
        help="NAME=TOP_K=DIR; add a group evaluated at its own budget.",
    )
    parser.add_argument("--compare", action="append", default=[], help="BASELINE=TREATMENT; repeat as needed")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--bootstrap-iters", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output-summary", type=Path, required=True)
    parser.add_argument("--output-paired", type=Path, required=True)
    parser.add_argument("--output-disagreements", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    eval_module = load_eval_module()
    ids = eval_module.load_ids(args.ids_file)
    gt_map = eval_module.load_or_build_gt_cache(ids, args.gt_cache)
    configured = [(*parse_named_path(raw), args.top_k) for raw in args.group]
    configured.extend(parse_budget_group(raw) for raw in args.budget_group)
    if not configured:
        raise ValueError("Provide at least one --group or --budget-group")
    if len({name for name, _, _ in configured}) != len(configured):
        raise ValueError("Duplicate --group name")

    groups: dict[str, dict[str, dict]] = {}
    group_top_ks: dict[str, int] = {}
    summaries: list[dict[str, Any]] = []
    for name, directory, group_top_k in configured:
        rows = load_group(eval_module, ids, gt_map, directory, group_top_k)
        groups[name] = rows
        group_top_ks[name] = group_top_k
        summaries.append(summarize(name, directory, ids, rows, group_top_k))

    paired: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    for raw in args.compare:
        baseline, treatment = parse_comparison(raw)
        missing = [name for name in (baseline, treatment) if name not in groups]
        if missing:
            raise ValueError(f"Unknown comparison group(s): {missing}")
        if group_top_ks[baseline] != group_top_ks[treatment]:
            raise ValueError(
                f"Cannot compare different budgets: {baseline}={group_top_ks[baseline]}, "
                f"{treatment}={group_top_ks[treatment]}"
            )
        pair_rows, pair_disagreements = paired_rows(
            baseline,
            treatment,
            ids,
            groups,
            group_top_ks[baseline],
            args.bootstrap_iters,
            args.seed,
        )
        paired.extend(pair_rows)
        disagreements.extend(pair_disagreements)

    write_tsv(
        args.output_summary,
        summaries,
        ["name", "N", "top_k", "file_rate", "method_or_entity_rate", "mrr", "hit_rate", "dir"],
    )
    write_tsv(
        args.output_paired,
        paired,
        [
            "baseline",
            "treatment",
            "top_k",
            "metric",
            "N",
            "baseline_value",
            "treatment_value",
            "delta",
            "ci95_low",
            "ci95_high",
            "wins",
            "losses",
            "ties",
            "exact_mcnemar_p",
        ],
    )
    write_tsv(
        args.output_disagreements,
        disagreements,
        ["baseline", "treatment", "top_k", "instance_id", "direction", "baseline_rank", "treatment_rank"],
    )
    print(f"wrote {args.output_summary}")
    print(f"wrote {args.output_paired}")
    print(f"wrote {args.output_disagreements}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
