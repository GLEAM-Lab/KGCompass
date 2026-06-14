import argparse
import json
import subprocess
import os
from datetime import datetime
from pathlib import Path
import time

from kgcompass.config import DECAY_FACTOR, VECTOR_SIMILARITY_WEIGHT

REPO_URL_MAP = {
    "astropy__astropy": "https://github.com/astropy/astropy.git",
    "django__django": "https://github.com/django/django.git",
    "matplotlib__matplotlib": "https://github.com/matplotlib/matplotlib.git",
    "mwaskom__seaborn": "https://github.com/mwaskom/seaborn.git",
    "pallets__flask": "https://github.com/pallets/flask.git",
    "psf__requests": "https://github.com/psf/requests.git",
    "pydata__xarray": "https://github.com/pydata/xarray.git",
    "pylint-dev__pylint": "https://github.com/pylint-dev/pylint.git",
    "pytest-dev__pytest": "https://github.com/pytest-dev/pytest.git",
    "scikit-learn__scikit-learn": "https://github.com/scikit-learn/scikit-learn.git",
    "sphinx-doc__sphinx": "https://github.com/sphinx-doc/sphinx.git",
    "sympy__sympy": "https://github.com/sympy/sympy.git",
}

DEFAULT_PARAM_CONFIG_PATH = ""
DEFAULT_SNAPSHOT_CONFIG_PATH = "kg_snapshot_config.json"
FL_RETRY_ATTEMPTS = 3
FL_RETRY_SLEEP_SECONDS = 5


def run_cmd(cmd: list):
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def apply_evidence_graph_environment_defaults():
    """Set paper-valid defaults inherited by fl.py/export subprocesses."""
    defaults = {
        "HF_DATASETS_OFFLINE": "1",
        "HF_HUB_OFFLINE": "1",
        "KGCOMPASS_EXPAND_PATCH_LINKS": "0",
        "KGCOMPASS_USE_TIMELINE": "0",
        "KGCOMPASS_ENABLE_DOC_CONTEXT": "0",
        "KGCOMPASS_ENABLE_DOC_SYMBOL_CONTEXT": "0",
        "KGCOMPASS_ENABLE_REPAIR_EXPERIENCE_CONTEXT": "0",
        "KGCOMPASS_ENABLE_COMMIT_CONTEXT": "0",
        "KGCOMPASS_ENABLE_TAG_CONTEXT": "0",
        "KGCOMPASS_ENABLE_METHOD_CALL_EXPANSION": "0",
        "KGCOMPASS_STRICT_IDENTIFIER_FILTER": "1",
        "KGCOMPASS_NAME_SEARCH_STRICT": "1",
        "FL_SCAN_CURRENT_LANG_ONLY": "1",
        "FL_SCAN_EXCLUDE_NONPROD_CONTEXT": "1",
        "KGCOMPASS_SOURCE_EXTENSIONS": ".py",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _repo_identifier_from_instance(instance_id: str) -> str:
    return instance_id.rsplit("-", 1)[0]


def ensure_repo_ready(repo_identifier: str, repos_dir: Path, fetch_remote: bool):
    clone_url = REPO_URL_MAP.get(repo_identifier)
    if not clone_url:
        return False
    repo_path = repos_dir / repo_identifier
    if not repo_path.exists():
        print(f"🌀 Pre-cloning {repo_identifier} ...")
        run_cmd(["git", "clone", clone_url, str(repo_path)])
    if fetch_remote:
        run_cmd(["git", "-C", str(repo_path), "fetch", "--all", "--tags"])
    return True


def run_fl_with_retries(
    instance_id: str,
    repo_identifier: str,
    output_dir: Path,
    repo_path: Path,
):
    last_error = None
    for attempt in range(1, FL_RETRY_ATTEMPTS + 1):
        try:
            run_cmd(
                ["python3", "kgcompass/fl.py", instance_id, repo_identifier, str(output_dir)]
            )
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            print(f"⚠️  fl.py failed (attempt {attempt}/{FL_RETRY_ATTEMPTS}).")
            if attempt < FL_RETRY_ATTEMPTS:
                print("🧹 Cleaning repo and retrying...")
                run_cmd(["git", "-C", str(repo_path), "reset", "--hard"])
                run_cmd(["git", "-C", str(repo_path), "clean", "-fd"])
                time.sleep(FL_RETRY_SLEEP_SECONDS)
            else:
                print("❌ fl.py failed after retries.")
                raise last_error


def dump_neo4j_snapshot(
    instance_id: str,
    snapshot_dir: Path,
    container: str,
    database: str,
    stop_db: bool,
):
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_file = snapshot_dir / f"{instance_id}.dump"
    if snapshot_file.exists():
        print(f"📦 Snapshot exists for {instance_id}, skipping.")
        return

    container_dump_dir = "/data/dumps"
    dump_name = f"{instance_id}.dump"
    dump_src = f"{container_dump_dir}/{database}.dump"
    dump_dst = f"{container_dump_dir}/{dump_name}"

    run_cmd(["docker", "exec", container, "mkdir", "-p", container_dump_dir])

    stopped = False
    try:
        if stop_db:
            print("🧊 Stopping Neo4j for snapshot...")
            try:
                run_cmd(["docker", "exec", container, "neo4j", "stop"])
                stopped = True
            except subprocess.CalledProcessError as exc:
                print(f"⚠️  neo4j stop failed (exit {exc.returncode}), continuing.")

        if stop_db and not stopped:
            print("⚠️  Neo4j is still running; skip snapshot to avoid corrupt dump.")
            return

        run_cmd(
            [
                "docker",
                "exec",
                container,
                "neo4j-admin",
                "dump",
                f"--database={database}",
                f"--to={dump_src}",
            ]
        )
        run_cmd(["docker", "exec", container, "rm", "-f", dump_dst])
        run_cmd(["docker", "exec", container, "mv", dump_src, dump_dst])
    finally:
        if stop_db and stopped:
            print("🔥 Starting Neo4j after snapshot...")
            run_cmd(["docker", "exec", container, "neo4j", "start"])

    run_cmd(["docker", "cp", f"{container}:{dump_dst}", str(snapshot_file)])
    print(f"📦 Saved snapshot: {snapshot_file}")


def _outputs_exist_for_param_pairs(instance_id: str, output_root: Path, param_pairs: list) -> bool:
    for raw_pair in param_pairs:
        tag = raw_pair.split(":", 1)[0]
        output_file = output_root / tag / f"{instance_id}.json"
        if not output_file.exists():
            return False
    return True


def _missing_param_pairs(instance_id: str, output_root: Path, param_pairs: list) -> list:
    missing = []
    for raw_pair in param_pairs:
        tag = raw_pair.split(":", 1)[0]
        output_file = output_root / tag / f"{instance_id}.json"
        if not output_file.exists():
            missing.append(raw_pair)
    return missing


def _missing_ablation_param_pairs(
    instance_id: str,
    ablation_output_root: Path,
    param_pairs: list,
    ablations: list,
) -> list:
    """
    Return param pairs where at least one ablation output is missing.
    Ablation output layout:
      <ablation_output_root>/<ablation_tag>/<param_tag>/<instance_id>.json
    """
    missing = []
    if not ablations:
        return missing

    for raw_pair in param_pairs:
        param_tag = raw_pair.split(":", 1)[0]
        has_missing = False
        for raw_ablation in ablations:
            ablation_tag = raw_ablation.split(":", 1)[0]
            output_file = ablation_output_root / ablation_tag / param_tag / f"{instance_id}.json"
            if not output_file.exists():
                has_missing = True
                break
        if has_missing:
            missing.append(raw_pair)
    return missing


def _get_param_pairs(args) -> list:
    if args.param_pair:
        return args.param_pair

    if args.param_config and args.param_config != "" and os.path.exists(args.param_config):
        with open(args.param_config, "r") as f:
            pair_config = json.load(f)
        return [f"{item['tag']}:{item['decay']},{item['sim']}" for item in pair_config]

    return [f"{args.param_tag}:{args.decay_factor},{args.vector_similarity_weight}"]


def process_instance(
    instance_id: str,
    repos_dir: Path,
    output_root: Path,
    idx: int,
    total: int,
    param_pairs: list,
    ablations: list,
    ablation_output_root: Path,
    fetch_remote: bool,
    export_param_workers: int,
    evidence_graph: bool = False,
    evidence_tag: str = "evidence_graph",
    evidence_limit: int = None,
    force: bool = False,
):
    repo_identifier = _repo_identifier_from_instance(instance_id)
    if evidence_graph:
        output_file = output_root / evidence_tag / f"{instance_id}.json"
        if (not force) and output_file.exists():
            print(f"[{idx}/{total}] ✅ Evidence-graph output exists for {instance_id}, skipping.")
            return False

    missing_pairs = []
    missing_ablation_pairs = []
    if (not force) and param_pairs:
        missing_pairs = _missing_param_pairs(instance_id, output_root, param_pairs)
        missing_ablation_pairs = _missing_ablation_param_pairs(
            instance_id,
            ablation_output_root,
            param_pairs,
            ablations,
        )
        if not missing_pairs and not missing_ablation_pairs:
            print(f"[{idx}/{total}] ✅ All param outputs exist for {instance_id}, skipping.")
            return False

    if (not force) and (not param_pairs) and (not evidence_graph):
        kg_output_dir = output_root / repo_identifier
        kg_output_dir.mkdir(parents=True, exist_ok=True)
        result_file = kg_output_dir / f"{instance_id}.json"
        if result_file.exists():
            print(f"[{idx}/{total}] ✅ KG exists for {instance_id}, skipping.")
            return False

    clone_url = REPO_URL_MAP.get(repo_identifier)
    if not clone_url:
        print(f"❌ Repo identifier {repo_identifier} not found, skipping {instance_id}.")
        return False

    repo_path = repos_dir / repo_identifier
    if not repo_path.exists():
        print(f"[{idx}/{total}] 🌀 Cloning {repo_identifier} … (full history, this may take a while)")
        run_cmd(["git", "clone", clone_url, str(repo_path)])
    else:
        print(f"[{idx}/{total}] ✅ Repo exists, skip clone.")

    # 仅在显式要求时更新远程历史
    if fetch_remote:
        run_cmd(["git", "-C", str(repo_path), "fetch", "--all", "--tags"])

    # 执行 KG 挖掘
    print(f"[{idx}/{total}] 🚀 Mining KG for {instance_id} …")
    if evidence_graph:
        build_output_dir = output_root / "_build" / repo_identifier
        build_output_dir.mkdir(parents=True, exist_ok=True)
        run_fl_with_retries(instance_id, repo_identifier, build_output_dir, repo_path)

        export_cmd = [
            "python3",
            "kgcompass/export_kg_evidence_graph.py",
            instance_id,
            str(output_root),
            "--tag",
            evidence_tag,
        ]
        if evidence_limit is not None:
            export_cmd.extend(["--limit", str(evidence_limit)])
        run_cmd(export_cmd)
        print(f"[{idx}/{total}] 🎉 Evidence-graph saved to {output_file}\n")
    elif param_pairs:
        build_output_dir = output_root / "_build" / repo_identifier
        build_output_dir.mkdir(parents=True, exist_ok=True)
        # Correctness first: export reads the *current* Neo4j graph state.
        # A historical _build JSON does not guarantee Neo4j currently holds this instance graph.
        run_fl_with_retries(instance_id, repo_identifier, build_output_dir, repo_path)

        pairs_to_export = param_pairs if force else missing_pairs
        if pairs_to_export:
            print(f"[{idx}/{total}] 🧭 Exporting {len(pairs_to_export)} param pairs …")
            export_cmd = [
                "python3",
                "kgcompass/export_kg_sweep.py",
                instance_id,
                str(output_root),
            ]
            if export_param_workers and export_param_workers > 1:
                export_cmd.extend(["--param-workers", str(export_param_workers)])
            for raw_pair in pairs_to_export:
                export_cmd.extend(["--param-pair", raw_pair])
            run_cmd(export_cmd)
        else:
            print(f"[{idx}/{total}] ✅ No missing main param outputs for {instance_id}.")

        if ablations:
            ablation_pairs_to_export = param_pairs if force else missing_ablation_pairs
            if ablation_pairs_to_export:
                print(
                    f"[{idx}/{total}] 🧪 Exporting ablation for {len(ablation_pairs_to_export)} param pairs …"
                )
                ablation_cmd = [
                    "python3",
                    "kgcompass/export_kg_ablation.py",
                    instance_id,
                    str(ablation_output_root),
                ]
                if export_param_workers and export_param_workers > 1:
                    ablation_cmd.extend(["--param-workers", str(export_param_workers)])
                for raw_pair in ablation_pairs_to_export:
                    ablation_cmd.extend(["--param-pair", raw_pair])
                for raw_ablation in ablations:
                    ablation_cmd.extend(["--ablation", raw_ablation])
                run_cmd(ablation_cmd)
            else:
                print(f"[{idx}/{total}] ✅ No missing ablation outputs for {instance_id}.")

        print(f"[{idx}/{total}] 🎉 Exported for {instance_id}\n")
    else:
        run_fl_with_retries(instance_id, repo_identifier, kg_output_dir, repo_path)
        print(f"[{idx}/{total}] 🎉 Saved to {result_file}\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="Bulk KG mining from a JSONL list of instance_id")
    parser.add_argument("jsonl_file", help="Path to JSONL file containing at least 'instance_id'")
    parser.add_argument("--output", default="runs/kg_verified", help="Output root directory for KG json")
    parser.add_argument(
        "--run-tag",
        default=None,
        help="Optional subdirectory name under --output (e.g. 20250101_120000 or expA)",
    )
    parser.add_argument(
        "--separate-run",
        action="store_true",
        help="Auto-create a timestamped subdirectory under --output for each batch run",
    )
    parser.add_argument("--repos_dir", default="playground", help="Directory to clone repos into")
    parser.add_argument("--limit", type=int, default=None, help="Debug: process only first N instances")
    parser.add_argument(
        "--fetch-remote",
        action="store_true",
        help="Fetch remote git history before mining each instance.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild/export even if output files already exist.",
    )
    parser.add_argument(
        "--param-pair",
        action="append",
        help=(
            "Fixed decay/sim pair, format TAG:DECAY,SIM. "
            "Multiple pairs are blocked unless --allow-sweep is set. If omitted, "
            "falls back to --param-tag/decay-factor/vector-similarity-weight."
        ),
    )
    parser.add_argument(
        "--param-tag",
        default="1006",
        help="Fallback param tag when --param-pair is not provided.",
    )
    parser.add_argument(
        "--decay-factor",
        type=float,
        default=DECAY_FACTOR,
        help=f"Fallback decay factor when --param-pair is not provided (default: {DECAY_FACTOR}).",
    )
    parser.add_argument(
        "--vector-similarity-weight",
        type=float,
        default=VECTOR_SIMILARITY_WEIGHT,
        help=(
            "Fallback vector similarity weight when --param-pair is not provided "
            f"(default: {VECTOR_SIMILARITY_WEIGHT})."
        ),
    )
    parser.add_argument(
        "--param-config",
        default=DEFAULT_PARAM_CONFIG_PATH,
        help=(
            "Optional JSON config file for decay/sim pairs. Disabled by default; "
            "configs with multiple pairs require --allow-sweep."
        ),
    )
    parser.add_argument(
        "--allow-sweep",
        action="store_true",
        help="Allow exporting multiple parameter pairs. Keep off for paper-valid fixed runs.",
    )
    parser.add_argument(
        "--snapshot-config",
        default=DEFAULT_SNAPSHOT_CONFIG_PATH,
        help="Path to JSON config file for Neo4j snapshot.",
    )
    parser.add_argument(
        "--export-param-workers",
        type=int,
        default=1,
        help="Parallel workers inside export_kg_sweep.py for param pairs (default: 1).",
    )
    parser.add_argument(
        "--evidence-graph",
        action="store_true",
        help=(
            "Use the TSE no-sweep evidence-graph export path. This disables "
            "decay/similarity param export and writes <output>/<evidence-tag>/<instance>.json."
        ),
    )
    parser.add_argument(
        "--evidence-tag",
        default="evidence_graph",
        help="Output tag for --evidence-graph mode (default: evidence_graph).",
    )
    parser.add_argument(
        "--evidence-limit",
        type=int,
        default=None,
        help="Optional candidate limit passed to export_kg_evidence_graph.py.",
    )
    parser.add_argument(
        "--ablation-config",
        default=None,
        help=(
            "Optional JSON config file for ablation modes. "
            "Format: [{\"tag\": \"full\", \"mode\": \"full\"}, ...]"
        ),
    )
    parser.add_argument(
        "--ablation-output",
        default=None,
        help=(
            "Optional output root for ablation JSONs. "
            "Default: <output_root>/_ablation"
        ),
    )
    args = parser.parse_args()

    os.environ.setdefault("PYTHONPATH", os.getcwd())

    output_root = Path(args.output)
    if args.run_tag:
        output_root = output_root / args.run_tag
    elif args.separate_run:
        run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_root = output_root / run_tag
    output_root.mkdir(parents=True, exist_ok=True)
    repos_dir = Path(args.repos_dir); repos_dir.mkdir(parents=True, exist_ok=True)

    param_pairs = [] if args.evidence_graph else _get_param_pairs(args)
    if args.evidence_graph:
        apply_evidence_graph_environment_defaults()
    if len(param_pairs) > 1 and not args.allow_sweep:
        raise SystemExit(
            "Refusing to export multiple parameter pairs without --allow-sweep. "
            "Use a single --param-pair/--param-tag for fixed experiments."
        )

    ablations = []
    if args.ablation_config:
        if args.evidence_graph:
            raise SystemExit("--ablation-config is not supported with --evidence-graph.")
        with open(args.ablation_config, "r") as f:
            ablation_config = json.load(f)
        ablations = [f"{item['tag']}:{item['mode']}" for item in ablation_config]

    ablation_output_root = (
        Path(args.ablation_output)
        if args.ablation_output
        else (output_root / "_ablation")
    )
    if ablations:
        ablation_output_root.mkdir(parents=True, exist_ok=True)

    snapshot_config = {
        "enabled": False,
    }
    if os.path.exists(args.snapshot_config):
        with open(args.snapshot_config, "r") as f:
            snapshot_config = json.load(f)

    with open(args.jsonl_file, 'r') as f:
        lines = f.readlines()

    total = len(lines) if args.limit is None else min(args.limit, len(lines))
    tasks = []
    for idx, line in enumerate(lines[:total], start=1):
        try:
            data = json.loads(line)
            instance_id = data.get('instance_id')
            if not instance_id:
                print(f"⚠️  Line {idx} missing instance_id, skip.")
                continue
            tasks.append((idx, instance_id))
        except json.JSONDecodeError:
            print(f"⚠️  Invalid JSON on line {idx}, skip.")
            continue

    # Pre-warm repositories once to avoid clone/fetch races in parallel mode.
    unique_repo_ids = sorted({_repo_identifier_from_instance(x[1]) for x in tasks})
    for repo_identifier in unique_repo_ids:
        if repo_identifier not in REPO_URL_MAP:
            continue
        ensure_repo_ready(repo_identifier, repos_dir, fetch_remote=args.fetch_remote)

    for idx, instance_id in tasks:
        did_run = process_instance(
            instance_id,
            repos_dir,
            output_root,
            idx,
            total,
            param_pairs,
            ablations,
            ablation_output_root,
            fetch_remote=args.fetch_remote,
            export_param_workers=args.export_param_workers,
            evidence_graph=args.evidence_graph,
            evidence_tag=args.evidence_tag,
            evidence_limit=args.evidence_limit,
            force=args.force,
        )
        if did_run and snapshot_config.get("enabled"):
            snapshot_dir = Path(snapshot_config.get("output_dir", str(output_root / "_snapshots")))
            dump_neo4j_snapshot(
                instance_id,
                snapshot_dir,
                snapshot_config.get("container", "kgcompass-neo4j"),
                snapshot_config.get("database", "neo4j"),
                snapshot_config.get("stop_db", True),
            )

    print("===========================================")
    print("🎉 All instances processed (JSONL mode)")
    print(f"KG json files are in {output_root}")
    print("===========================================")


if __name__ == "__main__":
    main()
