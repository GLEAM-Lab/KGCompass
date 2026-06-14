#!/usr/bin/env bash
set -euo pipefail

SESSION="${1:-kg_tse_clean_resume_20260529}"
JSON_DIR="${2:-runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6}"
AUDIT_JSON="${3:-logs/kg_clean_final_audit.json}"
LOG_FILE="${4:-logs/kg_clean_watch.log}"
JSONL_FILE="${JSONL_FILE:-SWE-bench_Verified_ids.jsonl}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$(dirname "$JSON_DIR")}"
TAG="${TAG:-$(basename "$JSON_DIR")}"
FL_LOG_DIR="${FL_LOG_DIR:-logs/calc_prefl_evidence_graph_tse_timesafe_main_20260529_v6}"
RUN_LOG="${RUN_LOG:-logs/tse_timesafe_main_20260529_v6_resume_autowatch.log}"
CHECK_INTERVAL="${CHECK_INTERVAL:-300}"
MAX_RESTARTS="${MAX_RESTARTS:-20}"
SLACK_SCRIPT="${SLACK_SCRIPT:-/home/barty/.codex/skills/slack-reminder-notify/scripts/send_slack_reminder_notice.py}"
FINALIZE_SCRIPT="${FINALIZE_SCRIPT:-scripts/finalize_clean_kg_localization.sh}"

mkdir -p "$(dirname "$AUDIT_JSON")" "$(dirname "$LOG_FILE")" "$(dirname "$RUN_LOG")"

expected_count="$(wc -l < "$JSONL_FILE" | tr -d ' ')"

start_resume_session() {
  tmux new-session -d -s "$SESSION" \
    "cd /home/barty/GLEAM-Lab/KGCompass && env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u DASHSCOPE_API_KEY -u MOONSHOT_API_KEY -u BAILIAN_API_KEY -u DEEPSEEK_API_KEY -u QWEN_API_KEY KGCOMPASS_LOAD_DOTENV=0 KGCOMPASS_EMBEDDING_DEVICE=cuda:0 HF_DATASETS_OFFLINE=1 HF_HUB_OFFLINE=1 bash run_evidence_graph_resume.sh '$JSONL_FILE' '$OUTPUT_ROOT' '$TAG' '$FL_LOG_DIR' 2>&1 | tee -a '$RUN_LOG'"
}

restart_count=0

echo "[$(date -Is)] watching tmux session: $SESSION" | tee -a "$LOG_FILE"
while true; do
  while tmux has-session -t "$SESSION" 2>/dev/null; do
    sleep "$CHECK_INTERVAL"
    count=$(find "$JSON_DIR" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
    echo "[$(date -Is)] still running; json_count=$count/$expected_count" | tee -a "$LOG_FILE"
  done

  count=$(find "$JSON_DIR" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$count" == "$expected_count" ]]; then
    break
  fi

  if [[ "$restart_count" -ge "$MAX_RESTARTS" ]]; then
    summary="KGCompass clean localization stopped before completion: json_count=$count/$expected_count, restarts=$restart_count/$MAX_RESTARTS"
    echo "[$(date -Is)] $summary" | tee -a "$LOG_FILE"
    if [[ "${SLACK_NOTIFY:-1}" == "1" && -x "$SLACK_SCRIPT" ]]; then
      python3 "$SLACK_SCRIPT" --message "$summary" --json >>"$LOG_FILE" 2>&1 || true
    fi
    exit 1
  fi

  restart_count=$((restart_count + 1))
  echo "[$(date -Is)] session ended early; restarting $SESSION (json_count=$count/$expected_count, restart=$restart_count/$MAX_RESTARTS)" | tee -a "$LOG_FILE"
  start_resume_session
  sleep 5
done

count=$(find "$JSON_DIR" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
audit_status=0
PRE_AUDIT_JSON="${AUDIT_JSON}.pre_rerun"
RERUN_IDS_FILE="logs/${TAG}_content_issue_rerun_ids.jsonl"

python3 scripts/audit_kg_leakage.py "$JSON_DIR" --output-json "$PRE_AUDIT_JSON" \
  >>"$LOG_FILE" 2>&1 || true
python3 - "$PRE_AUDIT_JSON" "$RERUN_IDS_FILE" <<'PY' >>"$LOG_FILE" 2>&1
import json
import sys
from pathlib import Path

audit_path = Path(sys.argv[1])
ids_path = Path(sys.argv[2])
report = json.loads(audit_path.read_text())
summary = report.get("summary", report)
items = summary.get("content_issue_instances") or []
ids_path.parent.mkdir(parents=True, exist_ok=True)
with ids_path.open("w") as fh:
    for item in items:
        instance_id = item.get("instance_id")
        if instance_id:
            fh.write(json.dumps({"instance_id": instance_id}) + "\n")
print(f"[watch] content issue rerun ids: {len(items)} -> {ids_path}")
PY

if [[ -s "$RERUN_IDS_FILE" ]]; then
  rerun_count="$(wc -l < "$RERUN_IDS_FILE" | tr -d ' ')"
  echo "[$(date -Is)] rerunning $rerun_count content-issue instances before finalization" | tee -a "$LOG_FILE"
  env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u DASHSCOPE_API_KEY -u MOONSHOT_API_KEY \
    -u BAILIAN_API_KEY -u DEEPSEEK_API_KEY -u QWEN_API_KEY \
    KGCOMPASS_LOAD_DOTENV=0 KGCOMPASS_EMBEDDING_DEVICE=cuda:0 \
    HF_DATASETS_OFFLINE=1 HF_HUB_OFFLINE=1 \
    python3 mine_kg_bulk.py "$RERUN_IDS_FILE" --output "$OUTPUT_ROOT" \
      --evidence-graph --evidence-tag "$TAG" --force >>"$LOG_FILE" 2>&1 || audit_status=$?
  cache_file="$JSON_DIR/_prefl_cache.jsonl"
  if [[ -f "$cache_file" ]]; then
    echo "[$(date -Is)] removing stale FL cache after content-issue rerun: $cache_file" | tee -a "$LOG_FILE"
    rm -f "$cache_file"
  fi
fi

if [[ -x "$FINALIZE_SCRIPT" ]]; then
  bash "$FINALIZE_SCRIPT" "$JSONL_FILE" "$OUTPUT_ROOT" "$TAG" \
    "$FL_LOG_DIR" "$AUDIT_JSON" \
    "logs/comparison_current/kg_clean_$TAG" >>"$LOG_FILE" 2>&1 || audit_status=$?
else
  python3 scripts/audit_kg_leakage.py "$JSON_DIR" --output-json "$AUDIT_JSON" --fail-on-issue \
    >>"$LOG_FILE" 2>&1 || audit_status=$?
fi

summary="KGCompass clean localization run ended: json_count=$count/$expected_count, finalize_status=$audit_status, audit=$AUDIT_JSON"
echo "[$(date -Is)] $summary" | tee -a "$LOG_FILE"

if [[ "${SLACK_NOTIFY:-1}" == "1" && -x "$SLACK_SCRIPT" ]]; then
  python3 "$SLACK_SCRIPT" --message "$summary" --json >>"$LOG_FILE" 2>&1 || true
fi
