#!/usr/bin/env python3
"""Evaluate released Qwen2.5-32B localizers after KGCompass top-10 fusion.

The released strong-baseline artifacts store ranked files plus textual
function/class labels.  This evaluator follows the same fuzzy matching contract
used for the released-baseline table, then appends path-mined KGCompass
candidates under the paper's fixed 10+10 budget.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids-file", type=Path, default=Path("SWE-bench_Verified_ids.jsonl"))
    parser.add_argument(
        "--gt-cache",
        type=Path,
        default=Path("temp_run/output/gt_eval_cache_verified_v3_entities.json"),
    )
    parser.add_argument(
        "--kg-dir",
        type=Path,
        default=Path("runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1"),
    )
    parser.add_argument(
        "--external-root",
        type=Path,
        default=Path("/tmp/kgc_external_baselines/CoSIL/loc_to_patch_verified"),
    )
    parser.add_argument(
        "--output-tsv",
        type=Path,
        default=Path("logs/comparison_current/qwen25_32b_kgcompass_fusion_20260601.tsv"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("logs/comparison_current/qwen25_32b_kgcompass_fusion_20260601.json"),
    )
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--primary-head", type=int, default=10)
    parser.add_argument("--kg-head", type=int, default=20)
    return parser.parse_args()


def load_ids(path: Path) -> list[str]:
    ids: list[str] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            ids.append(json.loads(line)["instance_id"] if line.startswith("{") else line)
    return ids


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_gt(path: Path) -> dict[str, dict]:
    return json.loads(path.read_text())["items"]


def signature_to_base(signature: str) -> str:
    base = (signature or "").strip()
    if not base:
        return ""
    base = base.split(" = ", 1)[0].strip()
    return base.split("(", 1)[0].strip()


def short_label(label: str) -> str:
    base = signature_to_base(label)
    if not base:
        return ""
    parts = base.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else base


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


def signature_matches_class(signature: str, class_name: str) -> bool:
    sig_base = signature_to_base(signature)
    return bool(sig_base and class_name and (sig_base == class_name or sig_base.startswith(class_name + ".")))


def flatten_loc_strings(raw_locs) -> list[str]:
    if raw_locs is None:
        return []
    if isinstance(raw_locs, str):
        raw_locs = [raw_locs]
    out: list[str] = []
    for item in raw_locs:
        if item is None:
            continue
        lines = item.splitlines() if isinstance(item, str) else [str(item)]
        for line in lines:
            line = line.strip()
            if line:
                out.append(line)
    return out


def normalize_loc(loc: str) -> tuple[str, str] | None:
    raw = loc.strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower.startswith("class:"):
        return ("class", raw.split(":", 1)[1].strip())
    if lower.startswith("function:"):
        return ("function", raw.split(":", 1)[1].strip())
    if lower.startswith("variable:"):
        return ("variable", raw.split(":", 1)[1].strip())
    if lower.startswith("line:"):
        return None
    return ("unknown", raw)


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


def kg_candidates(path: Path, top_limit: int = 50) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    methods = sorted(
        ((data.get("related_entities") or {}).get("methods") or []),
        key=lambda item: item.get("similarity", 0.0),
        reverse=True,
    )
    ranked: list[dict] = []
    seen: set[str] = set()
    for method in methods:
        signature = method.get("signature") or ""
        if not signature or signature in seen:
            continue
        seen.add(signature)
        ranked.append(
            {
                "source": "kg",
                "file_path": method.get("file_path") or "",
                "kind": "method",
                "label": signature,
                "signature": signature,
            }
        )
        if len(ranked) >= top_limit:
            break
    return ranked


def candidate_keys(candidate: dict) -> set[tuple[str, str]]:
    file_path = candidate.get("file_path") or ""
    label = candidate.get("signature") or candidate.get("label") or ""
    keys = {(file_path, signature_to_base(label).lower()), (file_path, short_label(label).lower())}
    return {key for key in keys if key[1]}


def fill_unique(base: list[dict], extra: list[dict], top_k: int) -> list[dict]:
    out = list(base)
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for candidate in out:
        keys = candidate_keys(candidate)
        if seen & keys:
            continue
        seen.update(keys)
        deduped.append(candidate)
    out = deduped
    for candidate in extra:
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


def evaluate_candidates(ids: list[str], candidates_by_id: dict[str, list[dict]], gt_map: dict[str, dict], top_k: int) -> dict:
    n = file_hits = hit_cnt = ranked_nonempty = 0
    method_ratio_sum = 0.0
    mrr_sum = 0.0
    for iid in ids:
        gt = gt_map[iid]
        patch_files = gt["patch_files"]
        found_methods = set(gt["found_methods"])
        found_classes = set(gt["found_classes"])
        use_file_fallback = bool(gt["fallback_file_target"])
        ranked = candidates_by_id.get(iid, [])[:top_k]

        matched_methods: set[str] = set()
        matched_classes: set[str] = set()
        found_cnt = 0
        first_hit_rank = 0
        find_file = 0
        fallback_hit = 0

        for rank, candidate in enumerate(ranked, start=1):
            file_path = candidate.get("file_path") or ""
            source = candidate.get("source")
            kind = candidate.get("kind")
            label = candidate.get("label") or ""
            matched_this_rank = False

            if source == "kg":
                signature = candidate.get("signature") or label
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
            else:
                if kind in ("function", "unknown"):
                    for gt_sig in found_methods:
                        if gt_sig in matched_methods:
                            continue
                        if file_matches(file_path, patch_files) and method_label_matches(label, gt_sig):
                            matched_methods.add(gt_sig)
                            matched_this_rank = True
                            break
                if not matched_this_rank and kind in ("class", "function", "unknown"):
                    for gt_class in found_classes:
                        if gt_class in matched_classes:
                            continue
                        if file_matches(file_path, patch_files) and class_label_matches(label, gt_class):
                            matched_classes.add(gt_class)
                            matched_this_rank = True
                            break

            if matched_this_rank:
                found_cnt += 1
                if first_hit_rank == 0:
                    first_hit_rank = rank
            if file_matches(file_path, patch_files):
                find_file = 1
                if use_file_fallback and fallback_hit == 0:
                    fallback_hit = 1
                    if first_hit_rank == 0:
                        first_hit_rank = rank

        if use_file_fallback:
            found_cnt = fallback_hit
        n += 1
        file_hits += find_file
        hit_cnt += 1 if found_cnt else 0
        method_ratio_sum += found_cnt / max(1, int(gt["gt_entities_n"]))
        if first_hit_rank:
            mrr_sum += 1.0 / first_hit_rank
        if ranked:
            ranked_nonempty += 1

    return {
        "N": n,
        "ranked_nonempty": ranked_nonempty,
        "file_rate": file_hits / n if n else 0.0,
        "method_or_entity_rate": method_ratio_sum / n if n else 0.0,
        "mrr": mrr_sum / n if n else 0.0,
        "top20_hit_rate": hit_cnt / n if n else 0.0,
    }


def main() -> None:
    args = parse_args()
    ids = load_ids(args.ids_file)
    gt_map = load_gt(args.gt_cache)
    specs = {
        "CoSIL-Qwen2.5-32B": args.external_root / "CoSIL" / "CoSIL_qwen_coder_32b_func.jsonl",
        "Agentless-Qwen2.5-32B": args.external_root / "agentless" / "agentless_qwen_coder_32b_func.jsonl",
        "LocAgent-Qwen2.5-32B": args.external_root / "locagent" / "locagent_qwen_coder_32b_func.jsonl",
        "OrcaLoca-Qwen2.5-32B": args.external_root / "orcaloca" / "orcaloca_qwen_coder_32b_func.jsonl",
    }

    rows: dict[str, dict] = {}
    meta: dict[str, dict] = {
        "kg_dir": str(args.kg_dir),
        "top_k": args.top_k,
        "primary_head": args.primary_head,
        "kg_head": args.kg_head,
        "external_root": str(args.external_root),
    }
    for name, path in specs.items():
        external_map = {row["instance_id"]: row for row in load_jsonl(path)}
        primary_by_id: dict[str, list[dict]] = {
            iid: external_candidates(external_map.get(iid), top_limit=max(args.top_k, args.primary_head))
            for iid in ids
        }
        kg_by_id: dict[str, list[dict]] = {
            iid: kg_candidates(args.kg_dir / f"{iid}.json", top_limit=max(args.top_k, args.kg_head))
            for iid in ids
        }
        fused_by_id = {
            iid: fuse_candidates(primary_by_id[iid], kg_by_id[iid], args.primary_head, args.kg_head, args.top_k)
            for iid in ids
        }
        rows[name] = {
            "source": str(path),
            **evaluate_candidates(ids, primary_by_id, gt_map, args.top_k),
        }
        rows[f"{name}+KGCompass"] = {
            "source": f"{path} + {args.kg_dir}",
            **evaluate_candidates(ids, fused_by_id, gt_map, args.top_k),
        }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps({"meta": meta, "rows": rows}, ensure_ascii=False, indent=2) + "\n")

    args.output_tsv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_tsv.open("w") as fh:
        fh.write("name\tN\tranked_nonempty\tfile_rate\tmethod_or_entity_rate\tmrr\ttop20_hit_rate\tsource\n")
        for name, metrics in sorted(rows.items(), key=lambda item: item[1]["method_or_entity_rate"], reverse=True):
            fh.write(
                f"{name}\t{metrics['N']}\t{metrics['ranked_nonempty']}\t"
                f"{metrics['file_rate']:.6f}\t{metrics['method_or_entity_rate']:.6f}\t"
                f"{metrics['mrr']:.6f}\t{metrics['top20_hit_rate']:.6f}\t{metrics['source']}\n"
            )
    print(f"wrote {args.output_tsv}")
    print(f"wrote {args.output_json}")


if __name__ == "__main__":
    main()
