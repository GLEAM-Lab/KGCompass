#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
from typing import Dict, List

from datasets import Dataset
from unidiff import PatchSet

import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "kgcompass"))
import utils  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate multiple control-group directories with calc_prefl-v3 logic."
    )
    parser.add_argument(
        "--ids-file",
        default="SWE-bench_Verified_ids.jsonl",
        help="Instance id list file.",
    )
    parser.add_argument(
        "--group",
        action="append",
        required=True,
        help="Group spec in the form name=dir_path. Repeat for multiple groups.",
    )
    parser.add_argument(
        "--output-tsv",
        default="logs/comparison_current/controls_v3_summary.tsv",
        help="Output TSV path.",
    )
    parser.add_argument(
        "--gt-cache",
        default="temp_run/output/gt_eval_cache_verified_v3_entities.json",
        help="GT cache path for v3 entity-level eval.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=20,
        help="Top-k methods for evaluation (default: 20).",
    )
    return parser.parse_args()


def load_ids(path: Path) -> List[str]:
    out = []
    with path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                out.append(json.loads(line)["instance_id"])
            else:
                out.append(line)
    return out


def discover_arrow() -> Path:
    root = Path.home() / ".cache/huggingface/datasets/princeton-nlp___swe-bench_verified/default/0.0.0"
    cands = sorted(root.glob("*/swe-bench_verified-test.arrow"), key=os.path.getmtime)
    if not cands:
        raise FileNotFoundError("Cannot locate cached SWE-bench verified arrow")
    return cands[-1]


def get_patch_files(patch_content: str) -> List[str]:
    patch = PatchSet(patch_content)
    out = []
    seen = set()
    for patched_file in patch:
        path = patched_file.path
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def parse_patch(file_path: str, patch_content: str) -> List[int]:
    patch = PatchSet(patch_content)
    results = []
    delta = 0
    now_line_no = None
    for patched_file in patch:
        if file_path != patched_file.path:
            continue
        modified_lines = set()
        for hunk in patched_file:
            for line in hunk:
                if line.is_added or line.is_removed:
                    if line.target_line_no:
                        delta -= 1
                        if now_line_no is None:
                            now_line_no = line.target_line_no + delta
                        modified_lines.add(now_line_no)
                    else:
                        now_line_no = None
                        modified_lines.add(line.source_line_no)
                        delta += 1
                else:
                    now_line_no = None
        results.extend(sorted(modified_lines))
    return results


def iter_local_repo_roots(repo_full_name: str):
    repo_id = repo_full_name.replace("/", "__")
    repo_name = repo_full_name.split("/")[-1]
    candidates = [
        REPO_ROOT / "playground" / repo_id,
        REPO_ROOT / "playground" / repo_name,
    ]
    for root in candidates:
        if root.is_dir():
            yield root


def get_local_commit_file_content(repo_full_name: str, commit_sha: str, file_path: str):
    for repo_root in iter_local_repo_roots(repo_full_name):
        content = utils._get_file_content_by_commit(str(repo_root), commit_sha, file_path)
        if content is not None:
            return content
    return None


def extract_gt_entities(item: dict) -> dict:
    patch_files = get_patch_files(item["patch"])
    repo_full = item["repo"]
    commit_sha = item["base_commit"]
    repo_name = repo_full.split("/")[-1]

    found_methods = set()
    found_classes = set()
    for patch_file in patch_files:
        file_content = get_local_commit_file_content(repo_full, commit_sha, patch_file)
        if file_content is None:
            file_content = ""
        classes, methods = utils.get_class_and_method_from_content(file_content, patch_file, repo_name)
        modified_lines = parse_patch(patch_file, item["patch"])
        for line_no in modified_lines:
            matched = False
            for method in methods:
                if method["start_line"] <= line_no <= method["end_line"]:
                    found_methods.add(method["signature"])
                    matched = True
                    break
            if not matched:
                for class_name in classes:
                    if class_name["start_line"] <= line_no <= class_name["end_line"]:
                        found_classes.add(class_name["name"])
                        break

    gt_entities_n = len(found_methods) + len(found_classes)
    fallback_file_target = 1 if gt_entities_n == 0 else 0
    if fallback_file_target:
        gt_entities_n = 1
    return {
        "patch_files": patch_files,
        "found_methods": sorted(found_methods),
        "found_classes": sorted(found_classes),
        "gt_methods_n": len(found_methods),
        "gt_classes_n": len(found_classes),
        "gt_entities_n": gt_entities_n,
        "fallback_file_target": fallback_file_target,
    }


def load_or_build_gt_cache(ids: List[str], cache_path: Path) -> Dict[str, dict]:
    if cache_path.exists():
        data = json.loads(cache_path.read_text())
        if data.get("_meta", {}).get("cache_version") == 3:
            out = data.get("items", {})
            if all(iid in out for iid in ids):
                return out

    arrow = discover_arrow()
    ds = Dataset.from_file(str(arrow))
    id_set = set(ids)
    by_id = {x["instance_id"]: x for x in ds if x.get("instance_id") in id_set}

    out = {}
    for idx, iid in enumerate(ids, start=1):
        out[iid] = extract_gt_entities(by_id[iid])
        if idx % 50 == 0 or idx == len(ids):
            print(f"[gt-v3] {idx}/{len(ids)}", flush=True)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_payload = {
        "_meta": {"cache_version": 3, "n": len(out)},
        "items": out,
    }
    cache_path.write_text(json.dumps(cache_payload, ensure_ascii=False))
    print(f"[gt-v3] cache saved: {cache_path}")
    return out


def signature_to_base(signature: str) -> str:
    base = signature.strip()
    if not base:
        return ""
    base = base.split(" = ", 1)[0].strip()
    base = base.split("(", 1)[0].strip()
    return base


def signature_matches_class(signature: str, class_name: str) -> bool:
    sig_base = signature_to_base(signature)
    if not sig_base or not class_name:
        return False
    if sig_base == class_name:
        return True
    return sig_base.startswith(class_name + ".")


def evaluate_one_instance(location_data: dict, gt: dict, top_k: int) -> dict:
    related = location_data.get("related_entities") or {}
    methods = related.get("methods") or []
    sorted_methods = sorted(methods, key=lambda x: x.get("similarity", 0), reverse=True)

    appear = set()
    cnt = 0
    find_file = 0
    matched_methods = set()
    matched_classes = set()
    found_methods_or_classes_cnt = 0
    first_hit_rank = 0
    fallback_hit = 0

    found_methods = set(gt["found_methods"])
    found_classes = set(gt["found_classes"])
    patch_files = gt["patch_files"]
    use_file_fallback = bool(gt["fallback_file_target"])

    for method_item in sorted_methods[:50]:
        signature = method_item.get("signature")
        if not signature:
            continue
        if signature in appear:
            continue
        appear.add(signature)
        cnt += 1
        if cnt > top_k:
            break

        matched_this_rank = False
        if signature in found_methods and signature not in matched_methods:
            matched_methods.add(signature)
            matched_this_rank = True
        else:
            for class_name in found_classes:
                if class_name in matched_classes:
                    continue
                if signature_matches_class(signature, class_name):
                    matched_classes.add(class_name)
                    matched_this_rank = True
                    break

        if matched_this_rank:
            found_methods_or_classes_cnt += 1
            if first_hit_rank == 0:
                first_hit_rank = cnt

        file_path = method_item.get("file_path") or ""
        if any(patch_file in file_path for patch_file in patch_files):
            find_file = 1
            if use_file_fallback and fallback_hit == 0:
                fallback_hit = 1
                if first_hit_rank == 0:
                    first_hit_rank = cnt

    if use_file_fallback:
        found_methods_or_classes_cnt = fallback_hit

    ratio = found_methods_or_classes_cnt / max(1, int(gt["gt_entities_n"]))
    return {
        "find_file": find_file,
        "ratio": ratio,
        "hit": 1 if found_methods_or_classes_cnt > 0 else 0,
        "best_rank": first_hit_rank if first_hit_rank > 0 else None,
    }


def evaluate_group(group_dir: Path, ids: List[str], gt_map: Dict[str, dict], top_k: int) -> dict:
    n = 0
    file_hits = 0
    method_ratio_sum = 0.0
    hit_cnt = 0
    mrr_sum = 0.0

    for iid in ids:
        fp = group_dir / f"{iid}.json"
        if not fp.exists():
            continue
        data = json.loads(fp.read_text())
        res = evaluate_one_instance(data, gt_map[iid], top_k=top_k)
        n += 1
        file_hits += res["find_file"]
        method_ratio_sum += res["ratio"]
        hit_cnt += res["hit"]
        if res["best_rank"] is not None:
            mrr_sum += 1.0 / res["best_rank"]

    return {
        "N": n,
        "file_rate": file_hits / n if n else 0.0,
        "method_or_entity_rate": method_ratio_sum / n if n else 0.0,
        "top20_hit_rate": hit_cnt / n if n else 0.0,
        "mrr": mrr_sum / n if n else 0.0,
    }


def parse_groups(raw_groups: List[str]) -> List[tuple[str, Path]]:
    out = []
    for raw in raw_groups:
        if "=" not in raw:
            raise ValueError(f"Invalid group spec: {raw}")
        name, path = raw.split("=", 1)
        out.append((name.strip(), Path(path.strip())))
    return out


def main() -> None:
    args = parse_args()
    ids = load_ids(Path(args.ids_file))
    groups = parse_groups(args.group)
    gt_map = load_or_build_gt_cache(ids, Path(args.gt_cache))

    rows = []
    for name, group_dir in groups:
        metrics = evaluate_group(group_dir, ids, gt_map, top_k=args.top_k)
        rows.append((name, str(group_dir), metrics))
        print(f"[done] {name}: N={metrics['N']}, method_or_entity_rate={metrics['method_or_entity_rate']:.6f}")

    rows.sort(
        key=lambda x: (
            x[2]["method_or_entity_rate"],
            x[2]["file_rate"],
            x[2]["mrr"],
        ),
        reverse=True,
    )

    out_path = Path(args.output_tsv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        f.write("name\tN\tfile_rate\tmethod_or_entity_rate\tmrr\ttop20_hit_rate\tdir\n")
        for name, path, m in rows:
            f.write(
                f"{name}\t{m['N']}\t{m['file_rate']:.6f}\t{m['method_or_entity_rate']:.6f}\t"
                f"{m['mrr']:.6f}\t{m['top20_hit_rate']:.6f}\t{path}\n"
            )
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
