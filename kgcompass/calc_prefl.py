import argparse
import json
import sys
import os
from glob import glob
from datasets import load_dataset, DownloadConfig
from unidiff import PatchSet
import utils
from config import DATASET_NAME, GITHUB_TOKEN

PREFL_CACHE_VERSION = 3
UNAVAILABLE_BENCHMARK_FIELDS = {"hint_text", "hints_text"}


def _strip_unavailable_benchmark_fields(item):
    return {k: v for k, v in dict(item).items() if k not in UNAVAILABLE_BENCHMARK_FIELDS}


def _load_json_or_jsonl(path):
    with open(path, "r") as f:
        text = f.read().strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [_strip_unavailable_benchmark_fields(item) for item in parsed]
        if isinstance(parsed, dict):
            for key in ("test", "instances", "data"):
                value = parsed.get(key)
                if isinstance(value, list):
                    return [_strip_unavailable_benchmark_fields(item) for item in value]
            if "instance_id" in parsed:
                return [_strip_unavailable_benchmark_fields(parsed)]
        raise ValueError(f"Unsupported JSON dataset shape in {path}")
    except json.JSONDecodeError:
        rows = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(_strip_unavailable_benchmark_fields(json.loads(line)))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL line {line_no} in {path}: {exc}") from exc
        return rows


def _load_eval_dataset(dataset_jsonl=None):
    if dataset_jsonl:
        return _load_json_or_jsonl(dataset_jsonl)
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    return [
        _strip_unavailable_benchmark_fields(item)
        for item in load_dataset(
            DATASET_NAME,
            download_config=DownloadConfig(local_files_only=True),
        )["test"]
    ]

def count_path_start_type(type_cnt, path_item):
    start_type = path_item.get('start_type')
    start_node = path_item.get('start_node')
    if start_type:
        if start_type == 'issue':
            if isinstance(start_node, str) and start_node.startswith('pr#'):
                type_cnt['pr'] = type_cnt.get('pr', 0) + 1
            else:
                type_cnt['issue'] = type_cnt.get('issue', 0) + 1
        else:
            type_cnt[start_type] = type_cnt.get(start_type, 0) + 1
        return

    if not start_node:
        type_cnt['unknown'] = type_cnt.get('unknown', 0) + 1
        return
    if '.py' in start_node:
        type_cnt['file'] = type_cnt.get('file', 0) + 1
    elif 'issue#' in start_node:
        type_cnt['issue'] = type_cnt.get('issue', 0) + 1
    elif 'pr#' in start_node:
        type_cnt['pr'] = type_cnt.get('pr', 0) + 1
    else:
        node_name = start_node
        if node_name[0].isupper():
            if node_name.isupper():
                type_cnt['const'] = type_cnt.get('const', 0) + 1
            else:
                type_cnt['class'] = type_cnt.get('class', 0) + 1
        else:
            type_cnt['method'] = type_cnt.get('method', 0) + 1

def get_patch_file(patch_content):
    patch = PatchSet(patch_content)
    file_paths = []
    seen = set()
    for patched_file in patch:
        file_path = patched_file.path
        if file_path in seen:
            continue
        seen.add(file_path)
        file_paths.append(file_path)
    return file_paths

def parse_patch(file_path, patch_content):
    patch = PatchSet(patch_content)
    results = []
    delta = 0
    now_line_no = None
    for patched_file in patch:
        now_file_path = patched_file.path
        if file_path != now_file_path:
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
        results.extend(sorted(list(modified_lines)))

    return results

def _iter_local_repo_roots(repo_full_name):
    repo_id = repo_full_name.replace("/", "__")
    repo_name = repo_full_name.split("/")[-1]
    cwd = os.getcwd()
    candidates = [
        os.path.join(cwd, "playground", repo_id),
        os.path.join(cwd, "playground", repo_name),
    ]
    for repo_root in candidates:
        if os.path.isdir(repo_root):
            yield repo_root


def _get_local_commit_file_content(repo_full_name, commit_sha, file_path):
    for repo_root in _iter_local_repo_roots(repo_full_name):
        content = utils._get_file_content_by_commit(repo_root, commit_sha, file_path)
        if content is not None:
            return content
    return None


def get_class_and_method_from_patch(
    patch_content,
    repo_full_name,
    commit_sha,
    github_repo=None,
    commit=None,
):
    patch_files = get_patch_file(patch_content)
    if not patch_files:
        return [], set(), set(), "missing_patch_file"
    repo_name = repo_full_name.split("/")[-1]

    found_methods = set()
    found_classes = set()
    used_github = False
    missing_file_count = 0

    for patch_file in patch_files:
        # Prefer local commit content to avoid network dependency.
        file_content = _get_local_commit_file_content(repo_full_name, commit_sha, patch_file)
        if file_content is None and github_repo is not None and commit is not None:
            file_content = utils.get_commit_file(github_repo, commit, patch_file)
            if file_content is not None:
                used_github = True
        if file_content is None:
            # Keep legacy behavior: continue with empty content when file cannot
            # be resolved at the target commit (e.g., added/renamed paths).
            file_content = ""
            missing_file_count += 1

        classes, methods = utils.get_class_and_method_from_content(file_content, patch_file, repo_name)
        modified_lines = parse_patch(patch_file, patch_content)
        for line_no in modified_lines:
            find = False
            for method in methods:
                if method['start_line'] <= line_no <= method['end_line']:
                    found_methods.add(method['signature'])
                    find = True
                    break
            if not find:
                for class_name in classes:
                    if class_name['start_line'] <= line_no <= class_name['end_line']:
                        found_classes.add(class_name['name'])
                        break

    if missing_file_count == len(patch_files):
        content_source = "missing_file_content"
    elif missing_file_count > 0:
        content_source = "partial_missing_file_content"
    elif used_github:
        content_source = "github"
    else:
        content_source = "local"

    return patch_files, found_methods, found_classes, content_source


def _merge_count_dict(target, delta):
    for key, value in delta.items():
        target[key] = target.get(key, 0) + value


def _normalize_count_dict(data):
    normalized = {}
    for key, value in data.items():
        try:
            normalized_key = int(key)
        except (TypeError, ValueError):
            normalized_key = key
        normalized[normalized_key] = value
    return normalized

def _signature_to_base(signature):
    if not isinstance(signature, str):
        return ""
    base = signature.strip()
    if not base:
        return ""
    # Handle assignment-like signatures first, then call signatures.
    base = base.split(" = ", 1)[0].strip()
    base = base.split("(", 1)[0].strip()
    return base

def _signature_matches_class(signature, class_name):
    sig_base = _signature_to_base(signature)
    if not sig_base or not class_name:
        return False
    if sig_base == class_name:
        return True
    return sig_base.startswith(class_name + ".")


def _apply_cache_entry(entry, totals):
    if not entry.get("tot_included"):
        return
    totals["tot"] += 1
    totals["tot_find_file"] += entry.get("find_file", 0)
    totals["tot_find_method_or_class"] += entry.get("found_methods_ratio", 0.0)
    totals["morethanone"] += entry.get("morethanone", 0)
    _merge_count_dict(totals["ranks"], _normalize_count_dict(entry.get("ranks", {})))
    _merge_count_dict(totals["lengths"], _normalize_count_dict(entry.get("lengths", {})))
    _merge_count_dict(totals["type_cnt"], entry.get("type_cnt", {}))
    if entry.get("find_file", 0) == 0 and entry.get("instance_id"):
        totals["failed_instance_ids"].append(entry["instance_id"])


def _rank_location_items(items):
    if any("similarity" in item for item in items):
        return sorted(items, key=lambda x: x.get("similarity", float("-inf")), reverse=True)
    return list(items)


def _location_path(item):
    return item.get("path") or item.get("path_details") or []


def _write_cache_entry(cache_fh, entry):
    entry.setdefault("cache_version", PREFL_CACHE_VERSION)
    cache_fh.write(json.dumps(entry) + "\n")
    cache_fh.flush()


def _print_summary(totals):
    total = totals["tot"]
    if total == 0:
        print("FL File count: 0, total: 0, rate: 0")
        print("FL Method or Class count: 0, total: 0, rate: 0")
        print("No included instances; check location files, dataset rows, or cache status.")
    else:
        print(
            f"FL File count: {totals['tot_find_file']}, total: {total}, "
            f"rate: {totals['tot_find_file'] / total}"
        )
        print(
            f"FL Method or Class count: {totals['tot_find_method_or_class']}, "
            f"total: {total}, rate: {totals['tot_find_method_or_class'] / total}"
        )
    print("========== Figure 6 ==========")
    for i in range(1, 21):
        print("Rank: ", i, "; Cnt: ", totals["ranks"].get(i, 0))

    print("========== Figure 7 ==========")
    for typ in totals["type_cnt"]:
        print("Type: ", typ, "; Cnt: ", totals["type_cnt"][typ])

    print("========== Figure 8 ==========")
    for i in range(1, 5):
        print("Length: ", i, "; Cnt: ", totals["lengths"].get(i, 0))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-id",
        help="Run folder name under runs/kg_verified (e.g., 0603).",
    )
    parser.add_argument(
        "--base-dir",
        default="runs/kg_verified",
        help="Base directory that contains run folders or JSON files.",
    )
    parser.add_argument(
        "--cache-file",
        default=None,
        help="JSONL cache file to resume calc without re-fetching data.",
    )
    parser.add_argument(
        "--allow-github-fallback",
        action="store_true",
        help="If local commit file lookup fails, fallback to GitHub API.",
    )
    parser.add_argument(
        "--dataset-jsonl",
        default=os.getenv("SWE_BENCH_VERIFIED_JSONL"),
        help="Optional local SWE-bench-style JSON/JSONL dataset file. Hint fields are stripped.",
    )
    parser.add_argument(
        "--only-instance",
        action="append",
        default=[],
        help="Restrict evaluation to one instance_id. Can be repeated for smoke tests.",
    )
    args = parser.parse_args()

    tot_find_file = 0
    tot_find_method_or_class = 0
    tot = 0
    morethanone = 0
    g = None
    ds = _load_eval_dataset(args.dataset_jsonl)
    if args.only_instance:
        only_instances = set(args.only_instance)
        ds = [item for item in ds if item.get("instance_id") in only_instances]
    ok = False
    totals = {
        "tot_find_file": 0,
        "tot_find_method_or_class": 0.0,
        "tot": 0,
        "morethanone": 0,
        "ranks": {},
        "failed_instance_ids": [],
        "lengths": {},
        "type_cnt": {},
    }

    # 收集所有 JSON 文件并建立 instance_id -> filepath 的映射
    base_dir = args.base_dir
    if args.run_id:
        base_dir = os.path.join(base_dir, args.run_id)
    cache_file = args.cache_file or os.path.join(base_dir, "_prefl_cache.jsonl")
    cache_parent = os.path.dirname(cache_file)
    if cache_parent:
        os.makedirs(cache_parent, exist_ok=True)
    location_files = {}
    json_paths = set(glob(os.path.join(base_dir, "*.json")))
    json_paths.update(glob(os.path.join(base_dir, "*/*.json")))
    for json_file in sorted(json_paths):
        # 从文件名提取 instance_id (去掉 .json 后缀)
        instance_id = os.path.splitext(os.path.basename(json_file))[0]
        location_files[instance_id] = json_file
    print(f"Found {len(location_files)} location files in {base_dir}")

    cache_by_id = {}
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("cache_version") != PREFL_CACHE_VERSION:
                    continue
                instance_id = entry.get("instance_id")
                if instance_id:
                    cache_by_id[instance_id] = entry
        for entry in cache_by_id.values():
            _apply_cache_entry(entry, totals)

    cache_fh = open(cache_file, "a")

    for item in ds:
        instance_id = item['instance_id']
        if instance_id in cache_by_id:
            print(f"[cache] {instance_id} loaded")
            continue
        repo = item['repo']
        commit_id = item['base_commit']
        github_repo = None
        commit = None
        if args.allow_github_fallback:
            if g is None:
                g = utils.create_github_client(GITHUB_TOKEN)
            github_repo = g.get_repo(repo)
            commit = github_repo.get_commit(commit_id)
        patch_files, found_methods, found_classes, content_source = get_class_and_method_from_patch(
            item['patch'],
            repo,
            commit_id,
            github_repo=github_repo,
            commit=commit,
        )
        if content_source == "missing_patch_file":
            print(
                f"Warning: failed to resolve patch source for {instance_id} "
                f"({repo}@{commit_id}, source={content_source}), skipping..."
            )
            _write_cache_entry(
                cache_fh,
                {
                    "instance_id": instance_id,
                    "status": content_source,
                    "tot_included": False,
                },
            )
            continue
        if content_source in {"missing_file_content", "partial_missing_file_content"}:
            print(
                f"Warning: patch file content missing for {instance_id} "
                f"({repo}@{commit_id}, source={content_source}); continue with empty content."
            )
        # 使用映射查找文件
        if instance_id not in location_files:
            print(f"Warning: No location file found for {instance_id}, skipping...")
            _write_cache_entry(
                cache_fh,
                {
                    "instance_id": instance_id,
                    "status": "missing_location",
                    "tot_included": False,
                },
            )
            continue
        location_file_name = location_files[instance_id]
        location_data = json.load(open(location_file_name, 'r'))
        find_file = 0
        cnt = 0
        found_methods_or_classes_cnt = 0
        matched_methods = set()
        matched_classes = set()
        has_gt_entities = bool(found_methods or found_classes)
        use_file_fallback = not has_gt_entities
        find = False
        appear = set()
        ranks_delta = {}
        type_cnt_delta = {}
        lengths_delta = {}
        fallback_hit = 0
        if 'methods' in location_data['related_entities']:
            sorted_methods = _rank_location_items(location_data['related_entities']['methods'])
            for method_item in sorted_methods[:50]:
                signature = method_item.get('signature')
                if not signature:
                    continue
                if signature in appear:
                    continue
                appear.add(signature)
                cnt += 1
                if cnt > 20:
                    break
                matched_this_rank = False
                if signature in found_methods and signature not in matched_methods:
                    matched_methods.add(signature)
                    matched_this_rank = True
                else:
                    for class_name in found_classes:
                        if class_name in matched_classes:
                            continue
                        if _signature_matches_class(signature, class_name):
                            matched_classes.add(class_name)
                            matched_this_rank = True
                            break
                if matched_this_rank:
                    path = _location_path(method_item)
                    print('path length is ', len(path))
                    ranks_delta[cnt] = ranks_delta.get(cnt, 0) + 1
                    find = True
                    for path_item in path[1:]:
                        count_path_start_type(type_cnt_delta, path_item)
                    lengths_delta[len(path)] = lengths_delta.get(len(path), 0) + 1
                    found_methods_or_classes_cnt += 1
                if any(patch_file in (method_item.get('file_path') or '') for patch_file in patch_files):
                    find_file = 1
                    if use_file_fallback and fallback_hit == 0:
                        path = _location_path(method_item)
                        fallback_hit = 1
                        ranks_delta[cnt] = ranks_delta.get(cnt, 0) + 1
                        find = True
                        for path_item in path[1:]:
                            count_path_start_type(type_cnt_delta, path_item)
                        lengths_delta[len(path)] = lengths_delta.get(len(path), 0) + 1
        if not find:
            ranks_delta[0] = ranks_delta.get(0, 0) + 1
        if find_file == 0:
            totals["failed_instance_ids"].append(instance_id)
        if use_file_fallback:
            found_methods_or_classes_cnt = fallback_hit
        if found_methods_or_classes_cnt > 0:
            totals["morethanone"] += 1

        gt_entities_n = len(found_methods) + len(found_classes)
        if use_file_fallback:
            gt_entities_n = 1
        found_methods_ratio = found_methods_or_classes_cnt / max(1, gt_entities_n)
        _merge_count_dict(totals["ranks"], ranks_delta)
        _merge_count_dict(totals["type_cnt"], type_cnt_delta)
        _merge_count_dict(totals["lengths"], lengths_delta)
        totals["tot_find_file"] += find_file
        totals["tot"] += 1
        totals["tot_find_method_or_class"] += found_methods_ratio
        _print_summary(totals)
        print(f"FL Method/Class at least one: {totals['morethanone']}")

        cache_entry = {
            "cache_version": PREFL_CACHE_VERSION,
            "instance_id": instance_id,
            "status": "ok",
            "tot_included": True,
            "find_file": find_file,
            "found_methods_ratio": found_methods_ratio,
            "morethanone": 1 if found_methods_or_classes_cnt > 0 else 0,
            "gt_methods_n": len(found_methods),
            "gt_classes_n": len(found_classes),
            "gt_entities_n": gt_entities_n,
            "fallback_file_target": 1 if use_file_fallback else 0,
            "matched_methods_n": len(matched_methods),
            "matched_classes_n": len(matched_classes),
            "ranks": ranks_delta,
            "type_cnt": type_cnt_delta,
            "lengths": lengths_delta,
        }
        _write_cache_entry(cache_fh, cache_entry)

    cache_fh.close()
    _print_summary(totals)
