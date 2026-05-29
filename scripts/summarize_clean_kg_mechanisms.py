#!/usr/bin/env python3
"""Summarize KG localization mechanism statistics from calc_prefl cache."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _add_counts(target: dict[int, int], raw_counts: dict) -> None:
    for raw_key, raw_value in (raw_counts or {}).items():
        try:
            key = int(raw_key)
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        target[key] = target.get(key, 0) + value


def _add_type_counts(target: dict[str, int], raw_counts: dict) -> None:
    for raw_key, raw_value in (raw_counts or {}).items():
        if raw_key is None:
            continue
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        key = str(raw_key)
        target[key] = target.get(key, 0) + value


def _percent(count: int, total: int) -> float:
    return (100.0 * count / total) if total else 0.0


def summarize(cache_file: Path) -> dict:
    included_instances = 0
    ok_instances = 0
    file_hits = 0
    method_hits = 0
    rank_counts: dict[int, int] = {}
    path_length_counts: dict[int, int] = {}
    entity_type_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}

    with cache_file.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            status = entry.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            if not entry.get("tot_included"):
                continue
            included_instances += 1
            if status == "ok":
                ok_instances += 1
            file_hits += int(entry.get("find_file", 0) or 0)
            method_hits += int(entry.get("morethanone", 0) or 0)
            _add_counts(rank_counts, entry.get("ranks", {}))
            _add_counts(path_length_counts, entry.get("lengths", {}))
            _add_type_counts(entity_type_counts, entry.get("type_cnt", {}))

    positive_rank_counts = {rank: count for rank, count in rank_counts.items() if rank > 0}
    rank_observations = sum(positive_rank_counts.values())
    missed_observations = rank_counts.get(0, 0)
    path_observations = sum(path_length_counts.values())
    entity_observations = sum(entity_type_counts.values())
    direct_paths = path_length_counts.get(1, 0)
    multi_hop_paths = sum(count for length, count in path_length_counts.items() if length > 1)
    top1 = positive_rank_counts.get(1, 0)
    top5 = sum(count for rank, count in positive_rank_counts.items() if rank <= 5)
    top10 = sum(count for rank, count in positive_rank_counts.items() if rank <= 10)
    top15 = sum(count for rank, count in positive_rank_counts.items() if rank <= 15)
    beyond15 = sum(count for rank, count in positive_rank_counts.items() if rank > 15)

    return {
        "cache_file": str(cache_file),
        "included_instances": included_instances,
        "ok_instances": ok_instances,
        "file_hit_instances": file_hits,
        "method_hit_instances": method_hits,
        "status_counts": status_counts,
        "rank_counts": {str(k): rank_counts[k] for k in sorted(rank_counts)},
        "path_length_counts": {str(k): path_length_counts[k] for k in sorted(path_length_counts)},
        "entity_type_counts": dict(sorted(entity_type_counts.items())),
        "rank_summary": {
            "rank_observations": rank_observations,
            "missed_observations": missed_observations,
            "rank1": top1,
            "rank1_percent": _percent(top1, rank_observations),
            "top5": top5,
            "top5_percent": _percent(top5, rank_observations),
            "top10": top10,
            "top10_percent": _percent(top10, rank_observations),
            "top15": top15,
            "top15_percent": _percent(top15, rank_observations),
            "beyond15": beyond15,
            "beyond15_percent": _percent(beyond15, rank_observations),
        },
        "path_summary": {
            "path_observations": path_observations,
            "direct_paths": direct_paths,
            "direct_percent": _percent(direct_paths, path_observations),
            "multi_hop_paths": multi_hop_paths,
            "multi_hop_percent": _percent(multi_hop_paths, path_observations),
        },
        "entity_type_percentages": {
            key: _percent(value, entity_observations)
            for key, value in sorted(entity_type_counts.items())
        },
    }


def write_tsv(summary: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        fh.write("section\tkey\tcount\tpercent\n")
        path_total = summary["path_summary"]["path_observations"]
        for key, value in summary["path_length_counts"].items():
            fh.write(f"path_length\t{key}\t{value}\t{_percent(int(value), path_total):.6f}\n")
        rank_total = summary["rank_summary"]["rank_observations"]
        for key, value in summary["rank_counts"].items():
            percent = "" if int(key) == 0 else f"{_percent(int(value), rank_total):.6f}"
            fh.write(f"rank\t{key}\t{value}\t{percent}\n")
        entity_total = sum(summary["entity_type_counts"].values())
        for key, value in summary["entity_type_counts"].items():
            fh.write(f"entity_type\t{key}\t{value}\t{_percent(int(value), entity_total):.6f}\n")


def write_plots(summary: dict, path_plot: Path | None, rank_plot: Path | None) -> None:
    if not path_plot and not rank_plot:
        return
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if path_plot:
        path_plot.parent.mkdir(parents=True, exist_ok=True)
        counts = {int(k): int(v) for k, v in summary["path_length_counts"].items()}
        xs = sorted(counts)
        ys = [counts[x] for x in xs]
        plt.figure(figsize=(4.8, 3.2))
        plt.bar([str(x) for x in xs], ys, color="#4C78A8")
        plt.xlabel("KG path length")
        plt.ylabel("Ground-truth hits")
        plt.tight_layout()
        plt.savefig(path_plot, dpi=240)
        plt.close()

    if rank_plot:
        rank_plot.parent.mkdir(parents=True, exist_ok=True)
        counts = {int(k): int(v) for k, v in summary["rank_counts"].items() if int(k) > 0}
        xs = list(range(1, 21))
        ys = [counts.get(x, 0) for x in xs]
        plt.figure(figsize=(5.6, 3.2))
        plt.bar([str(x) for x in xs], ys, color="#59A14F")
        plt.xlabel("Rank in Top-20")
        plt.ylabel("Ground-truth hits")
        plt.tight_layout()
        plt.savefig(rank_plot, dpi=240)
        plt.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache_file", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-tsv", type=Path, default=None)
    parser.add_argument("--path-plot", type=Path, default=None)
    parser.add_argument("--rank-plot", type=Path, default=None)
    args = parser.parse_args()

    summary = summarize(args.cache_file)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    if args.output_tsv:
        write_tsv(summary, args.output_tsv)
    write_plots(summary, args.path_plot, args.rank_plot)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
