import argparse
import subprocess
import os
from pathlib import Path
from datasets import load_dataset

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


def run_command(cmd: list, **kwargs):
    """便利函数：运行外部命令并实时输出。"""
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description="Mine KG for all instances in a HF dataset")
    parser.add_argument("--dataset", default="princeton-nlp/SWE-bench_Verified", help="HuggingFace dataset name")
    parser.add_argument("--split", default="test", help="Dataset split to load")
    parser.add_argument("--output", default="runs/kg_verified", help="Root directory for KG json files")
    parser.add_argument("--repos_dir", default="playground", help="Directory to clone repos into")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N instances (debug)")
    args = parser.parse_args()

    os.environ.setdefault("PYTHONPATH", os.getcwd())
    output_root = Path(args.output)
    output_root.mkdir(parents=True, exist_ok=True)

    repos_dir = Path(args.repos_dir)
    repos_dir.mkdir(parents=True, exist_ok=True)

    print(f"📦 Loading dataset {args.dataset} ({args.split}) from HuggingFace…")
    ds = load_dataset(args.dataset, split=args.split, streaming=False)

    total = len(ds) if not args.limit else min(args.limit, len(ds))
    for idx, sample in enumerate(ds):
        if args.limit and idx >= args.limit:
            break

        instance_id = sample["instance_id"]
        repo_identifier = instance_id.rsplit("-", 1)[0]
        clone_url = REPO_URL_MAP.get(repo_identifier)
        if not clone_url:
            print(f"❌ Repo identifier {repo_identifier} not found in map, skip.")
            continue

        repo_path = repos_dir / repo_identifier
        if not repo_path.exists():
            print(f"[{idx+1}/{total}] 🌀 Cloning {repo_identifier} …")
            run_command(["git", "clone", "--depth", "1", clone_url, str(repo_path)])
        else:
            print(f"[{idx+1}/{total}] ✅ Repo exists, skip clone.")

        kg_output_dir = output_root / repo_identifier
        kg_output_dir.mkdir(parents=True, exist_ok=True)
        kg_result_file = kg_output_dir / f"{instance_id}.json"
        if kg_result_file.exists():
            print(f"[{idx+1}/{total}] ✅ KG exists for {instance_id}, skipping.")
            continue

        print(f"[{idx+1}/{total}] 🚀 Mining KG for {instance_id} …")
        run_command(["python3", "kgcompass/fl.py", instance_id, repo_identifier, str(kg_output_dir)])
        print(f"[{idx+1}/{total}] 🎉 Saved to {kg_result_file}\n")

    print("===========================================")
    print("🎉 All instances processed (HF mode)")
    print(f"KG json files are in {output_root}")
    print("===========================================")


if __name__ == "__main__":
    main() 