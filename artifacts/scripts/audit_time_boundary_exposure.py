#!/usr/bin/env python3
"""Audit how much localization signal is exposed by SWE-bench hint/comment fields.

This script does not accuse a particular system of using the field.  It quantifies
the risk if a localization or repair pipeline consumes ``hints_text`` or follows
target-issue discussion comments, and it audits public submission README files for
explicit no-hint disclosures when a local SWE-bench experiments checkout exists.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Iterable

from datasets import load_dataset


def patch_files(patch: str) -> list[str]:
    files: set[str] = set()
    for match in re.finditer(r"^diff --git a/(.*?) b/(.*?)$", patch or "", flags=re.M):
        files.add(match.group(2))
    return sorted(files)


def pct(count: int, total: int) -> float:
    return round(100.0 * count / total, 1) if total else 0.0


def has(pattern: str, text: str, flags: int = 0) -> bool:
    return re.search(pattern, text, flags=flags) is not None


def audit_hints(dataset_name: str, split: str) -> tuple[dict, list[dict]]:
    dataset = load_dataset(dataset_name, split=split)
    rows: list[dict] = []
    for item in dataset:
        hints = (item.get("hints_text") or item.get("hint_text") or "").strip()
        hints_lower = hints.lower()
        files = patch_files(item.get("patch") or "")
        full_file_mentions = [path for path in files if path.lower() in hints_lower]
        basename_mentions = [
            path
            for path in files
            if os.path.basename(path)
            and has(rf"(?<![\w.-]){re.escape(os.path.basename(path).lower())}(?![\w.-])", hints_lower)
        ]
        rows.append(
            {
                "instance_id": item["instance_id"],
                "hint_chars": len(hints),
                "has_hint": bool(hints),
                "github_url": "github.com" in hints_lower,
                "github_line_url": has(r"github\.com/.+#L\d+", hints),
                "python_path": has(r"(?m)([\w.-]+/)+[\w.-]+\.py", hints),
                "localization_words": has(
                    r"\b(file|line|function|method|class|module|traceback|stack|diff|patch|commit|pull request|pr)\b",
                    hints,
                    flags=re.I,
                ),
                "diff_snippet": has(r"(?im)^diff --git|---\s+a/|\+\+\+\s+b/", hints),
                "commit_hash": has(r"\b[0-9a-f]{7,40}\b", hints),
                "code_fence": "```" in hints,
                "explicit_line_word": has(r"(?i)\bline\s+#?\d+|#L\d+", hints),
                "mentions_full_gt_file": bool(full_file_mentions),
                "mentions_gt_basename": bool(basename_mentions),
                "gt_files": files,
                "mentioned_gt_files": full_file_mentions,
                "mentioned_gt_basenames": basename_mentions,
                "hint_excerpt": hints[:500],
            }
        )

    total = len(rows)
    metrics = [
        "has_hint",
        "github_url",
        "github_line_url",
        "python_path",
        "localization_words",
        "diff_snippet",
        "commit_hash",
        "code_fence",
        "explicit_line_word",
        "mentions_full_gt_file",
        "mentions_gt_basename",
    ]
    summary = {
        "dataset": dataset_name,
        "split": split,
        "total_instances": total,
        "metrics": {
            name: {"count": sum(1 for row in rows if row[name]), "percent": pct(sum(1 for row in rows if row[name]), total)}
            for name in metrics
        },
        "source_field_note": (
            "SWE-bench documents hints_text as issue comments before the solution PR's first commit; "
            "KGCompass treats this as a benchmark-only comment-derived channel and excludes it."
        ),
    }
    return summary, rows


def audit_submission_readmes(root: Path | None) -> dict:
    if root is None or not root.exists():
        return {
            "root": str(root) if root else None,
            "available": False,
            "readme_count": 0,
            "explicit_no_hints": 0,
            "explicit_hints_use": 0,
            "unknown_or_no_disclosure": 0,
        }

    no_hint_patterns = [
        r"does not use\s+(?:the\s+)?`?hints?",
        r"does not have access to hints_text",
        r"without using\s+`?hints?_?text`?",
        r"hints field.*(?:yes|\[x\]|✅)",
    ]
    use_hint_patterns = [
        r"uses?\s+(?:the\s+)?`?hints?_?text`?",
        r"uses?\s+(?:the\s+)?`?hints?\s+field",
    ]
    readmes = sorted(root.glob("*/README.md"))
    no_hints: list[str] = []
    uses_hints: list[str] = []
    unknown: list[str] = []
    for path in readmes:
        text = path.read_text(errors="ignore").lower()
        if any(re.search(pattern, text) for pattern in no_hint_patterns):
            no_hints.append(str(path))
        elif any(re.search(pattern, text) for pattern in use_hint_patterns):
            uses_hints.append(str(path))
        else:
            unknown.append(str(path))

    return {
        "root": str(root),
        "available": True,
        "readme_count": len(readmes),
        "explicit_no_hints": len(no_hints),
        "explicit_hints_use": len(uses_hints),
        "unknown_or_no_disclosure": len(unknown),
        "explicit_no_hints_percent": pct(len(no_hints), len(readmes)),
        "explicit_hints_use_percent": pct(len(uses_hints), len(readmes)),
        "unknown_or_no_disclosure_percent": pct(len(unknown), len(readmes)),
        "explicit_no_hints_examples": no_hints[:10],
        "explicit_hints_use_examples": uses_hints[:10],
        "unknown_examples": unknown[:10],
    }


def write_metric_tsv(summary: dict, path: Path) -> None:
    lines = ["metric\tcount\tpercent\tnote"]
    notes = {
        "has_hint": "non-blank benchmark hints_text",
        "github_url": "hint contains a GitHub URL",
        "github_line_url": "hint contains a GitHub URL with a line anchor",
        "python_path": "hint contains a Python file path pattern",
        "localization_words": "hint contains localization-related vocabulary",
        "diff_snippet": "hint contains a diff-like snippet",
        "commit_hash": "hint contains a 7-40 hex commit-like hash",
        "code_fence": "hint contains a fenced code block",
        "explicit_line_word": "hint contains an explicit line-number cue",
        "mentions_full_gt_file": "hint contains an exact edited file path from the gold patch",
        "mentions_gt_basename": "hint contains an edited file basename from the gold patch",
    }
    for name, value in summary["metrics"].items():
        lines.append(f"{name}\t{value['count']}\t{value['percent']}\t{notes.get(name, '')}")
    path.write_text("\n".join(lines) + "\n")


def write_examples_tsv(rows: Iterable[dict], path: Path, limit: int) -> None:
    lines = ["instance_id\tmentioned_gt_files\tgt_files\thint_excerpt"]
    kept = 0
    for row in rows:
        if not row["mentions_full_gt_file"]:
            continue
        excerpt = row["hint_excerpt"].replace("\t", " ").replace("\r", " ").replace("\n", " ")[:300]
        excerpt = excerpt.encode("ascii", "ignore").decode("ascii")
        lines.append(
            f"{row['instance_id']}\t{';'.join(row['mentioned_gt_files'])}\t{';'.join(row['gt_files'])}\t{excerpt}"
        )
        kept += 1
        if kept >= limit:
            break
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-name", default="princeton-nlp/SWE-bench_Verified")
    parser.add_argument("--split", default="test")
    parser.add_argument(
        "--readme-root",
        type=Path,
        default=Path("/home/barty/research/experiments/evaluation/verified"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("logs/comparison_current/time_boundary_exposure_audit_20260601.json"),
    )
    parser.add_argument(
        "--output-tsv",
        type=Path,
        default=Path("logs/comparison_current/time_boundary_exposure_audit_20260601.tsv"),
    )
    parser.add_argument(
        "--examples-tsv",
        type=Path,
        default=Path("logs/comparison_current/time_boundary_exposure_examples_20260601.tsv"),
    )
    parser.add_argument("--example-limit", type=int, default=20)
    args = parser.parse_args()

    summary, rows = audit_hints(args.dataset_name, args.split)
    summary["submission_readme_audit"] = audit_submission_readmes(args.readme_root)

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_tsv.parent.mkdir(parents=True, exist_ok=True)
    args.examples_tsv.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n")
    write_metric_tsv(summary, args.output_tsv)
    write_examples_tsv(rows, args.examples_tsv, args.example_limit)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
