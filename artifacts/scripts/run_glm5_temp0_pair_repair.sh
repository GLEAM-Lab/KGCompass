#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/barty/GLEAM-Lab/KGCompass}"
IDS_FILE="${IDS_FILE:-$ROOT/temp_run/SWE-bench_Verified_ids.jsonl}"
DATASET_JSONL="${DATASET_JSONL:-$ROOT/temp_run/generated/SWE-bench_Verified.jsonl}"
REPAIR_ROOT="${REPAIR_ROOT:-$ROOT/repair_runs_glm5_verified_temp0_pair}"
PRED_ROOT="${PRED_ROOT:-$ROOT/predictions_glm5_verified_temp0_pair}"
OFFICIAL_ROOT="${OFFICIAL_ROOT:-$ROOT/official_glm5_verified_temp0_pair}"
LOG_DIR="${LOG_DIR:-$ROOT/logs/glm5_verified_temp0_pair}"
PLAYGROUND_DIR="${PLAYGROUND_DIR:-$ROOT/playground}"
OFFICIAL_NAMESPACE="${OFFICIAL_NAMESPACE:-logicstar}"
OFFICIAL_MAX_WORKERS="${OFFICIAL_MAX_WORKERS:-8}"
OFFICIAL_TIMEOUT="${OFFICIAL_TIMEOUT:-1800}"
RUN_LIMIT="${RUN_LIMIT:-}"
SKIP_EVAL="${SKIP_EVAL:-0}"
SEND_SLACK_NOTIFY="${SEND_SLACK_NOTIFY:-0}"
SLACK_NOTIFY_SCRIPT="${SLACK_NOTIFY_SCRIPT:-/home/barty/.codex/skills/slack-reminder-notify/scripts/send_slack_reminder_notice.py}"

ROUND_TAG="r1_c20_t0"
MODEL_NAME="glm-5"

NO_KG_FL_DIR="${NO_KG_FL_DIR:-$ROOT/temp_run/eval_aliyun_glm5_issueonly}"
KG_FL_DIR="${KG_FL_DIR:-$ROOT/temp_run/fusions_pathmined_kg/GLM5_pathunion_ht10}"

mkdir -p "$REPAIR_ROOT" "$PRED_ROOT" "$OFFICIAL_ROOT" "$LOG_DIR"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export HF_DATASETS_OFFLINE="${HF_DATASETS_OFFLINE:-1}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export KGCOMPASS_LOAD_DOTENV=0
export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"
export no_proxy="${no_proxy:-127.0.0.1,localhost}"

expected_count="$(wc -l < "$IDS_FILE" | tr -d ' ')"
if [[ -z "$RUN_LIMIT" && "$expected_count" != "500" ]]; then
  echo "Expected 500 benchmark ids, got $expected_count from $IDS_FILE" >&2
  exit 2
fi

variant_fl_dir() {
  case "$1" in
    noKG_top20) printf '%s\n' "$NO_KG_FL_DIR" ;;
    KG_10p10_top20) printf '%s\n' "$KG_FL_DIR" ;;
    *) echo "Unsupported variant=$1" >&2; exit 2 ;;
  esac
}

run_generation_variant() {
  local variant="$1"
  local fl_dir
  fl_dir="$(variant_fl_dir "$variant")"
  local variant_repair_root="$REPAIR_ROOT/$variant"
  local log_file="$LOG_DIR/glm5_${variant}_${ROUND_TAG}.log"

  if [[ ! -d "$fl_dir" ]]; then
    echo "FL input missing for $variant: $fl_dir" >&2
    exit 2
  fi

  local limit_args=()
  if [[ -n "$RUN_LIMIT" ]]; then
    limit_args=(--limit "$RUN_LIMIT")
  fi

  echo "[glm5][$variant] generation start round=$ROUND_TAG fl=$fl_dir output=$variant_repair_root" | tee -a "$log_file"
  python3 -u "$ROOT/temp_run/run_open_repair_rounds.py" \
    --preset glm5 \
    --fl-input-dir "$fl_dir" \
    --dataset-kind verified \
    --dataset-jsonl "$DATASET_JSONL" \
    --instance-list-file "$IDS_FILE" \
    "${limit_args[@]}" \
    --rounds "$ROUND_TAG" \
    --output-root "$variant_repair_root" \
    --playground-dir "$PLAYGROUND_DIR" \
    --skip-existing-empty \
    2>&1 | tee -a "$log_file"
  echo "[glm5][$variant] generation done" | tee -a "$log_file"
}

collect_and_eval_variant() {
  local variant="$1"
  local variant_repair_root="$REPAIR_ROOT/$variant"
  local pred_dir="$PRED_ROOT/$variant/$ROUND_TAG"
  local pred_path="$pred_dir/predictions.jsonl"
  local collect_summary="$pred_dir/collect_summary.json"
  local official_dir="$OFFICIAL_ROOT/$variant/$ROUND_TAG"
  local log_file="$LOG_DIR/glm5_${variant}_${ROUND_TAG}.log"
  mkdir -p "$pred_dir" "$official_dir"

  python3 "$ROOT/temp_run/collect_open_repair_predictions.py" \
    --ids-file "$IDS_FILE" \
    --repair-root "$variant_repair_root" \
    --preset glm5 \
    --output-jsonl "$pred_path" \
    --summary-json "$collect_summary" \
    --model-name "${MODEL_NAME}_${variant}_${ROUND_TAG}" \
    --round "$ROUND_TAG" \
    2>&1 | tee -a "$log_file"

  if [[ "$SKIP_EVAL" == "1" ]]; then
    echo "[glm5][$variant] SKIP_EVAL=1, official evaluation skipped" | tee -a "$log_file"
    return 0
  fi

  python3 "$ROOT/temp_run/eval_official_predictions_jsonl.py" \
    --predictions-path "$pred_path" \
    --dataset-kind verified \
    --dataset-jsonl "$DATASET_JSONL" \
    --output-root "$official_dir" \
    --run-id "glm5-temp0-${variant}-${ROUND_TAG}" \
    --max-workers "$OFFICIAL_MAX_WORKERS" \
    --timeout "$OFFICIAL_TIMEOUT" \
    --namespace "$OFFICIAL_NAMESPACE" \
    2>&1 | tee -a "$log_file"
}

for variant in noKG_top20 KG_10p10_top20; do
  run_generation_variant "$variant"
done

for variant in noKG_top20 KG_10p10_top20; do
  collect_and_eval_variant "$variant"
done

if [[ "$SEND_SLACK_NOTIFY" == "1" && -f "$SLACK_NOTIFY_SCRIPT" ]]; then
  notify_message="$(
    python3 - <<PY
import json
from pathlib import Path
root = Path("$OFFICIAL_ROOT")
parts = []
for variant in ["noKG_top20", "KG_10p10_top20"]:
    p = root / variant / "$ROUND_TAG" / "summary.json"
    if p.exists():
        d = json.loads(p.read_text())
        parts.append(f"{variant}: resolved={d.get('resolved')}/{d.get('predictions')}, nonempty={d.get('patch_nonempty')}, missing={d.get('missing_report')}")
    else:
        parts.append(f"{variant}: summary missing")
print("KGCompass GLM-5 temp0 repair pair finished; " + "; ".join(parts))
PY
  )"
  python3 "$SLACK_NOTIFY_SCRIPT" --message "$notify_message" --json || true
fi

echo "[done] GLM-5 temp0 pair finished: noKG_top20 KG_10p10_top20"
