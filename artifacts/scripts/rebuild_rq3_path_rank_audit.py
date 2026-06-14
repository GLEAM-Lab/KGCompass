#!/usr/bin/env python3
"""Rebuild the RQ-3 legacy path/rank audit summaries from observation ledgers.

The 320-row audit is an exploratory legacy audit restored from the earlier
path_correct/rank_correct figure-count data. This script intentionally reads
the explicit paper-side observation ledgers rather than the archived plotting
scripts, then checks that the published aggregate tables are consistent with
those ledgers.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "artifacts" / "results"
PATH_LEDGER = "rq3_path_audit_observations_20260614.tsv"
RANK_LEDGER = "rq3_rank_audit_observations_20260614.tsv"


def read_tsv(name: str) -> list[dict[str, str]]:
    with (RESULTS / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def row_by(rows: list[dict[str, str]], **criteria: str) -> dict[str, str]:
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            return row
    raise AssertionError(f"row not found: {criteria}")


def chi_square_2x2(a: int, b: int, c: int, d: int) -> float:
    total = a + b + c + d
    denom = (a + b) * (c + d) * (a + c) * (b + d)
    if denom == 0:
        return 0.0
    return total * ((a * d - b * c) ** 2) / denom


def chi_square_df1_pvalue(value: float) -> float:
    return math.erfc(math.sqrt(value / 2.0))


def hypergeom_prob(a: int, row1: int, row2: int, col1: int, col2: int) -> float:
    b = row1 - a
    c = col1 - a
    d = row2 - c
    if min(a, b, c, d) < 0:
        return 0.0
    total = row1 + row2
    logp = (
        math.lgamma(row1 + 1)
        + math.lgamma(row2 + 1)
        + math.lgamma(col1 + 1)
        + math.lgamma(col2 + 1)
        - math.lgamma(a + 1)
        - math.lgamma(b + 1)
        - math.lgamma(c + 1)
        - math.lgamma(d + 1)
        - math.lgamma(total + 1)
    )
    return math.exp(logp)


def fisher_two_sided(a: int, b: int, c: int, d: int) -> tuple[float, float]:
    row1 = a + b
    row2 = c + d
    col1 = a + c
    col2 = b + d
    observed = hypergeom_prob(a, row1, row2, col1, col2)
    low = max(0, col1 - row2)
    high = min(row1, col1)
    pvalue = 0.0
    for candidate in range(low, high + 1):
        prob = hypergeom_prob(candidate, row1, row2, col1, col2)
        if prob <= observed + 1e-15:
            pvalue += prob
    odds = math.inf if b * c == 0 else (a * d) / (b * c)
    return odds, min(pvalue, 1.0)


def assert_close(name: str, observed: float, expected: float, tol: float = 1e-6) -> None:
    if not math.isclose(observed, expected, abs_tol=tol):
        raise AssertionError(f"{name}: observed {observed} != expected {expected}")


def rebuild_path() -> dict[str, Any]:
    rows = read_tsv(PATH_LEDGER)
    total_by_outcome = Counter(row["outcome"] for row in rows)
    lengths = Counter((row["outcome"], row["path_length"]) for row in rows)
    non_null = Counter(row["outcome"] for row in rows if row["path_present"] == "1")
    null = Counter(row["outcome"] for row in rows if row["path_present"] == "0")

    a = non_null["correct"]
    b = null["correct"]
    c = non_null["wrong"]
    d = null["wrong"]
    chi2 = chi_square_2x2(a, b, c, d)
    odds, fisher_p = fisher_two_sided(a, b, c, d)

    published = read_tsv("path_availability_audit_20260613.tsv")
    for outcome in ("correct", "wrong"):
        for length in ("1", "2", "3", "4", "null"):
            published_count = int(row_by(published, kind="path_length", outcome=outcome, path_length=length)["count"])
            if lengths[(outcome, length)] != published_count:
                raise AssertionError(f"path {outcome}/{length}: {lengths[(outcome, length)]} != {published_count}")

    test = row_by(published, kind="test", outcome="non_null_vs_null", statistic="pearson_chi2")
    assert_close("path chi-square", chi2, float(test["value"]))
    fisher = row_by(published, kind="test", outcome="non_null_vs_null", statistic="fisher_odds_ratio")
    assert_close("path fisher odds ratio", odds, float(fisher["value"]))
    assert_close("path fisher p-value", fisher_p, float(fisher["pvalue"]), tol=1e-12)

    return {
        "rows": len(rows),
        "outcomes": dict(total_by_outcome),
        "non_null_table": {
            "correct_non_null": a,
            "correct_null": b,
            "wrong_non_null": c,
            "wrong_null": d,
        },
        "pearson_chi2": chi2,
        "pearson_p": chi_square_df1_pvalue(chi2),
        "fisher_odds_ratio": odds,
        "fisher_p": fisher_p,
    }


def rebuild_rank() -> dict[str, Any]:
    rows = read_tsv(RANK_LEDGER)
    total_by_outcome = Counter(row["outcome"] for row in rows)
    buckets = Counter((row["outcome"], row["rank_bucket"]) for row in rows)
    top5 = Counter(row["outcome"] for row in rows if row["top5"] == "1")
    not_top5 = Counter(row["outcome"] for row in rows if row["top5"] == "0")

    published = read_tsv("rank_availability_audit_20260613.tsv")
    for outcome in ("correct", "wrong"):
        for bucket in ("1", "2", "3", "4", "5", "6-10", "11-20", "other"):
            published_count = int(row_by(published, kind="rank", outcome=outcome, rank_bucket=bucket)["count"])
            if buckets[(outcome, bucket)] != published_count:
                raise AssertionError(f"rank {outcome}/{bucket}: {buckets[(outcome, bucket)]} != {published_count}")

    a = top5["correct"]
    b = not_top5["correct"]
    c = top5["wrong"]
    d = not_top5["wrong"]
    chi2 = chi_square_2x2(a, b, c, d)
    odds, fisher_p = fisher_two_sided(a, b, c, d)
    test = row_by(published, kind="test", outcome="top5_vs_rest", statistic="pearson_chi2")
    assert_close("rank top5 chi-square", chi2, float(test["value"]))
    fisher = row_by(published, kind="test", outcome="top5_vs_rest", statistic="fisher_odds_ratio")
    assert_close("rank top5 fisher odds ratio", odds, float(fisher["value"]))
    assert_close("rank top5 fisher p-value", fisher_p, float(fisher["pvalue"]), tol=1e-12)

    return {
        "rows": len(rows),
        "outcomes": dict(total_by_outcome),
        "top5_table": {
            "correct_top5": a,
            "correct_rest": b,
            "wrong_top5": c,
            "wrong_rest": d,
        },
        "pearson_chi2": chi2,
        "pearson_p": chi_square_df1_pvalue(chi2),
        "fisher_odds_ratio": odds,
        "fisher_p": fisher_p,
    }


def main() -> int:
    try:
        report = {
            "ok": True,
            "path": rebuild_path(),
            "rank": rebuild_rank(),
            "note": "Exploratory legacy audit restored from figure-count data; not a 500-instance per-instance ledger.",
        }
    except Exception as exc:  # noqa: BLE001 - reviewer-facing script should print context.
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
