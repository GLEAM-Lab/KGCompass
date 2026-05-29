#!/usr/bin/env bash
set -euo pipefail

JSONL_FILE="${1:-SWE-bench_Verified_ids.jsonl}"
OUTPUT_ROOT="${2:-runs/kg_verified_evidence_graph}"
TAG="${3:-evidence_graph}"
LOG_DIR="${4:-logs/calc_prefl_evidence_graph}"

export HF_DATASETS_OFFLINE="${HF_DATASETS_OFFLINE:-1}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export KGCOMPASS_LOAD_DOTENV=0
unset OPENAI_API_KEY ANTHROPIC_API_KEY DASHSCOPE_API_KEY MOONSHOT_API_KEY BAILIAN_API_KEY DEEPSEEK_API_KEY QWEN_API_KEY
if [[ -z "${GITHUB_TOKEN:-}" && "${KGCOMPASS_DISABLE_GITHUB_TOKEN:-0}" != "1" && -f .env ]]; then
  github_token_line="$(grep -m1 '^GITHUB_TOKEN=' .env || true)"
  if [[ -n "$github_token_line" ]]; then
    github_token_value="${github_token_line#GITHUB_TOKEN=}"
    github_token_value="${github_token_value%\"}"
    github_token_value="${github_token_value#\"}"
    github_token_value="${github_token_value%\'}"
    github_token_value="${github_token_value#\'}"
    export GITHUB_TOKEN="$github_token_value"
  fi
fi
export KGCOMPASS_OFFLINE_ARTIFACTS="${KGCOMPASS_OFFLINE_ARTIFACTS:-0}"
export KGCOMPASS_EXPAND_PATCH_LINKS="${KGCOMPASS_EXPAND_PATCH_LINKS:-0}"
export KGCOMPASS_USE_TIMELINE="${KGCOMPASS_USE_TIMELINE:-0}"
export KGCOMPASS_ENABLE_DOC_CONTEXT="${KGCOMPASS_ENABLE_DOC_CONTEXT:-0}"
export KGCOMPASS_ENABLE_DOC_SYMBOL_CONTEXT="${KGCOMPASS_ENABLE_DOC_SYMBOL_CONTEXT:-0}"
export KGCOMPASS_ENABLE_REPAIR_EXPERIENCE_CONTEXT="${KGCOMPASS_ENABLE_REPAIR_EXPERIENCE_CONTEXT:-0}"
export KGCOMPASS_ENABLE_COMMIT_CONTEXT="${KGCOMPASS_ENABLE_COMMIT_CONTEXT:-0}"
export KGCOMPASS_ENABLE_TAG_CONTEXT="${KGCOMPASS_ENABLE_TAG_CONTEXT:-0}"
export KGCOMPASS_ENABLE_METHOD_CALL_EXPANSION="${KGCOMPASS_ENABLE_METHOD_CALL_EXPANSION:-0}"
export KGCOMPASS_STRICT_IDENTIFIER_FILTER="${KGCOMPASS_STRICT_IDENTIFIER_FILTER:-1}"
export KGCOMPASS_NAME_SEARCH_STRICT="${KGCOMPASS_NAME_SEARCH_STRICT:-1}"
export FL_SCAN_CURRENT_LANG_ONLY="${FL_SCAN_CURRENT_LANG_ONLY:-1}"
export FL_SCAN_EXCLUDE_NONPROD_CONTEXT="${FL_SCAN_EXCLUDE_NONPROD_CONTEXT:-1}"
export KGCOMPASS_SOURCE_EXTENSIONS="${KGCOMPASS_SOURCE_EXTENSIONS:-.py}"

echo "[1/2] Mine + export no-sweep evidence graph (resume supported by skip-existing)..."
python3 mine_kg_bulk.py "$JSONL_FILE" \
  --output "$OUTPUT_ROOT" \
  --evidence-graph \
  --evidence-tag "$TAG"

echo "[2/2] Evaluate FL coverage for evidence graph..."
RUN_IDS="$TAG" bash run_fl.sh "$OUTPUT_ROOT" "$LOG_DIR"

echo "Done. Output root: $OUTPUT_ROOT ; tag: $TAG ; logs: $LOG_DIR"
