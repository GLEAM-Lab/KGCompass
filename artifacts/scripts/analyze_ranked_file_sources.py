#!/usr/bin/env python3
"""Evaluate ranked unique-file sources before file-local mining."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import random
from pathlib import Path
from typing import Any


def load_eval_module() -> Any:
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "scripts" / "eval_controls_v3.py"
    if not path.exists():
        path = Path(__file__).with_name("eval_controls_v3.py")
    spec = importlib.util.spec_from_file_location("eval_controls_v3", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"Cannot load evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_named_path(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise ValueError(f"Expected NAME=DIR, got {raw!r}")
    name, path = (part.strip() for part in raw.split("=", 1))
    if not name or not path:
        raise ValueError(f"Expected NAME=DIR, got {raw!r}")
    return name, Path(path)


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


def bootstrap_ci(values: list[tuple[int, int]], iterations: int, seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    size = len(values)
    deltas: list[float] = []
    for _ in range(iterations):
        total = 0
        for _ in range(size):
            old, new = values[rng.randrange(size)]
            total += new - old
        deltas.append(total / size)
    deltas.sort()
    return deltas[int(0.025 * iterations)], deltas[min(iterations - 1, int(0.975 * iterations))]


def ranked_files(payload: dict, top_files: int) -> list[str]:
    methods = (payload.get("related_entities") or {}).get("methods") or []
    methods = sorted(methods, key=lambda item: float(item.get("similarity") or 0.0), reverse=True)
    output: list[str] = []
    seen: set[str] = set()
    for method in methods:
        file_path = (method.get("file_path") or "").replace("\\", "/").lstrip("./")
        if not file_path or file_path in seen:
            continue
        seen.add(file_path)
        output.append(file_path)
        if len(output) >= top_files:
            break
    return output


def file_matches(candidate: str, target: str) -> bool:
    candidate = candidate.replace("\\", "/").lstrip("./")
    target = target.replace("\\", "/").lstrip("./")
    return candidate == target or candidate.endswith(f"/{target}") or target.endswith(f"/{candidate}")


def evaluate_group(directory: Path, ids: list[str], gt_map: dict[str, dict], top_files: int) -> dict[str, int]:
    outcomes: dict[str, int] = {}
    for instance_id in ids:
        source = directory / f"{instance_id}.json"
        if not source.exists():
            continue
        files = ranked_files(json.loads(source.read_text(encoding="utf-8")), top_files)
        patch_files = gt_map[instance_id]["patch_files"]
        outcomes[instance_id] = int(
            any(file_matches(file_path, patch_file) for file_path in files for patch_file in patch_files)
        )
    return outcomes


def write_tsv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids-file", type=Path, default=Path("temp_run/SWE-bench_Verified_ids.jsonl"))
    parser.add_argument("--gt-cache", type=Path, default=Path("temp_run/output/gt_eval_cache_verified_v3_entities.json"))
    parser.add_argument("--group", action="append", required=True, help="NAME=DIR; repeat as needed")
    parser.add_argument("--compare", action="append", default=[], help="BASELINE=TREATMENT")
    parser.add_argument("--top-files", type=int, default=20)
    parser.add_argument("--bootstrap-iters", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output-summary", required=True, type=Path)
    parser.add_argument("--output-paired", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.top_files <= 0:
        raise ValueError("--top-files must be positive")
    eval_module = load_eval_module()
    ids = eval_module.load_ids(args.ids_file)
    gt_map = eval_module.load_or_build_gt_cache(ids, args.gt_cache)
    configured = [parse_named_path(raw) for raw in args.group]
    if len({name for name, _ in configured}) != len(configured):
        raise ValueError("Duplicate --group name")

    groups: dict[str, dict[str, int]] = {}
    summary_rows: list[dict] = []
    for name, directory in configured:
        outcomes = evaluate_group(directory, ids, gt_map, args.top_files)
        groups[name] = outcomes
        hits = sum(outcomes.values())
        summary_rows.append(
            {
                "name": name,
                "N": len(outcomes),
                "top_files": args.top_files,
                "file_hits": hits,
                "file_coverage": hits / len(outcomes),
                "dir": str(directory),
            }
        )

    paired_rows: list[dict] = []
    for raw in args.compare:
        baseline, treatment = parse_comparison(raw)
        if baseline not in groups or treatment not in groups:
            raise ValueError(f"Unknown comparison: {baseline}={treatment}")
        common = [instance_id for instance_id in ids if instance_id in groups[baseline] and instance_id in groups[treatment]]
        values = [(groups[baseline][instance_id], groups[treatment][instance_id]) for instance_id in common]
        wins = sum(new > old for old, new in values)
        losses = sum(new < old for old, new in values)
        old_mean = sum(old for old, _ in values) / len(values)
        new_mean = sum(new for _, new in values) / len(values)
        low, high = bootstrap_ci(values, args.bootstrap_iters, args.seed)
        paired_rows.append(
            {
                "baseline": baseline,
                "treatment": treatment,
                "N": len(values),
                "top_files": args.top_files,
                "baseline_coverage": old_mean,
                "treatment_coverage": new_mean,
                "delta": new_mean - old_mean,
                "ci95_low": low,
                "ci95_high": high,
                "wins": wins,
                "losses": losses,
                "ties": len(values) - wins - losses,
                "exact_mcnemar_p": exact_mcnemar_p(wins, losses),
            }
        )

    write_tsv(args.output_summary, summary_rows, ["name", "N", "top_files", "file_hits", "file_coverage", "dir"])
    write_tsv(
        args.output_paired,
        paired_rows,
        [
            "baseline",
            "treatment",
            "N",
            "top_files",
            "baseline_coverage",
            "treatment_coverage",
            "delta",
            "ci95_low",
            "ci95_high",
            "wins",
            "losses",
            "ties",
            "exact_mcnemar_p",
        ],
    )
    print(f"wrote {args.output_summary}")
    print(f"wrote {args.output_paired}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
