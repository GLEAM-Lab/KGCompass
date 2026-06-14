#!/usr/bin/env python3
"""Render LaTeX-ready snippets from the clean TSE localization summaries."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path


RQ1_ORDER = [
    ("BM25_nohints", r"BM25~\cite{robertson2009probabilistic}"),
    ("DPR", r"DPR~\cite{karpukhin2020dense}"),
    ("BLUiR", r"BLUiR~\cite{saha2013improving}"),
    ("KG_clean", r"\tool"),
]

RQ2_ORDER = [
    ("Sonnet46", "Claude-4.6 Sonnet"),
    ("GLM5", "GLM-5"),
    ("Qwen3CoderNext", "Qwen3-Coder-Next"),
    ("MoonshotKimiK25", "Kimi-K2.5"),
]


def read_tsv(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    return {row["name"]: row for row in rows}


def pct(row: dict[str, str], key: str) -> float:
    return 100.0 * float(row[key])


def fmt_metric(row: dict[str, str], key: str) -> str:
    return f"{pct(row, key):.1f}"


def rel_improve(new_value: float, old_value: float) -> str:
    if old_value == 0:
        return "+inf"
    return f"+{100.0 * (new_value - old_value) / old_value:.1f}\\%"


def best_row(rows: list[tuple[str, dict[str, str]]], key: str) -> str:
    return max(rows, key=lambda item: float(item[1][key]))[0]


def render_rq1(rows: dict[str, dict[str, str]]) -> str:
    ordered = []
    for key, label in RQ1_ORDER:
        if key not in rows:
            raise KeyError(f"Missing RQ1 row: {key}")
        ordered.append((key, label, rows[key]))

    lines = []
    for key, label, row in ordered:
        metrics = [fmt_metric(row, col) for col in ("file_rate", "method_or_entity_rate", "mrr", "top20_hit_rate")]
        if key == "KG_clean":
            metrics = [r"\textbf{" + metric + "}" for metric in metrics]
        lines.append(f"{label} & {' & '.join(metrics)} \\\\")

    kg = rows["KG_clean"]
    bm25 = rows["BM25_nohints"]
    dpr = rows["DPR"]
    bluir = rows["BLUiR"]
    result = (
        "RQ1 table rows:\n"
        + "\n".join(lines)
        + "\n\nRQ1 result paragraph values:\n"
        + (
            "KG_clean: "
            f"{fmt_metric(kg, 'file_rate')}/{fmt_metric(kg, 'method_or_entity_rate')}/"
            f"{fmt_metric(kg, 'mrr')}/{fmt_metric(kg, 'top20_hit_rate')}; "
            "BM25: "
            f"{fmt_metric(bm25, 'file_rate')}/{fmt_metric(bm25, 'method_or_entity_rate')}/"
            f"{fmt_metric(bm25, 'mrr')}/{fmt_metric(bm25, 'top20_hit_rate')}; "
            "DPR: "
            f"{fmt_metric(dpr, 'file_rate')}/{fmt_metric(dpr, 'method_or_entity_rate')}/"
            f"{fmt_metric(dpr, 'mrr')}/{fmt_metric(dpr, 'top20_hit_rate')}; "
            "BLUiR: "
            f"{fmt_metric(bluir, 'file_rate')}/{fmt_metric(bluir, 'method_or_entity_rate')}/"
            f"{fmt_metric(bluir, 'mrr')}/{fmt_metric(bluir, 'top20_hit_rate')}."
        )
    )
    return result


def render_rq2(rows: dict[str, dict[str, str]]) -> str:
    lines = []
    for tag, label in RQ2_ORDER:
        issue_key = f"{tag}_issue_only"
        fusion_key = f"{tag}_KG_clean_ht10"
        if issue_key not in rows:
            raise KeyError(f"Missing RQ2 row: {issue_key}")
        if fusion_key not in rows:
            raise KeyError(f"Missing RQ2 row: {fusion_key}")
        old = rows[issue_key]
        new = rows[fusion_key]
        old_metrics = [fmt_metric(old, col) for col in ("file_rate", "method_or_entity_rate", "mrr", "top20_hit_rate")]
        new_metrics = []
        for col in ("file_rate", "method_or_entity_rate", "mrr", "top20_hit_rate"):
            old_v = pct(old, col)
            new_v = pct(new, col)
            new_metrics.append(r"\textbf{" + f"{new_v:.1f}" + r"} (" + rel_improve(new_v, old_v) + ")")
        lines.append(f"{label} & {' & '.join(old_metrics)} & {' & '.join(new_metrics)} \\\\")

    glm_old = rows["GLM5_issue_only"]
    glm_new = rows["GLM5_KG_clean_ht10"]
    return (
        "RQ2 table rows:\n"
        + "\n".join(lines)
        + "\n\nRQ2 primary GLM-5 values:\n"
        + (
            f"Method Coverage {fmt_metric(glm_old, 'method_or_entity_rate')} -> "
            f"{fmt_metric(glm_new, 'method_or_entity_rate')}; "
            f"Hit@20 {fmt_metric(glm_old, 'top20_hit_rate')} -> {fmt_metric(glm_new, 'top20_hit_rate')}."
        )
    )


def render_rq3(rq3: dict) -> str:
    path_counts = {int(k): int(v) for k, v in rq3.get("path_length_counts", {}).items()}
    rank_counts = {int(k): int(v) for k, v in rq3.get("rank_counts", {}).items()}
    type_counts = rq3.get("entity_type_counts", {})
    type_pcts = rq3.get("entity_type_percentages", {})
    path_total = int(rq3.get("path_summary", {}).get("path_observations", 0))
    rank_total = int(rq3.get("rank_summary", {}).get("rank_observations", 0))
    missed = int(rq3.get("rank_summary", {}).get("missed_observations", 0))
    direct = int(rq3.get("path_summary", {}).get("direct_paths", 0))
    direct_pct = float(rq3.get("path_summary", {}).get("direct_percent", 0.0))
    multi = int(rq3.get("path_summary", {}).get("multi_hop_paths", 0))
    multi_pct = float(rq3.get("path_summary", {}).get("multi_hop_percent", 0.0))
    top1 = int(rq3.get("rank_summary", {}).get("rank1", 0))
    top5 = int(rq3.get("rank_summary", {}).get("top5", 0))
    top10 = int(rq3.get("rank_summary", {}).get("top10", 0))
    top15 = int(rq3.get("rank_summary", {}).get("top15", 0))
    beyond15 = int(rq3.get("rank_summary", {}).get("beyond15", 0))

    path_parts = [
        f"{count} ({100.0 * count / path_total:.1f}\\%) length-{length}"
        for length, count in sorted(path_counts.items())
        if path_total
    ]
    type_parts = [
        f"{count} {name} ({float(type_pcts.get(name, 0.0)):.1f}\\%)"
        for name, count in sorted(type_counts.items(), key=lambda item: (-int(item[1]), item[0]))
    ]
    rank_line = (
        f"rank1={top1} ({100.0 * top1 / rank_total:.1f}\\%), "
        f"top5={top5} ({100.0 * top5 / rank_total:.1f}\\%), "
        f"top10={top10} ({100.0 * top10 / rank_total:.1f}\\%), "
        f"top15={top15} ({100.0 * top15 / rank_total:.1f}\\%), "
        f"beyond15={beyond15} ({100.0 * beyond15 / rank_total:.1f}\\%), "
        f"missed={missed}"
    ) if rank_total else "No positive rank observations."
    return (
        "RQ3 mechanism values:\n"
        f"Path observations={path_total}; direct={direct} ({direct_pct:.1f}\\%); "
        f"multi-hop={multi} ({multi_pct:.1f}\\%).\n"
        + "Path breakdown: "
        + "; ".join(path_parts)
        + "\nIntermediate entity types: "
        + "; ".join(type_parts)
        + "\nRank observations="
        + str(rank_total)
        + "; "
        + rank_line
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm-tsv", type=Path, required=True, help="Final LLM/KG fusion TSV from eval_controls_v3.")
    parser.add_argument("--rq3-json", type=Path, required=True, help="Final RQ3 mechanism JSON.")
    parser.add_argument("--output", type=Path, required=True, help="Output text/tex snippets path.")
    parser.add_argument("--copy-plots-to", type=Path, default=None, help="Optional paper figures directory.")
    parser.add_argument("--rq3-path-plot", type=Path, default=None)
    parser.add_argument("--rq3-rank-plot", type=Path, default=None)
    args = parser.parse_args()

    rows = read_tsv(args.llm_tsv)
    rq3 = json.loads(args.rq3_json.read_text())

    content = "\n\n".join(
        [
            "% Generated from clean TSE localization outputs. Verify before pasting into the paper.",
            render_rq1(rows),
            render_rq2(rows),
            render_rq3(rq3),
        ]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content + "\n")

    if args.copy_plots_to:
        args.copy_plots_to.mkdir(parents=True, exist_ok=True)
        if args.rq3_path_plot:
            shutil.copy2(args.rq3_path_plot, args.copy_plots_to / "pathlength.png")
        if args.rq3_rank_plot:
            shutil.copy2(args.rq3_rank_plot, args.copy_plots_to / "gt_rank.png")

    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
