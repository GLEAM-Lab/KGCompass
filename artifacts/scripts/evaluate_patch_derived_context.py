#!/usr/bin/env python3
"""Evaluate mapped edit-target coverage for ranked context windows."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


DEFAULT_ROWS = [
    ("BM25", "controlled", "runs/text_baselines_nohints/2000"),
    (
        "KGCompass w/o file-local paths",
        "controlled",
        "runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6",
    ),
    (
        "KGCompass",
        "controlled",
        "runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1",
    ),
    ("GLM-5 issue-only", "fusion", "temp_run/eval_aliyun_glm5_issueonly"),
    (
        "GLM-5+KGCompass",
        "fusion",
        "temp_run/fusions_glm5_baseline_controls_20260614_head10/GLM5_KGCompass_ht10",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids-file", type=Path, default=Path("temp_run/SWE-bench_Verified_ids.jsonl"))
    parser.add_argument(
        "--gt-cache",
        type=Path,
        default=Path("temp_run/output/gt_eval_cache_verified_v3_entities.json"),
    )
    parser.add_argument(
        "--target-cache",
        type=Path,
        default=Path("artifacts/results/patch_derived_context_targets_20260702.json"),
    )
    parser.add_argument(
        "--output-tsv",
        type=Path,
        default=Path("artifacts/results/patch_derived_context_summary_20260702.tsv"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("artifacts/results/patch_derived_context_summary_20260702.json"),
    )
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument(
        "--row",
        action="append",
        default=[],
        metavar="NAME=FAMILY=DIR",
        help="Append an explicitly reported directory-backed evaluation row.",
    )
    return parser.parse_args()


def parse_extra_row(raw: str) -> tuple[str, str, str]:
    parts = raw.split("=", 2)
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise ValueError(f"Invalid --row value {raw!r}; expected NAME=FAMILY=DIR")
    return tuple(part.strip() for part in parts)  # type: ignore[return-value]


def load_ids(path: Path) -> list[str]:
    ids: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            ids.append(json.loads(line)["instance_id"] if line.startswith("{") else line)
    return ids


def load_gt(path: Path) -> dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8"))["items"]


def build_edit_targets(ids: list[str], gt_map: dict[str, dict], cache_path: Path) -> dict[str, dict]:
    if cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        meta = data.get("_meta", {})
        if meta.get("cache_version") == 3 and all(iid in data.get("items", {}) for iid in ids):
            return data["items"]

    items: dict[str, dict] = {}
    for iid in ids:
        gt = gt_map[iid]
        items[iid] = {
            "patch_files": gt.get("patch_files") or [],
            "edit_methods": sorted(gt.get("found_methods") or []),
            "edit_classes": sorted(gt.get("found_classes") or []),
            "gt_entities_n": int(gt.get("gt_entities_n", 0) or 0),
            "fallback_file_target": int(gt.get("fallback_file_target", 0) or 0),
        }

    payload = {
        "_meta": {
            "cache_version": 3,
            "n": len(items),
            "target_definition": (
                "base-commit functions, methods, assignments, or classes mapped from official patch lines; "
                "patched-file fallback when no entity can be mapped"
            ),
        },
        "items": items,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return items


def signature_to_base(signature: str) -> str:
    base = (signature or "").strip()
    if not base:
        return ""
    base = base.split(" = ", 1)[0].strip()
    return base.split("(", 1)[0].strip()


def signature_matches_class(signature: str, class_name: str) -> bool:
    sig_base = signature_to_base(signature)
    return bool(sig_base and class_name and (sig_base == class_name or sig_base.startswith(class_name + ".")))


def file_matches(candidate_file: str, patch_files: list[str]) -> bool:
    return any(path == candidate_file or path in candidate_file or candidate_file in path for path in patch_files)


def rank_methods(methods: list[dict]) -> list[dict]:
    has_numeric_similarity = any(isinstance(item.get("similarity"), (int, float)) for item in methods)
    if not has_numeric_similarity:
        return list(methods)
    return sorted(
        methods,
        key=lambda item: item.get("similarity") if isinstance(item.get("similarity"), (int, float)) else float("-inf"),
        reverse=True,
    )


def dir_candidates(path: Path, iid: str, top_limit: int = 50) -> list[dict]:
    result_path = path / f"{iid}.json"
    if not result_path.exists():
        return []
    data = json.loads(result_path.read_text(encoding="utf-8"))
    methods = rank_methods((data.get("related_entities") or {}).get("methods") or [])
    candidates: list[dict] = []
    seen: set[str] = set()
    for method in methods:
        signature = method.get("signature") or ""
        if not signature or signature in seen:
            continue
        seen.add(signature)
        candidates.append({"file_path": method.get("file_path") or "", "signature": signature})
        if len(candidates) >= top_limit:
            break
    return candidates


def matched_edit_targets(candidate: dict, targets: dict) -> tuple[set[str], int]:
    signature = candidate.get("signature") or ""
    edit_methods = set(targets["edit_methods"])
    edit_classes = set(targets["edit_classes"])
    matched: set[str] = set()

    if signature in edit_methods:
        matched.add(signature)
    else:
        for class_name in edit_classes:
            if signature_matches_class(signature, class_name):
                matched.add(class_name)
                break

    fallback_hit = int(
        bool(targets["fallback_file_target"])
        and file_matches(candidate.get("file_path") or "", targets["patch_files"])
    )
    return matched, fallback_hit


def evaluate_candidates(
    ids: list[str],
    targets_by_id: dict[str, dict],
    candidates_by_id: dict[str, list[dict]],
    top_k: int,
) -> dict:
    edit_recall_sum = 0.0
    complete_edit = 0

    for iid in ids:
        targets = targets_by_id[iid]
        matched: set[str] = set()
        fallback_hit = 0
        for candidate in candidates_by_id.get(iid, [])[:top_k]:
            matched_delta, fallback_delta = matched_edit_targets(candidate, targets)
            matched.update(matched_delta)
            fallback_hit = max(fallback_hit, fallback_delta)

        denominator = max(1, int(targets["gt_entities_n"]))
        found = fallback_hit if targets["fallback_file_target"] else len(matched)
        edit_recall_sum += found / denominator
        complete_edit += int(found >= denominator)

    n = len(ids)
    return {
        "N": n,
        "edit_target_recall": edit_recall_sum / n if n else 0.0,
        "complete_edit_target_rate": complete_edit / n if n else 0.0,
    }


def candidates_from_dir(ids: list[str], path: Path, top_limit: int) -> dict[str, list[dict]]:
    return {iid: dir_candidates(path, iid, top_limit=top_limit) for iid in ids}


def main() -> int:
    args = parse_args()
    ids = load_ids(args.ids_file)
    targets = build_edit_targets(ids, load_gt(args.gt_cache), args.target_cache)

    row_payloads: list[dict] = []
    configured_rows = [*DEFAULT_ROWS, *(parse_extra_row(raw) for raw in args.row)]
    seen_names: set[str] = set()
    for name, family, source in configured_rows:
        if name in seen_names:
            raise ValueError(f"Duplicate evaluation row name: {name}")
        seen_names.add(name)
        candidates_by_id = candidates_from_dir(ids, Path(source), top_limit=args.top_k)
        row_payloads.append(
            {
                "name": name,
                "family": family,
                "source": source,
                **evaluate_candidates(ids, targets, candidates_by_id, args.top_k),
            }
        )

    args.output_tsv.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "name",
        "family",
        "N",
        "edit_target_recall",
        "complete_edit_target_rate",
        "source",
    ]
    with args.output_tsv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader()
        for row in row_payloads:
            out = dict(row)
            for key in ("edit_target_recall", "complete_edit_target_rate"):
                out[key] = f"{out[key]:.6f}"
            writer.writerow(out)

    meta = {
        "top_k": args.top_k,
        "target_cache": str(args.target_cache),
        "target_definition": (
            "base-commit functions, methods, assignments, or classes mapped from official patch lines; "
            "patched-file fallback when no entity can be mapped"
        ),
        "rows": {row["name"]: row for row in row_payloads},
    }
    args.output_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output_tsv}")
    print(f"wrote {args.output_json}")
    print(f"wrote {args.target_cache}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
