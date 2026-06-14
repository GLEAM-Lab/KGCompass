#!/usr/bin/env python3
"""Build GLM-5 baseline-fusion control metrics with paired accounting."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
from pathlib import Path
from typing import Any


def load_eval_controls_module():
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        repo_root / "scripts" / "eval_controls_v3.py",
        Path(__file__).with_name("eval_controls_v3.py"),
    ]
    for script in candidates:
        if not script.exists():
            continue
        spec = importlib.util.spec_from_file_location("eval_controls_v3", script)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    raise FileNotFoundError("Cannot locate eval_controls_v3.py")


def parse_group(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise ValueError(f"Invalid group spec: {raw}")
    name, path = raw.split("=", 1)
    return name.strip(), Path(path.strip())


def exact_mcnemar_p(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    tail = min(wins, losses)
    prob = sum(math.comb(n, k) for k in range(tail + 1)) / (2**n)
    return min(1.0, 2.0 * prob)


def mrr(row: dict[str, Any]) -> float:
    rank = row.get("best_rank")
    return 0.0 if rank is None else 1.0 / float(rank)


def load_eval_rows(eval_controls: Any, ids: list[str], gt_map: dict[str, dict], group_dir: Path, top_k: int) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for iid in ids:
        path = group_dir / f"{iid}.json"
        if not path.exists():
            continue
        rows[iid] = eval_controls.evaluate_one_instance(json.loads(path.read_text()), gt_map[iid], top_k=top_k)
    return rows


def summarize(name: str, group_dir: Path, ids: list[str], issue: dict[str, dict], group: dict[str, dict]) -> dict[str, Any]:
    common = [iid for iid in ids if iid in issue and iid in group]
    if not common:
        raise ValueError(f"No overlapping instances for {name}: {group_dir}")

    issue_hit_rate = sum(issue[iid]["hit"] for iid in common) / len(common)
    file_wins = sum(1 for iid in common if group[iid]["find_file"] > issue[iid]["find_file"])
    file_losses = sum(1 for iid in common if group[iid]["find_file"] < issue[iid]["find_file"])
    hit_wins = sum(1 for iid in common if group[iid]["hit"] > issue[iid]["hit"])
    hit_losses = sum(1 for iid in common if group[iid]["hit"] < issue[iid]["hit"])
    method_wins = sum(1 for iid in common if group[iid]["ratio"] > issue[iid]["ratio"] + 1e-12)
    method_losses = sum(1 for iid in common if group[iid]["ratio"] < issue[iid]["ratio"] - 1e-12)
    mrr_wins = sum(1 for iid in common if mrr(group[iid]) > mrr(issue[iid]) + 1e-12)
    mrr_losses = sum(1 for iid in common if mrr(group[iid]) < mrr(issue[iid]) - 1e-12)
    hit_rate = sum(group[iid]["hit"] for iid in common) / len(common)

    return {
        "name": name,
        "N": len(common),
        "file_rate": sum(group[iid]["find_file"] for iid in common) / len(common),
        "method_or_entity_rate": sum(group[iid]["ratio"] for iid in common) / len(common),
        "mrr": sum(mrr(group[iid]) for iid in common) / len(common),
        "top20_hit_rate": hit_rate,
        "hit_delta_pp": (hit_rate - issue_hit_rate) * 100.0,
        "hit_wins_vs_issue": hit_wins,
        "hit_losses_vs_issue": hit_losses,
        "hit_mcnemar_p": exact_mcnemar_p(hit_wins, hit_losses),
        "method_wins_vs_issue": method_wins,
        "method_losses_vs_issue": method_losses,
        "file_wins_vs_issue": file_wins,
        "file_losses_vs_issue": file_losses,
        "mrr_wins_vs_issue": mrr_wins,
        "mrr_losses_vs_issue": mrr_losses,
        "dir": str(group_dir),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids-file", default="temp_run/SWE-bench_Verified_ids.jsonl", type=Path)
    parser.add_argument("--gt-cache", default="temp_run/output/gt_eval_cache_verified_v3_entities.json", type=Path)
    parser.add_argument("--issue-dir", required=True, type=Path)
    parser.add_argument("--group", action="append", required=True, help="name=dir; repeat for each fusion control")
    parser.add_argument("--output-tsv", required=True, type=Path)
    parser.add_argument("--top-k", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    eval_controls = load_eval_controls_module()
    ids = eval_controls.load_ids(args.ids_file)
    gt_map = eval_controls.load_or_build_gt_cache(ids, args.gt_cache)
    issue = load_eval_rows(eval_controls, ids, gt_map, args.issue_dir, args.top_k)
    if not issue:
        raise SystemExit(f"No issue-only rows loaded from {args.issue_dir}")

    rows = [summarize("GLM5_issue_only", args.issue_dir, ids, issue, issue)]
    for raw in args.group:
        name, group_dir = parse_group(raw)
        group = load_eval_rows(eval_controls, ids, gt_map, group_dir, args.top_k)
        rows.append(summarize(name, group_dir, ids, issue, group))

    args.output_tsv.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "name",
        "N",
        "file_rate",
        "method_or_entity_rate",
        "mrr",
        "top20_hit_rate",
        "hit_delta_pp",
        "hit_wins_vs_issue",
        "hit_losses_vs_issue",
        "hit_mcnemar_p",
        "method_wins_vs_issue",
        "method_losses_vs_issue",
        "file_wins_vs_issue",
        "file_losses_vs_issue",
        "mrr_wins_vs_issue",
        "mrr_losses_vs_issue",
        "dir",
    ]
    with args.output_tsv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            for key in ("file_rate", "method_or_entity_rate", "mrr", "top20_hit_rate"):
                out[key] = f"{out[key]:.6f}"
            out["hit_delta_pp"] = f"{out['hit_delta_pp']:.3f}"
            out["hit_mcnemar_p"] = f"{out['hit_mcnemar_p']:.8g}"
            writer.writerow(out)
    print(f"Saved: {args.output_tsv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
