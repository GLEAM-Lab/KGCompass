#!/usr/bin/env python3
"""Audit KG location JSON files for paper-valid leakage boundary sentinels.

The checks here are conservative text sentinels, not a complete timestamp
proof. The primary sentinel is whether a SWE-bench instance output contains the
fixing pull request id encoded by the instance id suffix, e.g. whether
``astropy__astropy-12907.json`` contains ``pr#12907``. The audit also flags
obvious fixing traces such as ``Fixed #<target>``, exported issue/PR comments,
and Trac ``revision=...`` text if those strings reach the exported JSON.
"""

import argparse
import json
import re
from pathlib import Path


def _target_pr_id(instance_id: str) -> str | None:
    if "-" not in instance_id:
        return None
    suffix = instance_id.rsplit("-", 1)[-1]
    return suffix if suffix.isdigit() else None


def _metadata_flags(obj: dict) -> list[str]:
    flags = []
    params = obj.get("kg_params") or {}
    if params.get("uses_discussion_comments") not in (False, None):
        flags.append("uses_discussion_comments")
    if params.get("uses_embeddings") not in (False, None):
        flags.append("uses_embeddings")
    if params.get("tunable_retrieval_parameters") not in ([], None):
        flags.append("has_tunable_retrieval_parameters")
    return flags


def _content_flags(serialized: str, target: str | None) -> tuple[list[str], list[str]]:
    flags = []
    warnings = []
    if target and re.search(
        rf"(?<![a-z0-9_])pr#{re.escape(target)}(?![a-z0-9_])", serialized
    ):
        flags.append("target_pr_reference")
    if target and re.search(
        rf"github\.com/[^\s\"'<>]+/(?:pull|pulls|issues)/{re.escape(target)}(?!\d)",
        serialized,
    ):
        flags.append("target_fix_reference_url")
    if target and re.search(
        rf"code\.djangoproject\.com/ticket/{re.escape(target)}(?!\d)",
        serialized,
    ):
        flags.append("target_fix_reference_url")
    if target and re.search(
        rf"\b(?:pr|pull\s+request|pull|issue)\s*#?\s*{re.escape(target)}\b",
        serialized,
    ):
        flags.append("target_fix_reference_text")
    if target and (
        re.search(
            rf"\b(?:fix(?:e[ds])?|close[sd]?|resolve[sd]?)\s+#\s*{re.escape(target)}\b",
            serialized,
        )
        or re.search(
            rf"revision=[\"'][0-9a-f]{{12,}}[\"'][^{{}}]{{0,240}}#\s*{re.escape(target)}\b",
            serialized,
        )
    ):
        flags.append("target_fix_trace")
    if re.search(r"###\s+comment\s*:", serialized):
        flags.append("exported_issue_comment")
    if re.search(r"\bfix(?:e[ds])?\s+#\s*\d+\b", serialized):
        warnings.append("generic_fixed_issue_reference")
    return flags, warnings


def _target_pr_entity_and_path_flags(obj: dict, target: str | None) -> list[str]:
    if not target:
        return []

    flags = []
    related = obj.get("related_entities") or {}
    issues = related.get("issues") or []
    if isinstance(issues, list):
        for item in issues:
            if not isinstance(item, dict):
                continue
            if str(item.get("issue_id")) == target or str(item.get("name")) == f"pr#{target}":
                flags.append("target_pr_entity")
                break

    target_label = f"pr#{target}".lower()
    for group in ("methods", "classes", "issues", "files"):
        items = related.get(group) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            path_text = json.dumps(item.get("path") or [], ensure_ascii=False).lower()
            if target_label in path_text:
                flags.append("target_pr_in_any_path")
                if group == "methods":
                    flags.append("target_pr_in_method_path")
                elif group == "classes":
                    flags.append("target_pr_in_class_path")
                return sorted(set(flags))
    return sorted(set(flags))


def audit_file(path: Path) -> dict:
    instance_id = path.stem
    target = _target_pr_id(instance_id)
    try:
        obj = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001 - report malformed artifact.
        return {
            "path": str(path),
            "instance_id": instance_id,
            "ok": False,
            "target_pr_present": None,
            "metadata_flags": ["json_parse_error"],
            "error": str(exc),
        }

    serialized = json.dumps(obj, ensure_ascii=False).lower()
    content_flags, warning_content_flags = _content_flags(serialized, target)
    structural_flags = _target_pr_entity_and_path_flags(obj, target)
    target_pr_present = "target_pr_reference" in content_flags
    future_fix_trace_present = "target_fix_trace" in content_flags
    metadata_flags = _metadata_flags(obj)
    ok = not content_flags and not structural_flags and not metadata_flags
    return {
        "path": str(path),
        "instance_id": instance_id,
        "ok": ok,
        "target_pr_present": target_pr_present,
        "future_fix_trace_present": future_fix_trace_present,
        "content_flags": content_flags,
        "warning_content_flags": warning_content_flags,
        "structural_flags": structural_flags,
        "metadata_flags": metadata_flags,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit KGCompass JSON location artifacts for leakage flags."
    )
    parser.add_argument("json_dir", help="Directory containing per-instance KG JSON files.")
    parser.add_argument(
        "--output-json",
        default=None,
        help="Optional path to write the full audit report as JSON.",
    )
    parser.add_argument(
        "--fail-on-issue",
        action="store_true",
        help="Exit non-zero if any leakage or metadata issue is detected.",
    )
    args = parser.parse_args()

    json_dir = Path(args.json_dir)
    files = sorted(json_dir.glob("*.json"))
    results = [audit_file(path) for path in files]
    target_pr_hits = [item for item in results if item.get("target_pr_present")]
    content_issues = [item for item in results if item.get("content_flags")]
    future_fix_trace_hits = [item for item in results if item.get("future_fix_trace_present")]
    metadata_issues = [item for item in results if item.get("metadata_flags")]
    content_issue_counts = {}
    warning_content_issue_counts = {}
    structural_issue_counts = {}
    for item in results:
        for flag in item.get("content_flags", []):
            content_issue_counts[flag] = content_issue_counts.get(flag, 0) + 1
        for flag in item.get("warning_content_flags", []):
            warning_content_issue_counts[flag] = (
                warning_content_issue_counts.get(flag, 0) + 1
            )
        for flag in item.get("structural_flags", []):
            structural_issue_counts[flag] = structural_issue_counts.get(flag, 0) + 1
    ok_count = sum(1 for item in results if item["ok"])

    summary = {
        "json_dir": str(json_dir),
        "total": len(results),
        "ok": ok_count,
        "target_pr_hits": len(target_pr_hits),
        "future_fix_trace_hits": len(future_fix_trace_hits),
        "content_issue_counts": dict(sorted(content_issue_counts.items())),
        "warning_content_issue_counts": dict(
            sorted(warning_content_issue_counts.items())
        ),
        "structural_issue_counts": dict(sorted(structural_issue_counts.items())),
        "metadata_issues": len(metadata_issues),
        "content_issue_instances": [
            {"instance_id": item["instance_id"], "flags": item["content_flags"]}
            for item in content_issues
        ],
        "target_pr_hit_instances": [item["instance_id"] for item in target_pr_hits],
        "future_fix_trace_hit_instances": [
            item["instance_id"] for item in future_fix_trace_hits
        ],
        "metadata_issue_instances": [
            {"instance_id": item["instance_id"], "flags": item["metadata_flags"]}
            for item in metadata_issues
        ],
    }

    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({"summary": summary, "results": results}, indent=2))

    structural_issues = [item for item in results if item.get("structural_flags")]
    if args.fail_on_issue and (
        content_issues or future_fix_trace_hits or metadata_issues or structural_issues
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
