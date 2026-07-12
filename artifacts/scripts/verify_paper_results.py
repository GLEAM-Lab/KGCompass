#!/usr/bin/env python3
"""Verify manuscript-facing numbers from paper-side artifact ledgers.

This checker reads only committed files under artifacts/results/ and validates
the quantitative values used by the current KGCompass manuscript. It also
checks that the result directory does not contain unreported legacy ledgers.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "artifacts" / "results"

EXPECTED_RESULT_FILES = {
    "claudecode_context_probe_glm5_20260531.tsv",
    "claudecode_context_probe_glm5_20260531/full500_kg_official_results.jsonl",
    "claudecode_context_probe_glm5_20260531/full500_kg_summary.json",
    "claudecode_context_probe_glm5_20260531/full500_nokg_official_results.jsonl",
    "claudecode_context_probe_glm5_20260531/full500_nokg_summary.json",
    "claudecode_context_probe_glm5_20260531/paired_stats.json",
    "claudecode_context_probe_glm5_20260531/rq4_case_sphinx_10673.json",
    "external_verified_loc_baselines_cosil_release_20260601.tsv",
    "glm5_baseline_fusion_controls_top10_20260614.tsv",
    "glm5_pathmined_kg_complementarity_20260531.json",
    "glm5_pathmined_kg_complementarity_20260531.tsv",
    "glm5_pathmined_rescued_instances_20260531.tsv",
    "kg_clean_tse_timesafe_main_20260529_v6_rq3.json",
    "kg_clean_tse_timesafe_main_20260529_v6_rq3.tsv",
    "kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json",
    "llm_pathmined_kg_ht10_20260531.tsv",
    "local_open_models_pathmined_top10_5p5_summary.tsv",
    "path_mining_file_expansion_ablation_20260531.tsv",
    "path_mining_full500_summary.tsv",
    "patch_derived_context_summary_20260702.json",
    "patch_derived_context_summary_20260702.tsv",
    "patch_derived_context_targets_20260702.json",
    "qwen25_32b_kgcompass_fusion_20260601.tsv",
    "ranked_file_source_coverage_20260711.tsv",
    "ranked_file_source_paired_20260711.tsv",
    "retrieve_then_localize_budget_curve_20260711.tsv",
    "retrieve_then_localize_budget_paired_20260711.tsv",
    "retrieve_then_localize_disagreements_20260711.tsv",
    "retrieve_then_localize_paired_20260711.tsv",
    "retrieve_then_localize_top20_20260711.tsv",
    "rq1_pathmined_paired_stats_20260531.tsv",
    "rq3_file_local_path_mining_summary.tsv",
    "time_boundary_external_artifact_sensitivity_20260531.tsv",
    "tse_gt_mapping_v6.tsv",
    "tse_paired_stats_pathmined_20260531.tsv",
}

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
    rows: list[dict[str, Any]] = []
    with (RESULTS / name).open(encoding="utf-8") as handle:
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
    record(name, round(observed, 6), expected, math.isclose(observed, expected, abs_tol=tol), source)


def expect_equal(name: str, observed: Any, expected: Any, source: str) -> None:
    record(name, observed, expected, observed == expected, source)


def expect_row_set(name: str, rows: list[dict[str, str]], key: str, expected: list[str], source: str) -> None:
    observed = [row[key] for row in rows]
    expect_equal(name, observed, expected, source)


def expect_metric_row(source: str, row: dict[str, str], expected: tuple[float, float, float, float], prefix: str) -> None:
    observed = (
        pct(row["file_rate"]),
        pct(row["method_or_entity_rate"]),
        pct(row["mrr"]),
        pct(row.get("top20_hit_rate", row.get("hit@20", row.get("hit_rate", "nan")))),
    )
    for metric, obs, exp in zip(("file", "method", "mrr", "hit"), observed, expected):
        expect_close(f"{prefix} {metric}", obs, exp, source)


def verify_result_inventory() -> None:
    observed = {
        str(path.relative_to(RESULTS)).replace("\\", "/")
        for path in RESULTS.rglob("*")
        if path.is_file()
    }
    expect_equal(
        "Paper-facing result file inventory",
        sorted(observed),
        sorted(EXPECTED_RESULT_FILES),
        "artifacts/results",
    )


def verify_setup() -> None:
    source = "tse_gt_mapping_v6.tsv"
    rows = read_tsv(source)
    expected = {
        "single_file": (429, 85.8),
        "multi_file": (71, 14.2),
        "has_method_target": (473, 94.6),
        "has_class_target": (66, 13.2),
        "single_entity": (350, 70.0),
        "multi_entity": (150, 30.0),
        "file_only_fallback": (9, 1.8),
    }
    for category, (count, percent) in expected.items():
        row = row_by(rows, "category", category)
        expect_equal(f"GT mapping {category} count", int(float(row["count"])), count, source)
        expect_close(f"GT mapping {category} percent", float(row["percent"]), percent, source)


def verify_rq1() -> None:
    source = "path_mining_file_expansion_ablation_20260531.tsv"
    rows = read_tsv(source)
    expected_rows = [
        "bm25_nohint",
        "bluir",
        "no_history_codegraph",
        "strict_kg_ablation",
        "full_pathmined",
    ]
    expect_row_set("RQ1/RQ3 controlled row set", rows, "name", expected_rows, source)
    expected = {
        "bm25_nohint": (77.0, 39.2, 25.3, 46.0),
        "bluir": (55.6, 38.6, 28.9, 43.4),
        "no_history_codegraph": (63.6, 35.2, 22.9, 41.0),
        "strict_kg_ablation": (55.6, 33.8, 22.2, 37.8),
        "full_pathmined": (59.2, 45.4, 26.3, 50.8),
    }
    for name, values in expected.items():
        expect_metric_row(source, row_by(rows, "name", name), values, f"RQ1 {name}")

    paired_source = "rq1_pathmined_paired_stats_20260531.tsv"
    paired = read_tsv(paired_source)
    expect_equal(
        "RQ1 paired baseline set",
        sorted({row["baseline"] for row in paired}),
        ["strict_kg_ablation"],
        paired_source,
    )
    method = row_by_two(paired, "baseline", "strict_kg_ablation", "metric", "method")
    hit = row_by_two(paired, "baseline", "strict_kg_ablation", "metric", "hit")
    expect_close("RQ1 method delta vs without file-local paths", float(method["delta_pp"]), 11.652, paired_source)
    expect_close("RQ1 hit delta vs without file-local paths", float(hit["delta_pp"]), 13.0, paired_source)
    expect_equal("RQ1 hit wins vs without file-local paths", int(hit["wins"]), 67, paired_source)
    expect_equal("RQ1 hit losses vs without file-local paths", int(hit["losses"]), 2, paired_source)

    verify_retrieve_then_localize_controls()


def verify_retrieve_then_localize_controls() -> None:
    file_source = "ranked_file_source_coverage_20260711.tsv"
    file_rows = read_tsv(file_source)
    expect_row_set(
        "Ranked file-source row set",
        file_rows,
        "name",
        ["KG_grounded_files", "BM25_ranked_files"],
        file_source,
    )
    for name, hits, coverage in [
        ("KG_grounded_files", 291, 58.2),
        ("BM25_ranked_files", 402, 80.4),
    ]:
        row = row_by(file_rows, "name", name)
        expect_equal(f"Ranked file source {name} hits", int(row["file_hits"]), hits, file_source)
        expect_close(f"Ranked file source {name} coverage", pct(row["file_coverage"]), coverage, file_source)

    file_paired_source = "ranked_file_source_paired_20260711.tsv"
    file_paired = read_tsv(file_paired_source)[0]
    expect_close("Ranked file source BM25-KG delta", pct(file_paired["delta"]), 22.2, file_paired_source)
    expect_equal("Ranked file source BM25 wins", int(file_paired["wins"]), 144, file_paired_source)
    expect_equal("Ranked file source BM25 losses", int(file_paired["losses"]), 33, file_paired_source)
    expect_close(
        "Ranked file source exact p",
        float(file_paired["exact_mcnemar_p"]),
        9.79369029978302e-18,
        file_paired_source,
        tol=1e-20,
    )

    source = "retrieve_then_localize_top20_20260711.tsv"
    rows = read_tsv(source)
    expected_rows = [
        "BM25",
        "KG_grounded",
        "BM25_filelocal",
        "KG_filelocal",
        "BM25_KG_RRF_filelocal",
        "GLM5_issue",
        "GLM5_KG_filelocal",
        "GLM5_BM25_filelocal",
        "GLM5_BM25_KG_RRF_filelocal",
    ]
    expect_row_set("Retrieve-then-localize Top-20 row set", rows, "name", expected_rows, source)
    expected = {
        "BM25": (77.0, 39.2, 25.3, 46.0),
        "KG_grounded": (55.6, 33.8, 22.2, 37.8),
        "BM25_filelocal": (73.6, 50.1, 28.6, 57.0),
        "KG_filelocal": (59.2, 45.4, 26.3, 50.8),
        "BM25_KG_RRF_filelocal": (77.0, 55.3, 32.0, 62.8),
        "GLM5_issue": (87.4, 53.0, 51.2, 62.4),
        "GLM5_KG_filelocal": (93.2, 65.5, 53.7, 74.0),
        "GLM5_BM25_filelocal": (94.2, 69.2, 54.4, 78.0),
        "GLM5_BM25_KG_RRF_filelocal": (94.6, 70.9, 54.7, 79.0),
    }
    for name, values in expected.items():
        expect_metric_row(source, row_by(rows, "name", name), values, f"Retrieve/localize {name}")

    paired_source = "retrieve_then_localize_paired_20260711.tsv"
    paired = read_tsv(paired_source)
    comparisons = {
        ("BM25", "BM25_filelocal"): (11.0, 100, 45, 5.72317416461909e-06),
        ("KG_grounded", "KG_filelocal"): (13.0, 67, 2, 8.185726402265558e-18),
        ("KG_filelocal", "BM25_filelocal"): (6.2, 90, 59, 0.013712033079849216),
        ("BM25_filelocal", "BM25_KG_RRF_filelocal"): (5.8, 43, 14, 0.00015388902244434233),
        ("KG_filelocal", "BM25_KG_RRF_filelocal"): (12.0, 80, 20, 1.1159089057251951e-09),
        ("GLM5_issue", "GLM5_KG_filelocal"): (11.6, 58, 0, 6.938893903907228e-18),
        ("GLM5_issue", "GLM5_BM25_filelocal"): (15.6, 78, 0, 6.617444900424222e-24),
        ("GLM5_issue", "GLM5_BM25_KG_RRF_filelocal"): (16.6, 83, 0, 2.0679515313825692e-25),
        ("GLM5_KG_filelocal", "GLM5_BM25_filelocal"): (4.0, 39, 19, 0.011928139715763175),
        ("GLM5_BM25_filelocal", "GLM5_BM25_KG_RRF_filelocal"): (1.0, 17, 12, 0.45825831964612007),
        ("GLM5_KG_filelocal", "GLM5_BM25_KG_RRF_filelocal"): (5.0, 31, 6, 4.12575900554657e-05),
    }
    for (baseline, treatment), (delta, wins, losses, p_value) in comparisons.items():
        row = next(
            item
            for item in paired
            if item["baseline"] == baseline and item["treatment"] == treatment and item["metric"] == "hit"
        )
        prefix = f"Retrieve/localize {baseline}->{treatment}"
        expect_close(f"{prefix} Hit delta", pct(row["delta"]), delta, paired_source)
        expect_equal(f"{prefix} wins", int(row["wins"]), wins, paired_source)
        expect_equal(f"{prefix} losses", int(row["losses"]), losses, paired_source)
        expect_close(f"{prefix} exact p", float(row["exact_mcnemar_p"]), p_value, paired_source, tol=1e-15)

    budget_source = "retrieve_then_localize_budget_curve_20260711.tsv"
    budget_rows = read_tsv(budget_source)
    expected_hits = {
        "GLM5_issue_b5": 60.4,
        "GLM5_KG_filelocal_b5": 65.0,
        "GLM5_BM25_filelocal_b5": 66.2,
        "GLM5_BM25_KG_RRF_b5": 66.6,
        "GLM5_issue_b10": 62.4,
        "GLM5_KG_filelocal_b10": 70.0,
        "GLM5_BM25_filelocal_b10": 72.4,
        "GLM5_BM25_KG_RRF_b10": 73.4,
        "GLM5_issue_b20": 62.4,
        "GLM5_KG_filelocal_b20": 74.0,
        "GLM5_BM25_filelocal_b20": 78.0,
        "GLM5_BM25_KG_RRF_b20": 79.0,
        "GLM5_issue_b40": 62.4,
        "GLM5_KG_filelocal_b40": 76.8,
        "GLM5_BM25_filelocal_b40": 81.6,
        "GLM5_BM25_KG_RRF_b40": 83.8,
    }
    expect_row_set("Retrieve/localize budget row set", budget_rows, "name", list(expected_hits), budget_source)
    for name, expected_hit in expected_hits.items():
        expect_close(
            f"Retrieve/localize budget {name} Hit",
            pct(row_by(budget_rows, "name", name)["hit_rate"]),
            expected_hit,
            budget_source,
        )

    budget_paired_source = "retrieve_then_localize_budget_paired_20260711.tsv"
    budget_paired = read_tsv(budget_paired_source)
    b40_hybrid = next(
        row
        for row in budget_paired
        if row["baseline"] == "GLM5_BM25_filelocal_b40"
        and row["treatment"] == "GLM5_BM25_KG_RRF_b40"
        and row["metric"] == "hit"
    )
    expect_close("Hybrid B40 Hit delta over BM25", pct(b40_hybrid["delta"]), 2.2, budget_paired_source)
    expect_equal("Hybrid B40 Hit wins over BM25", int(b40_hybrid["wins"]), 17, budget_paired_source)
    expect_equal("Hybrid B40 Hit losses over BM25", int(b40_hybrid["losses"]), 6, budget_paired_source)
    expect_close(
        "Hybrid B40 exact p over BM25",
        float(b40_hybrid["exact_mcnemar_p"]),
        0.03468966484069824,
        budget_paired_source,
        tol=1e-15,
    )

    disagreement_source = "retrieve_then_localize_disagreements_20260711.tsv"
    disagreements = read_tsv(disagreement_source)
    key_rows = [
        row
        for row in disagreements
        if row["baseline"] == "GLM5_KG_filelocal" and row["treatment"] == "GLM5_BM25_filelocal"
    ]
    expect_equal("Retrieve/localize KG-vs-BM25 disagreement count", len(key_rows), 58, disagreement_source)
    expect_equal(
        "Retrieve/localize KG-vs-BM25 treatment-only count",
        sum(row["direction"] == "treatment_only" for row in key_rows),
        39,
        disagreement_source,
    )
    expect_equal(
        "Retrieve/localize KG-vs-BM25 baseline-only count",
        sum(row["direction"] == "baseline_only" for row in key_rows),
        19,
        disagreement_source,
    )


def verify_rq2() -> None:
    source = "llm_pathmined_kg_ht10_20260531.tsv"
    rows = read_tsv(source)
    expected_rows = [
        "Sonnet46_issue_only",
        "Sonnet46_KG_pathmined_ht10",
        "GLM5_issue_only",
        "GLM5_KG_pathmined_ht10",
        "Qwen3CoderNext_issue_only",
        "Qwen3CoderNext_KG_pathmined_ht10",
        "MoonshotKimiK25_issue_only",
        "MoonshotKimiK25_KG_pathmined_ht10",
        "KGCompass",
    ]
    expect_row_set("RQ2 LLM row set", rows, "name", expected_rows, source)
    expected = {
        "Sonnet46_issue_only": (82.6, 58.9, 57.7, 68.6),
        "Sonnet46_KG_pathmined_ht10": (90.6, 70.0, 61.0, 78.4),
        "GLM5_issue_only": (87.4, 53.0, 51.2, 62.4),
        "GLM5_KG_pathmined_ht10": (93.4, 65.5, 53.7, 74.0),
        "Qwen3CoderNext_issue_only": (76.2, 38.8, 39.8, 46.2),
        "Qwen3CoderNext_KG_pathmined_ht10": (86.8, 56.5, 43.7, 63.6),
        "MoonshotKimiK25_issue_only": (51.6, 36.8, 38.0, 41.8),
        "MoonshotKimiK25_KG_pathmined_ht10": (76.4, 57.5, 46.8, 64.4),
        "KGCompass": (59.2, 45.4, 26.3, 50.8),
    }
    for name, values in expected.items():
        expect_metric_row(source, row_by(rows, "name", name), values, f"RQ2 {name}")

    controls_source = "glm5_baseline_fusion_controls_top10_20260614.tsv"
    controls = read_tsv(controls_source)
    control_rows = [
        "GLM5_issue_only",
        "GLM5_CodeGraph_ht10",
        "GLM5_KGCompass_ht10",
    ]
    expect_row_set("RQ2 GLM-5 tail-control row set", controls, "name", control_rows, controls_source)
    control_expected = {
        "GLM5_issue_only": (87.4, 53.0, 51.2, 62.4, 0, 0),
        "GLM5_CodeGraph_ht10": (93.6, 60.9, 53.0, 69.6, 36, 0),
        "GLM5_KGCompass_ht10": (93.4, 65.5, 53.7, 74.0, 58, 0),
    }
    for name, values in control_expected.items():
        row = row_by(controls, "name", name)
        expect_metric_row(controls_source, row, values[:4], f"RQ2 GLM tail {name}")
        expect_equal(f"RQ2 GLM tail {name} hit wins", int(row["hit_wins_vs_issue"]), values[4], controls_source)
        expect_equal(f"RQ2 GLM tail {name} hit losses", int(row["hit_losses_vs_issue"]), values[5], controls_source)

    released_source = "external_verified_loc_baselines_cosil_release_20260601.tsv"
    released = read_tsv(released_source)
    released_rows = [
        "CoSIL/CoSIL_qwen_coder_32b_func.jsonl",
        "locagent/locagent_qwen_coder_32b_func.jsonl",
        "agentless/agentless_qwen_coder_32b_func.jsonl",
        "orcaloca/orcaloca_qwen_coder_32b_func.jsonl",
    ]
    expect_row_set("RQ2 released Qwen2.5 row set", released, "name", released_rows, released_source)
    released_expected = {
        "CoSIL/CoSIL_qwen_coder_32b_func.jsonl": (85.0, 55.9, 52.0, 65.6),
        "locagent/locagent_qwen_coder_32b_func.jsonl": (76.2, 52.0, 53.0, 61.2),
        "agentless/agentless_qwen_coder_32b_func.jsonl": (81.4, 48.3, 43.2, 57.8),
        "orcaloca/orcaloca_qwen_coder_32b_func.jsonl": (69.0, 17.6, 16.8, 21.4),
    }
    for name, values in released_expected.items():
        expect_metric_row(released_source, row_by(released, "name", name), values, f"RQ2 released {name}")

    qwen_source = "qwen25_32b_kgcompass_fusion_20260601.tsv"
    qwen = read_tsv(qwen_source)
    expect_row_set(
        "RQ2 CoSIL-Qwen2.5 fusion row set",
        qwen,
        "name",
        ["CoSIL-Qwen2.5-32B+KGCompass", "CoSIL-Qwen2.5-32B"],
        qwen_source,
    )
    expect_metric_row(qwen_source, row_by(qwen, "name", "CoSIL-Qwen2.5-32B+KGCompass"), (90.6, 65.8, 53.2, 74.6), "RQ2 CoSIL+KG")
    expect_metric_row(qwen_source, row_by(qwen, "name", "CoSIL-Qwen2.5-32B"), (85.0, 55.9, 52.0, 65.6), "RQ2 CoSIL")

    local_source = "local_open_models_pathmined_top10_5p5_summary.tsv"
    local = read_tsv(local_source)
    local_rows = [
        "LocalQwen3Coder30B_KG_pathmined_5p5",
        "LocalQwen3Coder30B_issue_top10",
        "LocalDeepSeekCoderV2Lite_KG_pathmined_5p5",
        "LocalDeepSeekCoderV2Lite_issue_top10",
    ]
    expect_row_set("RQ2 local open row set", local, "name", local_rows, local_source)
    local_expected = {
        "LocalQwen3Coder30B_KG_pathmined_5p5": (70.8, 40.4, 28.4, 46.6),
        "LocalQwen3Coder30B_issue_top10": (51.4, 25.9, 25.8, 30.0),
        "LocalDeepSeekCoderV2Lite_KG_pathmined_5p5": (64.0, 38.8, 24.0, 45.0),
        "LocalDeepSeekCoderV2Lite_issue_top10": (27.8, 12.9, 13.7, 15.6),
    }
    for name, values in local_expected.items():
        expect_metric_row(local_source, row_by(local, "name", name), values, f"RQ2 local {name}")

    paired_source = "tse_paired_stats_pathmined_20260531.tsv"
    paired = read_tsv(paired_source)
    hit = row_by(paired, "metric", "Hit@20")
    expect_close("RQ2 GLM5 Hit@20 delta", float(hit["delta"]), 11.6, paired_source)
    expect_equal("RQ2 GLM5 Hit@20 wins", int(hit["wins"]), 58, paired_source)
    expect_equal("RQ2 GLM5 Hit@20 losses", int(hit["losses"]), 0, paired_source)
    expect_close("RQ2 GLM5 Hit@20 p-value", float(hit["p_value"]), 6.94e-18, paired_source, tol=1e-20)

    comp_source = "glm5_pathmined_kg_complementarity_20260531.json"
    comp = read_json(comp_source)
    overlap = comp["kg_only_vs_glm_issue_only"]
    expect_equal("RQ2 overlap GLM hit and KG hit", overlap["both_hit"], 190, comp_source)
    expect_equal("RQ2 overlap GLM hit and KG miss", overlap["glm_hits_missed_by_kg"], 122, comp_source)
    expect_equal("RQ2 overlap GLM miss and KG hit", overlap["kg_hits_missed_by_glm"], 64, comp_source)
    expect_equal("RQ2 overlap GLM miss and KG miss", 500 - overlap["union_hit_ceiling"], 124, comp_source)
    expect_equal("RQ2 GLM/KG union ceiling", overlap["union_hit_ceiling"], 376, comp_source)
    expect_equal("RQ2 fixed 10+10 fusion hits", comp["top20_hit"]["llm_kg_hit"], 370, comp_source)
    rescued = comp["rescued_method_instances"]
    expect_equal("RQ2 rescued method wins", rescued["count"], 58, comp_source)
    expect_equal("RQ2 rescued wins with KG evidence path", rescued["kg_evidence_hit_count"], 58, comp_source)
    expect_equal("RQ2 rescued rank <= 5", rescued["fusion_rank_buckets"]["fusion_rank_le_5"], 21, comp_source)
    expect_equal("RQ2 rescued rank <= 10", rescued["fusion_rank_buckets"]["fusion_rank_le_10"], 39, comp_source)
    expect_equal("RQ2 rescued two-hop paths", rescued["path_lengths"]["2"], 21, comp_source)
    expect_equal("RQ2 rescued three-hop paths", rescued["path_lengths"]["3"], 37, comp_source)


def verify_rq3() -> None:
    rq3_source = "kg_clean_tse_timesafe_main_20260529_v6_rq3.json"
    rq3 = read_json(rq3_source)
    expect_equal("RQ3 KG-only method-hit instances", rq3["method_hit_instances"], 189, rq3_source)
    expect_equal("RQ3 KG-only path observations", rq3["path_summary"]["path_observations"], 252, rq3_source)
    expect_equal("RQ3 KG-only length-2 paths", rq3["path_length_counts"]["2"], 251, rq3_source)
    expect_equal("RQ3 KG-only length-3 paths", rq3["path_length_counts"]["3"], 1, rq3_source)
    expect_equal("RQ3 KG-only file intermediate count", rq3["entity_type_counts"]["file"], 252, rq3_source)

    full_source = "path_mining_full500_summary.tsv"
    rows = read_tsv(full_source)
    expect_row_set("RQ3 compact summary row set", rows, "name", ["pathunion_v1", "kg_clean"], full_source)
    full_hits = round(float(row_by(rows, "name", "pathunion_v1")["top20_hit_rate"]) * 500)
    strict_hits = round(float(row_by(rows, "name", "kg_clean")["top20_hit_rate"]) * 500)
    expect_equal("RQ3 full path-mined hits", full_hits, 254, full_source)
    expect_equal("RQ3 without-file-local hits", strict_hits, 189, full_source)
    expect_equal("RQ3 net Hit@20 gain", full_hits - strict_hits, 65, full_source)

    mechanism_source = "rq3_file_local_path_mining_summary.tsv"
    mechanism = {row["metric"]: row["value"] for row in read_tsv(mechanism_source)}
    expected = {
        "kg_without_file_local_paths_hit_instances": "189",
        "kgcompass_hit_instances": "254",
        "net_hit20_gain_instances": "65",
        "paired_gross_wins": "67",
        "paired_regressions": "2",
        "gross_wins_length2_paths": "12",
        "gross_wins_length3_paths": "55",
        "gross_wins_length3_percent": "82.1",
    }
    expect_equal("RQ3 file-local mechanism summary", mechanism, expected, mechanism_source)


def verify_patch_derived_context() -> None:
    source = "patch_derived_context_summary_20260702.tsv"
    rows = read_tsv(source)
    expected_rows = [
        "BM25",
        "BLUiR",
        "CodeGraph",
        "KGCompass w/o file-local paths",
        "KGCompass",
        "GLM-5 issue-only",
        "GLM-5+CodeGraph",
        "GLM-5+KGCompass",
        "BM25 files + file-local",
        "BM25+KG RRF file-local",
        "GLM-5 + BM25 files + file-local",
        "GLM-5 + BM25+KG RRF file-local",
    ]
    expect_row_set("Patch-derived context row set", rows, "name", expected_rows, source)
    expected = {
        "BM25": (500, 500, 241, 39.2, 35.0, 46.0, 9.5, 32.8),
        "BLUiR": (500, 500, 241, 38.6, 34.6, 43.4, 17.4, 33.1),
        "CodeGraph": (500, 500, 241, 35.2, 31.2, 41.0, 13.4, 29.7),
        "KGCompass w/o file-local paths": (500, 430, 241, 33.8, 30.8, 37.8, 14.2, 27.9),
        "KGCompass": (500, 430, 241, 45.4, 41.4, 50.8, 19.4, 37.3),
        "GLM-5 issue-only": (500, 473, 241, 53.0, 46.2, 62.4, 11.0, 40.9),
        "GLM-5+CodeGraph": (500, 500, 241, 60.9, 53.8, 69.6, 20.4, 49.3),
        "GLM-5+KGCompass": (500, 498, 241, 65.5, 58.8, 74.0, 23.1, 53.6),
        "BM25 files + file-local": (500, 500, 241, 50.1, 44.6, 57.0, 19.0, 41.9),
        "BM25+KG RRF file-local": (500, 500, 241, 55.3, 49.0, 62.8, 21.8, 45.9),
        "GLM-5 + BM25 files + file-local": (500, 500, 241, 69.2, 62.2, 78.0, 23.7, 56.7),
        "GLM-5 + BM25+KG RRF file-local": (500, 500, 241, 70.9, 64.2, 79.0, 25.0, 58.0),
    }
    for name, values in expected.items():
        row = row_by(rows, "name", name)
        n, ranked_nonempty, support_bearing, edit_recall, complete_edit, edit_hit, support_recall, completeness = values
        expect_equal(f"Patch context {name} N", int(row["N"]), n, source)
        expect_equal(f"Patch context {name} ranked nonempty", int(row["ranked_nonempty"]), ranked_nonempty, source)
        expect_equal(f"Patch context {name} support-bearing N", int(row["support_bearing_N"]), support_bearing, source)
        expect_close(f"Patch context {name} edit target recall", pct(row["edit_target_recall"]), edit_recall, source)
        expect_close(f"Patch context {name} complete edit target", pct(row["complete_edit_target_rate"]), complete_edit, source)
        expect_close(f"Patch context {name} edit target hit", pct(row["edit_target_hit_rate"]), edit_hit, source)
        expect_close(f"Patch context {name} support context recall", pct(row["support_context_recall"]), support_recall, source)
        expect_close(f"Patch context {name} context completeness", pct(row["context_completeness"]), completeness, source)

    target_source = "patch_derived_context_targets_20260702.json"
    targets = read_json(target_source)
    items = targets["items"]
    support_counts = [int(item["support_entities_n"]) for item in items.values()]
    expect_equal("Patch context target cache size", targets["_meta"]["n"], 500, target_source)
    expect_equal("Patch context support-bearing instances", sum(1 for count in support_counts if count > 0), 241, target_source)
    expect_equal("Patch context support entity total", sum(support_counts), 1251, target_source)


def verify_rq4_and_boundary() -> None:
    source = "claudecode_context_probe_glm5_20260531.tsv"
    rows = read_tsv(source)
    expect_equal("RQ4 retained slice set", sorted({row["slice"] for row in rows}), ["full500"], source)
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
        field = {
            "nonempty": "nonempty_patches",
            "applied": "applied_patches",
            "resolved": "resolved",
        }[label.split()[-1]]
        expect_equal(label, int(row[field]), expected, source)

    paired_source = "claudecode_context_probe_glm5_20260531/paired_stats.json"
    paired = read_json(paired_source)
    expect_equal("RQ4 paired stats key set", sorted(paired.keys()), ["full500", "notes"], paired_source)
    full = paired["full500"]
    expect_equal("RQ4 paired instances", full["paired_instances"], 500, paired_source)
    expect_equal("RQ4 paired wins", full["wins"], 41, paired_source)
    expect_equal("RQ4 paired losses", full["losses"], 18, paired_source)
    expect_close("RQ4 exact McNemar p", float(full["exact_mcnemar_p"]), 0.0037937056353716074, paired_source, tol=1e-15)

    for context in ("nokg", "kg"):
        full500 = read_jsonl(f"claudecode_context_probe_glm5_20260531/full500_{context}_official_results.jsonl")
        expect_equal(f"RQ4 {context} full500 row count", len(full500), 500, f"claudecode_context_probe_glm5_20260531/full500_{context}_official_results.jsonl")

    audit_source = "kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json"
    audit = read_json(audit_source)["summary"]
    expect_equal("Boundary audit ok instances", audit["ok"], 500, audit_source)
    expect_equal("Boundary audit target PR hits", audit["target_pr_hits"], 0, audit_source)
    expect_equal("Boundary audit future-fix hits", audit["future_fix_trace_hits"], 0, audit_source)
    expect_equal("Boundary audit metadata issues", audit["metadata_issues"], 0, audit_source)
    expect_equal("Boundary audit content issue counts", audit["content_issue_counts"], {}, audit_source)
    expect_equal("Boundary audit structural issue counts", audit["structural_issue_counts"], {}, audit_source)

    sensitivity_source = "time_boundary_external_artifact_sensitivity_20260531.tsv"
    sensitivity = read_tsv(sensitivity_source)
    full_row = row_by(sensitivity, "setting", "full_pathmined")
    expect_equal("External artifact sensitivity instances", int(full_row["external_instances"]), 1, sensitivity_source)
    expect_equal("External artifact sensitivity Top-20 candidates", int(full_row["external_top20_candidates"]), 2, sensitivity_source)
    expect_equal("External artifact sensitivity Hit@20 losses", int(full_row["hit_losses"]), 0, sensitivity_source)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify KGCompass paper-facing artifact values.")
    parser.add_argument(
        "--rq",
        choices=("all", "setup", "rq1", "rq2", "rq3", "rq4"),
        default="all",
        help="Restrict checks to one section. Default: all.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_checks = {
        "setup": verify_setup,
        "rq1": verify_rq1,
        "rq2": verify_rq2,
        "rq3": lambda: (verify_rq3(), verify_patch_derived_context()),
        "rq4": verify_rq4_and_boundary,
    }
    try:
        verify_result_inventory()
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
