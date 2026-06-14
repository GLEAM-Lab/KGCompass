#!/usr/bin/env python3
"""Verify manuscript-facing numbers from paper-side artifact ledgers.

This checker is intentionally lightweight: it reads only files committed under
artifacts/results/ and validates the quantitative values used by the final
manuscript tables and key RQ statements. It does not require the full KGCompass
experiment workspace or the large per-instance KG JSON directories.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "artifacts" / "results"


checks: list[dict[str, Any]] = []


def read_tsv(name: str) -> list[dict[str, str]]:
    path = RESULTS / name
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_json(name: str) -> Any:
    path = RESULTS / name
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(name: str) -> list[dict[str, Any]]:
    path = RESULTS / name
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def row_by(rows: list[dict[str, str]], key: str, value: str) -> dict[str, str]:
    for row in rows:
        if row.get(key) == value:
            return row
    raise AssertionError(f"row not found: {key}={value}")


def row_by_two(rows: list[dict[str, str]], key1: str, value1: str, key2: str, value2: str) -> dict[str, str]:
    for row in rows:
        if row.get(key1) == value1 and row.get(key2) == value2:
            return row
    raise AssertionError(f"row not found: {key1}={value1}, {key2}={value2}")


def pct(value: str | float) -> float:
    return float(value) * 100.0


def record(name: str, observed: Any, expected: Any, ok: bool, source: str) -> None:
    checks.append(
        {
            "name": name,
            "ok": ok,
            "observed": observed,
            "expected": expected,
            "source": source,
        }
    )


def expect_close(name: str, observed: float, expected: float, source: str, tol: float = 0.05) -> None:
    ok = math.isclose(observed, expected, abs_tol=tol)
    record(name, round(observed, 6), expected, ok, source)


def expect_equal(name: str, observed: Any, expected: Any, source: str) -> None:
    record(name, observed, expected, observed == expected, source)


def expect_match(name: str, condition: bool, source: str) -> None:
    record(name, "match" if condition else "mismatch", "match", condition, source)


def verify_rq1() -> None:
    source = "path_mining_file_expansion_ablation_20260531.tsv"
    rows = read_tsv(source)
    expected = {
        "bm25_nohint": (77.0, 39.2, 25.3, 46.0),
        "dpr_filefirst": (57.8, 40.3, 28.3, 45.4),
        "bluir": (55.6, 38.6, 28.9, 43.4),
        "no_history_codegraph": (63.6, 35.2, 22.9, 41.0),
        "strict_kg_ablation": (55.6, 33.8, 22.2, 37.8),
        "full_pathmined": (59.2, 45.4, 26.3, 50.8),
    }
    for name, values in expected.items():
        row = row_by(rows, "name", name)
        observed = (
            pct(row["file_rate"]),
            pct(row["method_or_entity_rate"]),
            pct(row["mrr"]),
            pct(row["top20_hit_rate"]),
        )
        for metric, obs, exp in zip(("file", "method", "mrr", "hit"), observed, values):
            expect_close(f"RQ1 {name} {metric}", obs, exp, source)

    paired = read_tsv("rq1_pathmined_paired_stats_20260531.tsv")
    hit = row_by_two(paired, "baseline", "strict_kg_ablation", "metric", "hit")
    expect_close("RQ1 full vs KG-reachability-only hit delta", float(hit["delta_pp"]), 13.0, "rq1_pathmined_paired_stats_20260531.tsv")
    expect_equal("RQ1 full vs KG-reachability-only hit wins", int(hit["wins"]), 67, "rq1_pathmined_paired_stats_20260531.tsv")
    expect_equal("RQ1 full vs KG-reachability-only hit losses", int(hit["losses"]), 2, "rq1_pathmined_paired_stats_20260531.tsv")


def verify_rq2() -> None:
    source = "llm_pathmined_kg_ht10_20260531.tsv"
    rows = read_tsv(source)
    expected = {
        "GLM5_issue_only": (87.4, 53.0, 51.2, 62.4),
        "GLM5_KG_pathmined_ht10": (93.4, 65.5, 53.7, 74.0),
        "Qwen3CoderNext_issue_only": (76.2, 38.8, 39.8, 46.2),
        "Qwen3CoderNext_KG_pathmined_ht10": (86.8, 56.5, 43.7, 63.6),
        "MoonshotKimiK25_issue_only": (51.6, 36.8, 38.0, 41.8),
        "MoonshotKimiK25_KG_pathmined_ht10": (76.4, 57.5, 46.8, 64.4),
        "Sonnet46_issue_only": (82.6, 58.9, 57.7, 68.6),
        "Sonnet46_KG_pathmined_ht10": (90.6, 70.0, 61.0, 78.4),
    }
    for name, values in expected.items():
        row = row_by(rows, "name", name)
        observed = (
            pct(row["file_rate"]),
            pct(row["method_or_entity_rate"]),
            pct(row["mrr"]),
            pct(row["top20_hit_rate"]),
        )
        for metric, obs, exp in zip(("file", "method", "mrr", "hit"), observed, values):
            expect_close(f"RQ2 {name} {metric}", obs, exp, source)

    paired = read_tsv("tse_paired_stats_pathmined_20260531.tsv")
    hit = row_by(paired, "metric", "Hit@20")
    expect_close("RQ2 GLM5 Hit@20 delta", float(hit["delta"]), 11.6, "tse_paired_stats_pathmined_20260531.tsv")
    expect_equal("RQ2 GLM5 Hit@20 wins", int(hit["wins"]), 58, "tse_paired_stats_pathmined_20260531.tsv")
    expect_equal("RQ2 GLM5 Hit@20 losses", int(hit["losses"]), 0, "tse_paired_stats_pathmined_20260531.tsv")

    comp = read_json("glm5_pathmined_kg_complementarity_20260531.json")
    expect_equal("RQ2 GLM5/KG union ceiling", comp["kg_only_vs_glm_issue_only"]["union_hit_ceiling"], 376, "glm5_pathmined_kg_complementarity_20260531.json")
    expect_equal("RQ2 fixed 10+10 fusion hits", comp["top20_hit"]["llm_kg_hit"], 370, "glm5_pathmined_kg_complementarity_20260531.json")

    qwen = read_tsv("qwen25_32b_kgcompass_fusion_20260601.tsv")
    cosil = row_by(qwen, "name", "CoSIL-Qwen2.5-32B")
    cosil_kg = row_by(qwen, "name", "CoSIL-Qwen2.5-32B+KGCompass")
    expect_close("RQ2 CoSIL-Qwen2.5-32B method", pct(cosil["method_or_entity_rate"]), 55.9, "qwen25_32b_kgcompass_fusion_20260601.tsv")
    expect_close("RQ2 CoSIL-Qwen2.5-32B+KG method", pct(cosil_kg["method_or_entity_rate"]), 65.8, "qwen25_32b_kgcompass_fusion_20260601.tsv")
    expect_close("RQ2 CoSIL-Qwen2.5-32B hit", pct(cosil["top20_hit_rate"]), 65.6, "qwen25_32b_kgcompass_fusion_20260601.tsv")
    expect_close("RQ2 CoSIL-Qwen2.5-32B+KG hit", pct(cosil_kg["top20_hit_rate"]), 74.6, "qwen25_32b_kgcompass_fusion_20260601.tsv")

    local = read_tsv("local_open_models_pathmined_top10_5p5_summary.tsv")
    expect_close("RQ2 Qwen3-Coder-30B issue Hit@10", pct(row_by(local, "name", "LocalQwen3Coder30B_issue_top10")["top20_hit_rate"]), 30.0, "local_open_models_pathmined_top10_5p5_summary.tsv")
    expect_close("RQ2 Qwen3-Coder-30B+KG Hit@10", pct(row_by(local, "name", "LocalQwen3Coder30B_KG_pathmined_5p5")["top20_hit_rate"]), 46.6, "local_open_models_pathmined_top10_5p5_summary.tsv")
    expect_close("RQ2 DeepSeek-Coder-V2-Lite issue Hit@10", pct(row_by(local, "name", "LocalDeepSeekCoderV2Lite_issue_top10")["top20_hit_rate"]), 15.6, "local_open_models_pathmined_top10_5p5_summary.tsv")
    expect_close("RQ2 DeepSeek-Coder-V2-Lite+KG Hit@10", pct(row_by(local, "name", "LocalDeepSeekCoderV2Lite_KG_pathmined_5p5")["top20_hit_rate"]), 45.0, "local_open_models_pathmined_top10_5p5_summary.tsv")


def verify_rq3() -> None:
    rq3 = read_json("kg_clean_tse_timesafe_main_20260529_v6_rq3.json")
    expect_equal("RQ3 KG-reachability-only method hits", rq3["method_hit_instances"], 189, "kg_clean_tse_timesafe_main_20260529_v6_rq3.json")
    expect_equal("RQ3 KG-reachability-only path observations", rq3["path_summary"]["path_observations"], 252, "kg_clean_tse_timesafe_main_20260529_v6_rq3.json")
    expect_equal("RQ3 length-2 paths", rq3["path_length_counts"]["2"], 251, "kg_clean_tse_timesafe_main_20260529_v6_rq3.json")

    rows = read_tsv("path_mining_full500_summary.tsv")
    full = row_by(rows, "name", "pathunion_v1")
    strict = row_by(rows, "name", "kg_clean")
    full_hits = round(float(full["top20_hit_rate"]) * 500)
    strict_hits = round(float(strict["top20_hit_rate"]) * 500)
    expect_equal("RQ3 full path-mined hits", full_hits, 254, "path_mining_full500_summary.tsv")
    expect_equal("RQ3 KG-reachability-only hits", strict_hits, 189, "path_mining_full500_summary.tsv")
    expect_equal("RQ3 net Hit@20 increase", full_hits - strict_hits, 65, "path_mining_full500_summary.tsv")

    paired = read_tsv("rq1_pathmined_paired_stats_20260531.tsv")
    hit = row_by_two(paired, "baseline", "strict_kg_ablation", "metric", "hit")
    paired_wins = int(hit["wins"])
    paired_losses = int(hit["losses"])
    expect_equal("RQ3 paired wins over KG-reachability-only", paired_wins, 67, "rq1_pathmined_paired_stats_20260531.tsv")
    expect_equal("RQ3 paired losses over KG-reachability-only", paired_losses, 2, "rq1_pathmined_paired_stats_20260531.tsv")
    expect_equal("RQ3 paired wins minus losses equals net gain", paired_wins - paired_losses, 65, "rq1_pathmined_paired_stats_20260531.tsv")

    snippets = (RESULTS / "clean_tse_tse_timesafe_main_20260529_v6_latex_snippets.tex").read_text(encoding="utf-8")
    match = re.search(r"recovered from strict-KG miss=(\d+); recovered path lengths: (\d+) length-2, (\d+) length-3", snippets)
    if not match:
        raise AssertionError("RQ3 recovered path-length snippet not found")
    recovered, length2, length3 = map(int, match.groups())
    expect_equal("RQ3 recovered wins with path-length accounting", recovered, 67, "clean_tse_tse_timesafe_main_20260529_v6_latex_snippets.tex")
    expect_equal("RQ3 recovered length-3 wins", length3, 55, "clean_tse_tse_timesafe_main_20260529_v6_latex_snippets.tex")

    path_observations = read_tsv("rq3_path_audit_observations_20260614.tsv")
    rank_observations = read_tsv("rq3_rank_audit_observations_20260614.tsv")
    expect_equal("RQ3 path audit observation rows", len(path_observations), 320, "rq3_path_audit_observations_20260614.tsv")
    expect_equal("RQ3 rank audit observation rows", len(rank_observations), 320, "rq3_rank_audit_observations_20260614.tsv")
    expect_equal(
        "RQ3 path audit outcome universe",
        dict(Counter(row["outcome"] for row in path_observations)),
        {"correct": 116, "wrong": 204},
        "rq3_path_audit_observations_20260614.tsv",
    )
    expect_equal(
        "RQ3 rank audit outcome universe",
        dict(Counter(row["outcome"] for row in rank_observations)),
        {"correct": 116, "wrong": 204},
        "rq3_rank_audit_observations_20260614.tsv",
    )
    path_lengths = Counter((row["outcome"], row["path_length"]) for row in path_observations)
    expect_equal("RQ3 path audit correct non-null", sum(path_lengths[("correct", str(length))] for length in range(1, 5)), 100, "rq3_path_audit_observations_20260614.tsv")
    expect_equal("RQ3 path audit wrong non-null", sum(path_lengths[("wrong", str(length))] for length in range(1, 5)), 108, "rq3_path_audit_observations_20260614.tsv")
    rank_top5 = Counter((row["outcome"], row["top5"]) for row in rank_observations)
    expect_equal("RQ3 rank audit correct top5 count", rank_top5[("correct", "1")], 82, "rq3_rank_audit_observations_20260614.tsv")
    expect_equal("RQ3 rank audit wrong top5 count", rank_top5[("wrong", "1")], 79, "rq3_rank_audit_observations_20260614.tsv")

    path_audit = read_tsv("path_availability_audit_20260613.tsv")
    path_test = row_by(path_audit, "kind", "test")
    expect_equal("RQ3 path/rank audit universe", int(path_test["count"]), 320, "path_availability_audit_20260613.tsv")
    expect_close("RQ3 path audit chi-square", float(path_test["value"]), 35.970845, "path_availability_audit_20260613.tsv", tol=1e-6)

    rank_audit = read_tsv("rank_availability_audit_20260613.tsv")
    correct_top5 = row_by_two(rank_audit, "outcome", "correct", "rank_bucket", "top5")
    wrong_top5 = row_by_two(rank_audit, "outcome", "wrong", "rank_bucket", "top5")
    expect_close("RQ3 correct Top-5 rank rate", pct(correct_top5["rate"]), 70.7, "rank_availability_audit_20260613.tsv")
    expect_close("RQ3 wrong Top-5 rank rate", pct(wrong_top5["rate"]), 38.7, "rank_availability_audit_20260613.tsv")


def verify_rq4_and_boundary() -> None:
    rows = read_tsv("claudecode_context_probe_glm5_20260531.tsv")
    no_kg = row_by_two(rows, "slice", "full500", "context", "noKG")
    kg = row_by_two(rows, "slice", "full500", "context", "KGCompass")
    for label, row, expected in [
        ("RQ4 issue-only nonempty", no_kg, 425),
        ("RQ4 issue-only applied", no_kg, 412),
        ("RQ4 issue-only resolved", no_kg, 266),
        ("RQ4 KG nonempty", kg, 460),
        ("RQ4 KG applied", kg, 446),
        ("RQ4 KG resolved", kg, 289),
    ]:
        column = label.split()[-1]
        field = {"nonempty": "nonempty_patches", "applied": "applied_patches", "resolved": "resolved"}[column]
        expect_equal(label, int(row[field]), expected, "claudecode_context_probe_glm5_20260531.tsv")

    paired = read_json("claudecode_context_probe_glm5_20260531/paired_stats.json")
    full = paired["full500"]
    expect_equal("RQ4 paired wins", full["wins"], 41, "claudecode_context_probe_glm5_20260531/paired_stats.json")
    expect_equal("RQ4 paired losses", full["losses"], 18, "claudecode_context_probe_glm5_20260531/paired_stats.json")
    expect_close("RQ4 exact McNemar p", float(full["exact_mcnemar_p"]), 0.0037937056353716074, "claudecode_context_probe_glm5_20260531/paired_stats.json", tol=1e-15)

    rq4_dir = "claudecode_context_probe_glm5_20260531"
    for context in ("nokg", "kg"):
        first100 = read_jsonl(f"{rq4_dir}/first100_{context}_official_results.jsonl")
        remaining400 = read_jsonl(f"{rq4_dir}/remaining400_{context}_official_results.jsonl")
        full500 = read_jsonl(f"{rq4_dir}/full500_{context}_official_results.jsonl")
        source = f"{rq4_dir}/full500_{context}_official_results.jsonl"
        expect_equal(f"RQ4 {context} full500 row count", len(full500), 500, source)
        expect_equal(f"RQ4 {context} first100 row count", len(first100), 100, f"{rq4_dir}/first100_{context}_official_results.jsonl")
        expect_equal(f"RQ4 {context} remaining400 row count", len(remaining400), 400, f"{rq4_dir}/remaining400_{context}_official_results.jsonl")
        expect_match(f"RQ4 {context} full500 is first100 plus remaining400", full500 == first100 + remaining400, source)

    audit = read_json("kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json")["summary"]
    expect_equal("Boundary audit ok instances", audit["ok"], 500, "kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json")
    expect_equal("Boundary audit target PR hits", audit["target_pr_hits"], 0, "kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json")
    expect_equal("Boundary audit future-fix hits", audit["future_fix_trace_hits"], 0, "kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json")
    expect_equal("Boundary audit content issue counts", audit["content_issue_counts"], {}, "kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json")
    expect_equal("Boundary audit warning count", audit["warning_content_issue_counts"].get("generic_fixed_issue_reference"), 5, "kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json")

    sensitivity = read_tsv("time_boundary_external_artifact_sensitivity_20260531.tsv")
    full_row = row_by(sensitivity, "setting", "full_pathmined")
    expect_equal("External artifact sensitivity instances", int(full_row["external_instances"]), 1, "time_boundary_external_artifact_sensitivity_20260531.tsv")
    expect_equal("External artifact sensitivity Top-20 candidates", int(full_row["external_top20_candidates"]), 2, "time_boundary_external_artifact_sensitivity_20260531.tsv")
    expect_equal("External artifact sensitivity Hit@20 losses", int(full_row["hit_losses"]), 0, "time_boundary_external_artifact_sensitivity_20260531.tsv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify manuscript-facing KGCompass artifact values."
    )
    parser.add_argument(
        "--rq",
        choices=("all", "rq1", "rq2", "rq3", "rq4"),
        default="all",
        help="Restrict checks to one research question. Default: all.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_checks = {
        "rq1": verify_rq1,
        "rq2": verify_rq2,
        "rq3": verify_rq3,
        "rq4": verify_rq4_and_boundary,
    }
    try:
        if args.rq == "all":
            for check in selected_checks.values():
                check()
        else:
            selected_checks[args.rq]()
    except Exception as exc:  # noqa: BLE001 - reviewer-facing script should print context.
        print(json.dumps({"ok": False, "error": str(exc), "checks": checks}, indent=2), file=sys.stderr)
        return 1

    failed = [item for item in checks if not item["ok"]]
    report = {
        "ok": not failed,
        "scope": args.rq,
        "checked_values": len(checks),
        "failed": failed,
        "checks": checks,
    }
    print(json.dumps(report, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
