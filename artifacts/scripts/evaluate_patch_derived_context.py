#!/usr/bin/env python3
"""Evaluate patch-derived repair-context coverage for ranked context windows.

The existing paper metrics evaluate whether a Top-K window covers official
patch edit targets.  This script keeps that definition and adds a conservative
support-context set derived from the official patch itself: non-edited
functions or assignments in patched files whose simple names are referenced by
the patch hunk text.  This makes the "repair context" target reproducible and
keeps it tied to the developer patch rather than subjective annotation.
"""

from __future__ import annotations

import argparse
import csv
import json
import keyword
import os
import re
import sys
from pathlib import Path
from typing import Iterable

from datasets import Dataset
from unidiff import PatchSet


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "kgcompass"))
import utils  # type: ignore  # noqa: E402


DEFAULT_ROWS = [
    (
        "BM25",
        "controlled",
        "dir",
        "runs/text_baselines_nohints/2000",
    ),
    (
        "BLUiR",
        "controlled",
        "dir",
        "runs/text_baselines_bluir/2300",
    ),
    (
        "CodeGraph",
        "controlled",
        "dir",
        "runs/codegraph_anchor/tse_timesafe_main_20260531_v2",
    ),
    (
        "KGCompass w/o file-local paths",
        "controlled",
        "dir",
        "runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6",
    ),
    (
        "KGCompass",
        "controlled",
        "dir",
        "runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1",
    ),
    (
        "GLM-5 issue-only",
        "fusion",
        "dir",
        "temp_run/eval_aliyun_glm5_issueonly",
    ),
    (
        "GLM-5+CodeGraph",
        "fusion",
        "dir",
        "temp_run/fusions_glm5_baseline_controls_20260614_head10/GLM5_CodeGraph_ht10",
    ),
    (
        "GLM-5+KGCompass",
        "fusion",
        "dir",
        "temp_run/fusions_glm5_baseline_controls_20260614_head10/GLM5_KGCompass_ht10",
    ),
]


COMMON_IDENTIFIERS = {
    "self",
    "cls",
    "args",
    "kwargs",
    "None",
    "True",
    "False",
    "return",
    "yield",
    "super",
    "object",
    "str",
    "int",
    "float",
    "bool",
    "list",
    "dict",
    "set",
    "tuple",
    "len",
    "range",
    "isinstance",
    "getattr",
    "setattr",
    "hasattr",
    "ValueError",
    "TypeError",
    "Exception",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids-file", type=Path, default=Path("temp_run/SWE-bench_Verified_ids.jsonl"))
    parser.add_argument(
        "--gt-cache",
        type=Path,
        default=Path("temp_run/output/gt_eval_cache_verified_v3_entities.json"),
    )
    parser.add_argument(
        "--support-cache",
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
    parser.add_argument(
        "--external-root",
        type=Path,
        default=Path("/tmp/kgc_external_baselines/CoSIL/loc_to_patch_verified"),
    )
    parser.add_argument(
        "--kg-dir",
        type=Path,
        default=Path("runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1"),
    )
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--primary-head", type=int, default=10)
    parser.add_argument("--kg-head", type=int, default=20)
    parser.add_argument(
        "--row",
        action="append",
        default=[],
        metavar="NAME=FAMILY=DIR",
        help="Append a directory-backed evaluation row without changing the built-in paper rows.",
    )
    return parser.parse_args()


def parse_extra_row(raw: str) -> tuple[str, str, str, str]:
    parts = raw.split("=", 2)
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise ValueError(f"Invalid --row value {raw!r}; expected NAME=FAMILY=DIR")
    name, family, source = (part.strip() for part in parts)
    return name, family, "dir", source


def load_ids(path: Path) -> list[str]:
    ids: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            ids.append(json.loads(line)["instance_id"] if line.startswith("{") else line)
    return ids


def discover_arrow() -> Path:
    root = Path.home() / ".cache/huggingface/datasets/princeton-nlp___swe-bench_verified/default/0.0.0"
    candidates = sorted(root.glob("*/swe-bench_verified-test.arrow"), key=os.path.getmtime)
    if not candidates:
        raise FileNotFoundError("Cannot locate cached SWE-bench Verified arrow file")
    return candidates[-1]


def load_dataset_by_id(ids: list[str]) -> dict[str, dict]:
    ds = Dataset.from_file(str(discover_arrow()))
    id_set = set(ids)
    return {row["instance_id"]: dict(row) for row in ds if row.get("instance_id") in id_set}


def load_gt(path: Path) -> dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8"))["items"]


def iter_local_repo_roots(repo_full_name: str):
    repo_id = repo_full_name.replace("/", "__")
    repo_name = repo_full_name.split("/")[-1]
    for root in (REPO_ROOT / "playground" / repo_id, REPO_ROOT / "playground" / repo_name):
        if root.is_dir():
            yield root


def get_local_commit_file_content(repo_full_name: str, commit_sha: str, file_path: str) -> str | None:
    for repo_root in iter_local_repo_roots(repo_full_name):
        content = utils._get_file_content_by_commit(str(repo_root), commit_sha, file_path)
        if content is not None:
            return content
    return None


def signature_to_base(signature: str) -> str:
    base = (signature or "").strip()
    if not base:
        return ""
    base = base.split(" = ", 1)[0].strip()
    return base.split("(", 1)[0].strip()


def simple_name(signature: str) -> str:
    base = signature_to_base(signature)
    if not base:
        return ""
    return base.rsplit(".", 1)[-1]


def short_label(label: str) -> str:
    base = signature_to_base(label)
    if not base:
        return ""
    parts = base.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else base


def signature_matches_class(signature: str, class_name: str) -> bool:
    sig_base = signature_to_base(signature)
    return bool(sig_base and class_name and (sig_base == class_name or sig_base.startswith(class_name + ".")))


def file_matches(candidate_file: str, patch_files: Iterable[str]) -> bool:
    return any(pf == candidate_file or pf in candidate_file or candidate_file in pf for pf in patch_files)


def method_label_matches(candidate: str, gt_signature: str) -> bool:
    base = signature_to_base(gt_signature)
    if not base:
        return False
    if base == candidate or base.endswith("." + candidate):
        return True
    return short_label(candidate) == short_label(base)


def class_label_matches(candidate: str, gt_class: str) -> bool:
    if gt_class == candidate or gt_class.endswith("." + candidate):
        return True
    return short_label(candidate) == short_label(gt_class)


def patch_hunk_text_by_file(patch_content: str) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    for patched_file in PatchSet(patch_content):
        bucket = out.setdefault(patched_file.path, [])
        for hunk in patched_file:
            for line in hunk:
                # Include hunk context as part of the developer patch evidence.
                bucket.append(line.value)
    return {path: "".join(lines) for path, lines in out.items()}


def extract_identifiers(text: str) -> set[str]:
    identifiers: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("def ") or line.startswith("class "):
            continue
        identifiers.update(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", line))
        identifiers.update(re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)\b", line))
    return {
        token
        for token in identifiers
        if len(token) >= 3
        and not (token.startswith("__") and token.endswith("__"))
        and token not in COMMON_IDENTIFIERS
        and not keyword.iskeyword(token)
    }


def build_support_targets(ids: list[str], gt_map: dict[str, dict], cache_path: Path) -> dict[str, dict]:
    if cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        meta = data.get("_meta", {})
        if meta.get("cache_version") == 2 and all(iid in data.get("items", {}) for iid in ids):
            return data["items"]

    dataset_by_id = load_dataset_by_id(ids)
    items: dict[str, dict] = {}
    for iid in ids:
        item = dataset_by_id[iid]
        gt = gt_map[iid]
        repo_full = item["repo"]
        repo_name = repo_full.split("/")[-1]
        commit_sha = item["base_commit"]
        hunk_text = patch_hunk_text_by_file(item["patch"])
        edit_methods = set(gt.get("found_methods") or [])
        edit_classes = set(gt.get("found_classes") or [])
        support_methods: set[str] = set()

        for patch_file, text in hunk_text.items():
            identifiers = extract_identifiers(text)
            if not identifiers:
                continue
            content = get_local_commit_file_content(repo_full, commit_sha, patch_file) or ""
            classes, methods = utils.get_class_and_method_from_content(content, patch_file, repo_name)
            for method in methods:
                signature = method.get("signature") or ""
                if not signature or signature in edit_methods:
                    continue
                if any(signature_matches_class(signature, cls) for cls in edit_classes):
                    continue
                name = simple_name(signature)
                if name and name in identifiers:
                    support_methods.add(signature)

        items[iid] = {
            "patch_files": gt.get("patch_files") or [],
            "edit_methods": sorted(edit_methods),
            "edit_classes": sorted(edit_classes),
            "gt_entities_n": int(gt.get("gt_entities_n", 0) or 0),
            "fallback_file_target": int(gt.get("fallback_file_target", 0) or 0),
            "support_methods": sorted(support_methods),
            "support_entities_n": len(support_methods),
        }

    payload = {
        "_meta": {
            "cache_version": 2,
            "n": len(items),
            "support_definition": (
                "non-edited function or assignment in an official patched file "
                "whose simple name appears in the official patch hunk text"
            ),
        },
        "items": items,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return items


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
    fp = path / f"{iid}.json"
    if not fp.exists():
        return []
    data = json.loads(fp.read_text(encoding="utf-8"))
    methods = rank_methods((data.get("related_entities") or {}).get("methods") or [])
    out: list[dict] = []
    seen: set[str] = set()
    for method in methods:
        signature = method.get("signature") or ""
        if not signature or signature in seen:
            continue
        seen.add(signature)
        out.append(
            {
                "source": "dir",
                "file_path": method.get("file_path") or "",
                "kind": "method",
                "label": signature,
                "signature": signature,
            }
        )
        if len(out) >= top_limit:
            break
    return out


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def flatten_loc_strings(raw_locs) -> list[str]:
    if raw_locs is None:
        return []
    if isinstance(raw_locs, str):
        raw_locs = [raw_locs]
    out: list[str] = []
    for item in raw_locs:
        lines = item.splitlines() if isinstance(item, str) else [str(item)]
        out.extend(line.strip() for line in lines if line.strip())
    return out


def normalize_loc(loc: str) -> tuple[str, str] | None:
    raw = loc.strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower.startswith("class:"):
        return "class", raw.split(":", 1)[1].strip()
    if lower.startswith("function:"):
        return "function", raw.split(":", 1)[1].strip()
    if lower.startswith("variable:"):
        return "variable", raw.split(":", 1)[1].strip()
    if lower.startswith("line:"):
        return None
    return "unknown", raw


def external_candidates(row: dict | None, top_limit: int = 50) -> list[dict]:
    if row is None:
        return []
    found_files = row.get("found_files") or []
    related = row.get("found_related_locs") or {}
    ranked: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for file_path in found_files:
        for loc in flatten_loc_strings(related.get(file_path) or []):
            norm = normalize_loc(loc)
            if not norm:
                continue
            kind, label = norm
            key = (file_path, kind, label)
            if key in seen:
                continue
            seen.add(key)
            ranked.append({"source": "external", "file_path": file_path, "kind": kind, "label": label})
            if len(ranked) >= top_limit:
                return ranked
    return ranked


def candidate_keys(candidate: dict) -> set[tuple[str, str]]:
    file_path = candidate.get("file_path") or ""
    label = candidate.get("signature") or candidate.get("label") or ""
    keys = {(file_path, signature_to_base(label).lower()), (file_path, short_label(label).lower())}
    return {key for key in keys if key[1]}


def fill_unique(base: list[dict], extra: list[dict], top_k: int) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for candidate in list(base) + list(extra):
        keys = candidate_keys(candidate)
        if seen & keys:
            continue
        seen.update(keys)
        out.append(candidate)
        if len(out) >= top_k:
            break
    return out[:top_k]


def fuse_candidates(primary: list[dict], secondary: list[dict], primary_head: int, kg_head: int, top_k: int) -> list[dict]:
    merged = fill_unique(primary[:primary_head], secondary[:kg_head], top_k)
    if len(merged) < top_k:
        merged = fill_unique(merged, primary[primary_head:], top_k)
    if len(merged) < top_k:
        merged = fill_unique(merged, secondary[kg_head:], top_k)
    return merged[:top_k]


def match_candidate(candidate: dict, targets: dict) -> tuple[set[str], set[str], int]:
    file_path = candidate.get("file_path") or ""
    source = candidate.get("source")
    kind = candidate.get("kind")
    label = candidate.get("label") or ""
    signature = candidate.get("signature") or label
    patch_files = targets["patch_files"]
    edit_methods = set(targets["edit_methods"])
    edit_classes = set(targets["edit_classes"])
    support_methods = set(targets["support_methods"])

    matched_edit: set[str] = set()
    matched_support: set[str] = set()
    fallback_hit = 0

    if source in {"dir", "kg"}:
        if signature in edit_methods:
            matched_edit.add(signature)
        else:
            for class_name in edit_classes:
                if signature_matches_class(signature, class_name):
                    matched_edit.add(class_name)
                    break
        if signature in support_methods:
            matched_support.add(signature)
    else:
        if kind in ("function", "variable", "unknown"):
            for gt_sig in edit_methods:
                if file_matches(file_path, patch_files) and method_label_matches(label, gt_sig):
                    matched_edit.add(gt_sig)
            for support_sig in support_methods:
                if file_matches(file_path, patch_files) and method_label_matches(label, support_sig):
                    matched_support.add(support_sig)
        if kind in ("class", "function", "unknown"):
            for gt_class in edit_classes:
                if file_matches(file_path, patch_files) and class_label_matches(label, gt_class):
                    matched_edit.add(gt_class)

    if targets["fallback_file_target"] and file_matches(file_path, patch_files):
        fallback_hit = 1
    return matched_edit, matched_support, fallback_hit


def evaluate_candidates(
    ids: list[str],
    targets_by_id: dict[str, dict],
    candidates_by_id: dict[str, list[dict]],
    top_k: int,
) -> dict:
    n = 0
    ranked_nonempty = 0
    support_bearing_n = 0
    edit_recall_sum = 0.0
    complete_edit = 0
    edit_hit = 0
    support_recall_sum = 0.0
    context_completeness_sum = 0.0
    context_waste_sum = 0.0

    for iid in ids:
        targets = targets_by_id[iid]
        ranked = candidates_by_id.get(iid, [])[:top_k]
        n += 1
        if ranked:
            ranked_nonempty += 1

        matched_edit: set[str] = set()
        matched_support: set[str] = set()
        fallback_hit = 0
        waste_slots = 0
        for candidate in ranked:
            edit_delta, support_delta, fallback_delta = match_candidate(candidate, targets)
            matched_before = bool(edit_delta or support_delta or fallback_delta)
            matched_edit.update(edit_delta)
            matched_support.update(support_delta)
            fallback_hit = max(fallback_hit, fallback_delta)
            if not matched_before:
                waste_slots += 1

        edit_den = max(1, int(targets["gt_entities_n"]))
        edit_found = fallback_hit if targets["fallback_file_target"] else len(matched_edit)
        support_den = int(targets["support_entities_n"])
        support_found = len(matched_support)
        total_den = edit_den + support_den
        total_found = edit_found + support_found

        edit_recall_sum += edit_found / edit_den
        edit_hit += 1 if edit_found > 0 else 0
        complete_edit += 1 if edit_found >= edit_den else 0
        context_completeness_sum += total_found / max(1, total_den)
        if support_den > 0:
            support_bearing_n += 1
            support_recall_sum += support_found / support_den
        if ranked:
            context_waste_sum += waste_slots / len(ranked)

    return {
        "N": n,
        "ranked_nonempty": ranked_nonempty,
        "support_bearing_N": support_bearing_n,
        "edit_target_recall": edit_recall_sum / n if n else 0.0,
        "complete_edit_target_rate": complete_edit / n if n else 0.0,
        "edit_target_hit_rate": edit_hit / n if n else 0.0,
        "support_context_recall": support_recall_sum / support_bearing_n if support_bearing_n else 0.0,
        "context_completeness": context_completeness_sum / n if n else 0.0,
        "context_waste": context_waste_sum / n if n else 0.0,
    }


def candidates_from_dir(ids: list[str], path: Path, top_limit: int) -> dict[str, list[dict]]:
    return {iid: dir_candidates(path, iid, top_limit=top_limit) for iid in ids}


def maybe_external_rows(
    ids: list[str],
    external_root: Path,
    kg_dir: Path,
    primary_head: int,
    kg_head: int,
    top_k: int,
) -> list[tuple[str, str, str, dict[str, list[dict]]]]:
    cosil_path = external_root / "CoSIL" / "CoSIL_qwen_coder_32b_func.jsonl"
    if not cosil_path.exists():
        return []
    external_map = {row["instance_id"]: row for row in load_jsonl(cosil_path)}
    primary_by_id = {
        iid: external_candidates(external_map.get(iid), top_limit=max(top_k, primary_head))
        for iid in ids
    }
    kg_by_id = {
        iid: dir_candidates(kg_dir, iid, top_limit=max(top_k, kg_head))
        for iid in ids
    }
    fused_by_id = {
        iid: fuse_candidates(primary_by_id[iid], kg_by_id[iid], primary_head, kg_head, top_k)
        for iid in ids
    }
    return [
        ("CoSIL-Qwen2.5-32B", "fusion", str(cosil_path), primary_by_id),
        ("CoSIL-Qwen2.5-32B+KGCompass", "fusion", f"{cosil_path} + {kg_dir}", fused_by_id),
    ]


def main() -> int:
    args = parse_args()
    ids = load_ids(args.ids_file)
    gt_map = load_gt(args.gt_cache)
    targets = build_support_targets(ids, gt_map, args.support_cache)

    row_payloads: list[dict] = []
    configured_rows = [*DEFAULT_ROWS, *(parse_extra_row(raw) for raw in args.row)]
    seen_names: set[str] = set()
    for name, family, source_kind, source in configured_rows:
        if name in seen_names:
            raise ValueError(f"Duplicate evaluation row name: {name}")
        seen_names.add(name)
        if source_kind != "dir":
            raise ValueError(f"Unsupported source kind: {source_kind}")
        path = Path(source)
        candidates_by_id = candidates_from_dir(ids, path, top_limit=args.top_k)
        row_payloads.append(
            {
                "name": name,
                "family": family,
                "source": source,
                **evaluate_candidates(ids, targets, candidates_by_id, args.top_k),
            }
        )

    for name, family, source, candidates_by_id in maybe_external_rows(
        ids,
        args.external_root,
        args.kg_dir,
        args.primary_head,
        args.kg_head,
        args.top_k,
    ):
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
        "ranked_nonempty",
        "support_bearing_N",
        "edit_target_recall",
        "complete_edit_target_rate",
        "edit_target_hit_rate",
        "support_context_recall",
        "context_completeness",
        "context_waste",
        "source",
    ]
    with args.output_tsv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader()
        for row in row_payloads:
            out = dict(row)
            for key in (
                "edit_target_recall",
                "complete_edit_target_rate",
                "edit_target_hit_rate",
                "support_context_recall",
                "context_completeness",
                "context_waste",
            ):
                out[key] = f"{out[key]:.6f}"
            writer.writerow(out)

    meta = {
        "top_k": args.top_k,
        "target_cache": str(args.support_cache),
        "support_definition": (
            "non-edited function or assignment in an official patched file whose simple name "
            "appears in the official patch hunk text"
        ),
        "rows": {row["name"]: row for row in row_payloads},
    }
    args.output_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output_tsv}")
    print(f"wrote {args.output_json}")
    print(f"wrote {args.support_cache}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
