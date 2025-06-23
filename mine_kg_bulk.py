import argparse
import json
import subprocess
import os
from pathlib import Path

REPO_URL_MAP = {
    "astropy__astropy": "https://github.com/astropy/astropy.git",
    "django__django": "https://github.com/django/django.git",
    "matplotlib__matplotlib": "https://github.com/matplotlib/matplotlib.git",
    "mwaskom__seaborn": "https://github.com/mwaskom/seaborn.git",
    "psf__requests": "https://github.com/psf/requests.git",
    "pylint-dev__pylint": "https://github.com/pylint-dev/pylint.git",
    "pytest-dev__pytest": "https://github.com/pytest-dev/pytest.git",
    "scikit-learn__scikit-learn": "https://github.com/scikit-learn/scikit-learn.git",
    "sphinx-doc__sphinx": "https://github.com/sphinx-doc/sphinx.git",
    "sympy__sympy": "https://github.com/sympy/sympy.git",
}


def run_cmd(cmd: list):
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def process_instance(instance_id: str, repos_dir: Path, output_root: Path, idx: int, total: int):
    repo_identifier = instance_id.rsplit('-', 1)[0]
    kg_output_dir = output_root / repo_identifier
    kg_output_dir.mkdir(parents=True, exist_ok=True)
    result_file = kg_output_dir / f"{instance_id}.json"
    if result_file.exists():
        print(f"[{idx}/{total}] ✅ KG exists for {instance_id}, skipping.")
        return

    clone_url = REPO_URL_MAP.get(repo_identifier)
    if not clone_url:
        print(f"❌ Repo identifier {repo_identifier} not found, skipping {instance_id}.")
        return

    repo_path = repos_dir / repo_identifier
    if not repo_path.exists():
        print(f"[{idx}/{total}] 🌀 Cloning {repo_identifier} … (full history, this may take a while)")
        run_cmd(["git", "clone", clone_url, str(repo_path)])
    else:
        print(f"[{idx}/{total}] ✅ Repo exists, skip clone.")

    # 确保目标提交存在：获取最新远程历史（如果之前已浅克隆，此步骤会补全缺失提交）
    run_cmd(["git", "-C", str(repo_path), "fetch", "--all", "--tags"])

    # 执行 KG 挖掘
    print(f"[{idx}/{total}] 🚀 Mining KG for {instance_id} …")
    run_cmd(["python3", "kgcompass/fl.py", instance_id, repo_identifier, str(kg_output_dir)])
    print(f"[{idx}/{total}] 🎉 Saved to {result_file}\n")


def main():
    parser = argparse.ArgumentParser(description="Bulk KG mining from a JSONL list of instance_id")
    parser.add_argument("jsonl_file", help="Path to JSONL file containing at least 'instance_id'")
    parser.add_argument("--output", default="runs/kg_verified", help="Output root directory for KG json")
    parser.add_argument("--repos_dir", default="playground", help="Directory to clone repos into")
    parser.add_argument("--limit", type=int, default=None, help="Debug: process only first N instances")
    args = parser.parse_args()

    os.environ.setdefault("PYTHONPATH", os.getcwd())

    output_root = Path(args.output); output_root.mkdir(parents=True, exist_ok=True)
    repos_dir = Path(args.repos_dir); repos_dir.mkdir(parents=True, exist_ok=True)

    with open(args.jsonl_file, 'r') as f:
        lines = f.readlines()

    total = len(lines) if not args.limit else min(args.limit, len(lines))
    for idx, line in enumerate(lines[:total], start=1):
        try:
            data = json.loads(line)
            instance_id = data.get('instance_id')
            if not instance_id:
                print(f"⚠️  Line {idx} missing instance_id, skip.")
                continue
            process_instance(instance_id, repos_dir, output_root, idx, total)
        except json.JSONDecodeError:
            print(f"⚠️  Invalid JSON on line {idx}, skip.")
            continue

    print("===========================================")
    print("🎉 All instances processed (JSONL mode)")
    print(f"KG json files are in {output_root}")
    print("===========================================")


if __name__ == "__main__":
    main() 