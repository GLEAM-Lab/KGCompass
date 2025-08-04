#!/usr/bin/env bash
# mine_kg_bulk.sh
# Script to iterate over instances in the SWE-bench_Verified dataset and run only
# the KG mining (step 1) for each instance.
#
# Usage:
#   bash mine_kg_bulk.sh /path/to/SWE-bench_Verified.jsonl
#   # Optionally specify output directory (defaults to runs/kg_verified)
#   bash mine_kg_bulk.sh /path/to/SWE-bench_Verified.jsonl runs/kg_verified
#
# -----------------------------------------------------------------------------
set -uo pipefail  # 移除 -e，允许单个命令失败而不中断脚本

DATASET_FILE="$1"
OUTPUT_ROOT="${2:-runs/kg_verified}"

if [[ ! -f "$DATASET_FILE" ]]; then
  echo "❌ Dataset file '$DATASET_FILE' not found." >&2
  exit 1
fi

# -----------------------------------------------------------------------------
# Environment Setup (modify as needed)
export PYTHONPATH=$(pwd)
# Uncomment and edit the following lines if you need to set a proxy.
# export http_proxy=http://<proxy>:<port>
# export https_proxy=$http_proxy

# Directory where all Git repositories will be cloned/stored.
REPOS_DIR="playground"
mkdir -p "$REPOS_DIR" "$OUTPUT_ROOT"

# Map of repository identifiers to their clone URLs.
# Extend this map if new repositories are added to the dataset.
# Format: ["owner__repo"]="https://github.com/owner/repo.git"
declare -A REPO_URL_MAP=(
  ["astropy__astropy"]="https://github.com/astropy/astropy.git"
  ["django__django"]="https://github.com/django/django.git"
  ["matplotlib__matplotlib"]="https://github.com/matplotlib/matplotlib.git"
  ["mwaskom__seaborn"]="https://github.com/mwaskom/seaborn.git"
  ["psf__requests"]="https://github.com/psf/requests.git"
  ['pallets__flask']="https://github.com/pallets/flask.git"
  ['pydata__xarray']="https://github.com/pydata/xarray.git"
  ["pylint-dev__pylint"]="https://github.com/pylint-dev/pylint.git"
  ["pytest-dev__pytest"]="https://github.com/pytest-dev/pytest.git"
  ["scikit-learn__scikit-learn"]="https://github.com/scikit-learn/scikit-learn.git"
  ["sphinx-doc__sphinx"]="https://github.com/sphinx-doc/sphinx.git"
  ["sympy__sympy"]="https://github.com/sympy/sympy.git"
)

# -----------------------------------------------------------------------------
# Iterate over each line (JSON object) in the dataset.
# Each line is expected to have a key "instance_id".
# -----------------------------------------------------------------------------
TOTAL=$(wc -l < "$DATASET_FILE")
COUNT=0
while IFS= read -r line; do
  COUNT=$((COUNT + 1))
  INSTANCE_ID=$(jq -r '.instance_id' <<< "$line")
  if [[ "$INSTANCE_ID" == "null" ]]; then
    echo "⚠️  Skipping line $COUNT: no instance_id field."
    continue
  fi

  REPO_IDENTIFIER="${INSTANCE_ID%-*}"
  CLONE_URL="${REPO_URL_MAP[$REPO_IDENTIFIER]:-}"   # Empty if not found

  if [[ -z "$CLONE_URL" ]]; then
    echo "❌ Repo identifier '$REPO_IDENTIFIER' not found in REPO_URL_MAP. Update the map and re-run." >&2
    exit 1
  fi

  REPO_PATH="${REPOS_DIR}/${REPO_IDENTIFIER}"
  FETCH_DONE_FILE="${REPO_PATH}/.fetch_done"
  
  # Clone repository if not already present
  if [[ ! -d "$REPO_PATH" ]]; then
    echo "[$COUNT/$TOTAL] 🌀 Cloning $REPO_IDENTIFIER ... (full history, this may take a while)"
    git clone "$CLONE_URL" "$REPO_PATH"
    # 标记已完成 fetch，避免重复操作
    touch "$FETCH_DONE_FILE"
  else
    echo "[$COUNT/$TOTAL] ✅ Repo exists, skip clone."
  fi

  # 只在第一次或者没有标记文件时才 fetch
  if [[ ! -f "$FETCH_DONE_FILE" ]]; then
    echo "[$COUNT/$TOTAL] 🔄 Fetching latest commits for $REPO_IDENTIFIER ..."
    git -C "$REPO_PATH" fetch --unshallow 2>/dev/null || git -C "$REPO_PATH" fetch --all --tags
    touch "$FETCH_DONE_FILE"
  fi

  # Output directory for KG results per repository
  KG_OUTPUT_DIR="${OUTPUT_ROOT}/${REPO_IDENTIFIER}"
  mkdir -p "$KG_OUTPUT_DIR"
  KG_RESULT_FILE="${KG_OUTPUT_DIR}/${INSTANCE_ID}.json"

  if [[ -f "$KG_RESULT_FILE" ]]; then
    echo "[$COUNT/$TOTAL] ✅ KG already exists for $INSTANCE_ID, skipping."
    continue
  fi

  echo "[$COUNT/$TOTAL] 🚀 Mining KG for $INSTANCE_ID ..."
  python3 kgcompass/fl.py "$INSTANCE_ID" "$REPO_IDENTIFIER" "$KG_OUTPUT_DIR"
  echo "[$COUNT/$TOTAL] 🎉 KG saved to $KG_RESULT_FILE"

done < "$DATASET_FILE"

echo "======================================================"
echo "✅ All instances processed. KG files stored in '$OUTPUT_ROOT'"
echo "======================================================" 
