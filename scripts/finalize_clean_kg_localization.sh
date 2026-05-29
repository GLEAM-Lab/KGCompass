#!/usr/bin/env bash
set -euo pipefail

JSONL_FILE="${1:-SWE-bench_Verified_ids.jsonl}"
OUTPUT_ROOT="${2:-runs/kg_verified_evidence_graph}"
TAG="${3:-tse_timesafe_main_20260529_v6}"
LOG_DIR="${4:-logs/calc_prefl_evidence_graph_tse_timesafe_main_20260529_v6}"
AUDIT_JSON="${5:-logs/kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json}"
SUMMARY_PREFIX="${6:-logs/comparison_current/kg_clean_${TAG}}"

JSON_DIR="$OUTPUT_ROOT/$TAG"
CACHE_FILE="$JSON_DIR/_prefl_cache.jsonl"
STATUS_JSON="${SUMMARY_PREFIX}_status.json"
SUMMARY_JSON="${SUMMARY_PREFIX}_summary.json"
SUMMARY_TSV="${SUMMARY_PREFIX}_summary.tsv"
RQ3_JSON="${SUMMARY_PREFIX}_rq3.json"
RQ3_TSV="${SUMMARY_PREFIX}_rq3.tsv"
RQ3_PATH_PNG="${SUMMARY_PREFIX}_rq3_pathlength.png"
RQ3_RANK_PNG="${SUMMARY_PREFIX}_rq3_gt_rank.png"
LLM_FUSION_TSV="logs/comparison_current/llm_clean_${TAG}.tsv"
LLM_FUSION_STATUS="logs/comparison_current/llm_clean_${TAG}_status.json"
LATEX_SNIPPETS="logs/comparison_current/clean_tse_${TAG}_latex_snippets.tex"
PAPER_FIGURES_DIR="external/kgcompass-paper/figures"

export KGCOMPASS_LOAD_DOTENV=0
unset OPENAI_API_KEY ANTHROPIC_API_KEY DASHSCOPE_API_KEY MOONSHOT_API_KEY BAILIAN_API_KEY DEEPSEEK_API_KEY QWEN_API_KEY

mkdir -p "$(dirname "$AUDIT_JSON")" "$(dirname "$SUMMARY_PREFIX")"

expected_count="$(wc -l < "$JSONL_FILE" | tr -d ' ')"
json_count="$(find "$JSON_DIR" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"

echo "[finalize] json_count=$json_count/$expected_count"
python3 scripts/audit_kg_leakage.py "$JSON_DIR" --output-json "$AUDIT_JSON" --fail-on-issue

if [[ "$json_count" != "$expected_count" ]]; then
  echo "[finalize] warning: KG JSON count is incomplete; summary will reflect available instances only" >&2
fi

cache_entry_count=0
cache_unique_count=0
cache_complete=0
if [[ -f "$CACHE_FILE" ]]; then
  cache_entry_count="$(wc -l < "$CACHE_FILE" | tr -d ' ')"
  read -r cache_unique_count cache_complete < <(python3 - "$JSONL_FILE" "$CACHE_FILE" <<'PY'
import json
import sys
from pathlib import Path

ids_file = Path(sys.argv[1])
cache_file = Path(sys.argv[2])
expected = set()
with ids_file.open() as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            expected.add(json.loads(line)["instance_id"])
        else:
            expected.add(line)

seen = set()
with cache_file.open() as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("cache_version") != 3:
            continue
        instance_id = entry.get("instance_id")
        if instance_id in expected:
            seen.add(instance_id)

print(len(seen), int(expected.issubset(seen)))
PY
)
fi

if [[ "$cache_complete" == "1" ]]; then
  echo "[finalize] FL coverage cache covers all expected instances ($cache_unique_count/$expected_count unique, $cache_entry_count rows); reusing it"
elif [[ ! -f "$CACHE_FILE" ]] || ! grep -q "\"status\": \"ok\"" "$CACHE_FILE"; then
  echo "[finalize] running FL coverage because cache is missing or empty ($cache_unique_count/$expected_count unique, $cache_entry_count rows)"
  RUN_IDS="$TAG" RESUME=0 bash run_fl.sh "$OUTPUT_ROOT" "$LOG_DIR"
else
  echo "[finalize] resuming FL coverage to fill missing cache entries ($cache_unique_count/$expected_count unique, $cache_entry_count rows)"
  RUN_IDS="$TAG" RESUME=0 bash run_fl.sh "$OUTPUT_ROOT" "$LOG_DIR"
fi

python3 scripts/summarize_prefl_cache.py "$CACHE_FILE" --name "KG_clean_${TAG}" > "$SUMMARY_JSON"
python3 scripts/summarize_prefl_cache.py "$CACHE_FILE" --name "KG_clean_${TAG}" --tsv > "$SUMMARY_TSV"
python3 scripts/summarize_clean_kg_mechanisms.py "$CACHE_FILE" \
  --output-json "$RQ3_JSON" \
  --output-tsv "$RQ3_TSV" \
  --path-plot "$RQ3_PATH_PNG" \
  --rank-plot "$RQ3_RANK_PNG"

python3 - "$STATUS_JSON" "$JSONL_FILE" "$JSON_DIR" "$CACHE_FILE" "$AUDIT_JSON" "$SUMMARY_JSON" "$SUMMARY_TSV" "$RQ3_JSON" "$RQ3_TSV" "$RQ3_PATH_PNG" "$RQ3_RANK_PNG" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

(
    status_path,
    jsonl_file,
    json_dir,
    cache_file,
    audit_json,
    summary_json,
    summary_tsv,
    rq3_json,
    rq3_tsv,
    rq3_path_png,
    rq3_rank_png,
) = map(Path, sys.argv[1:])
expected = sum(1 for _ in jsonl_file.open())
json_count = len(list(json_dir.glob("*.json")))
summary = json.loads(summary_json.read_text())
audit_report = json.loads(audit_json.read_text())
audit = audit_report.get("summary", audit_report)
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "jsonl_file": str(jsonl_file),
    "json_dir": str(json_dir),
    "expected_count": expected,
    "json_count": json_count,
    "cache_file": str(cache_file),
    "audit_json": str(audit_json),
    "summary_json": str(summary_json),
    "summary_tsv": str(summary_tsv),
    "rq3_json": str(rq3_json),
    "rq3_tsv": str(rq3_tsv),
    "rq3_path_plot": str(rq3_path_png),
    "rq3_rank_plot": str(rq3_rank_png),
    "audit": {
        "total": audit.get("total"),
        "ok": audit.get("ok"),
        "target_pr_hits": audit.get("target_pr_hits"),
        "future_fix_trace_hits": audit.get("future_fix_trace_hits"),
        "metadata_issues": audit.get("metadata_issues"),
        "content_issue_counts": audit.get("content_issue_counts", {}),
        "content_issue_instances": audit.get("content_issue_instances", []),
        "warning_content_issue_counts": audit.get("warning_content_issue_counts", {}),
        "structural_issue_counts": audit.get("structural_issue_counts", {}),
    },
    "metrics": {
        "N": summary.get("N"),
        "file_rate": summary.get("file_rate"),
        "method_or_entity_rate": summary.get("method_or_entity_rate"),
        "mrr": summary.get("mrr"),
        "top20_hit_rate": summary.get("top20_hit_rate"),
        "statuses": summary.get("statuses", {}),
    },
}
status_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
print(json.dumps(payload, indent=2, sort_keys=True))
PY

echo "[finalize] wrote $SUMMARY_JSON"
echo "[finalize] wrote $SUMMARY_TSV"
echo "[finalize] wrote $RQ3_JSON"
echo "[finalize] wrote $RQ3_TSV"
echo "[finalize] wrote $RQ3_PATH_PNG"
echo "[finalize] wrote $RQ3_RANK_PNG"
echo "[finalize] wrote $STATUS_JSON"

if [[ "$json_count" == "$expected_count" && -x scripts/build_clean_llm_kg_fusions.sh ]]; then
  bash scripts/build_clean_llm_kg_fusions.sh "$JSONL_FILE" "$JSON_DIR" \
    "temp_run/fusions_clean_kg/$TAG" "$LLM_FUSION_TSV" "$LLM_FUSION_STATUS"
  if [[ -f "$LLM_FUSION_TSV" && -f "$RQ3_JSON" && -x scripts/render_clean_tse_latex_snippets.py ]]; then
    python3 scripts/render_clean_tse_latex_snippets.py \
      --llm-tsv "$LLM_FUSION_TSV" \
      --rq3-json "$RQ3_JSON" \
      --output "$LATEX_SNIPPETS" \
      --copy-plots-to "$PAPER_FIGURES_DIR" \
      --rq3-path-plot "$RQ3_PATH_PNG" \
      --rq3-rank-plot "$RQ3_RANK_PNG"
    echo "[finalize] wrote $LATEX_SNIPPETS"
    echo "[finalize] refreshed $PAPER_FIGURES_DIR/pathlength.png and $PAPER_FIGURES_DIR/gt_rank.png"
  fi
fi
