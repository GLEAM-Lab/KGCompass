#!/usr/bin/env bash
set -euo pipefail

IDS_FILE="${1:-SWE-bench_Verified_ids.jsonl}"
KG_DIR="${2:-runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6}"
OUT_ROOT="${3:-temp_run/fusions_clean_kg/tse_timesafe_main_20260529_v6}"
SUMMARY_TSV="${4:-logs/comparison_current/llm_clean_kg_tse_timesafe_main_20260529_v6.tsv}"
STATUS_JSON="${5:-logs/comparison_current/llm_clean_kg_tse_timesafe_main_20260529_v6_status.json}"

export KGCOMPASS_LOAD_DOTENV=0
export HF_DATASETS_OFFLINE="${HF_DATASETS_OFFLINE:-1}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
unset OPENAI_API_KEY ANTHROPIC_API_KEY DASHSCOPE_API_KEY MOONSHOT_API_KEY BAILIAN_API_KEY DEEPSEEK_API_KEY QWEN_API_KEY

mkdir -p "$OUT_ROOT" "$(dirname "$SUMMARY_TSV")" "$(dirname "$STATUS_JSON")"

expected_count="$(wc -l < "$IDS_FILE" | tr -d ' ')"
kg_count="$(find "$KG_DIR" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
if [[ "$kg_count" != "$expected_count" ]]; then
  echo "KG_DIR is incomplete: $kg_count/$expected_count ($KG_DIR)" >&2
  exit 2
fi

declare -a model_specs=(
  "Sonnet46|temp_run/eval_zenmux_sonnet46_issueonly_full|Sonnet46_issue_only|Sonnet46_KG_clean_ht10"
  "GLM5|temp_run/eval_aliyun_glm5_issueonly|GLM5_issue_only|GLM5_KG_clean_ht10"
  "Qwen3CoderNext|temp_run/eval_aliyun_qwen3coderplus_issueonly|Qwen3CoderNext_issue_only|Qwen3CoderNext_KG_clean_ht10"
  "MoonshotKimiK25|temp_run/eval_moonshot_kimik25_issueonly_w1|MoonshotKimiK25_issue_only|MoonshotKimiK25_KG_clean_ht10"
)

declare -a eval_groups=()
for spec in "${model_specs[@]}"; do
  IFS='|' read -r tag issue_dir issue_group fusion_group <<< "$spec"
  issue_count="$(find "$issue_dir" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "$issue_count" -lt "$expected_count" ]]; then
    echo "Issue-only dir for $tag is incomplete: $issue_count/$expected_count ($issue_dir)" >&2
    exit 3
  fi
  fusion_dir="$OUT_ROOT/${tag}_kg_clean_ht10"
  echo "[fusion] $tag: $issue_dir + $KG_DIR -> $fusion_dir"
  python3 temp_run/export_two_way_fusion.py \
    --primary-dir "$issue_dir" \
    --secondary-dir "$KG_DIR" \
    --output-dir "$fusion_dir" \
    --mode intersection \
    --strategy head_tail \
    --top-k 20 \
    --primary-head 10 \
    --secondary-head 20 \
    --force
  eval_groups+=(--group "$issue_group=$issue_dir")
  eval_groups+=(--group "$fusion_group=$fusion_dir")
done

python3 scripts/eval_controls_v3.py \
  --ids-file "$IDS_FILE" \
  "${eval_groups[@]}" \
  --group "KG_clean=$KG_DIR" \
  --group "BM25_nohints=runs/text_baselines_nohints/2000" \
  --group "DPR=runs/text_baselines_dense_filefirst/2203" \
  --group "BLUiR=runs/text_baselines_bluir/2300" \
  --output-tsv "$SUMMARY_TSV"

python3 - "$STATUS_JSON" "$IDS_FILE" "$KG_DIR" "$OUT_ROOT" "$SUMMARY_TSV" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path, ids_file, kg_dir, out_root, summary_tsv = map(Path, sys.argv[1:])
expected = sum(1 for _ in ids_file.open())
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "ids_file": str(ids_file),
    "kg_dir": str(kg_dir),
    "kg_json_count": len(list(kg_dir.glob("*.json"))),
    "expected_count": expected,
    "fusion_root": str(out_root),
    "summary_tsv": str(summary_tsv),
    "model_fusion_counts": {
        child.name: len(list(child.glob("*.json")))
        for child in sorted(out_root.iterdir())
        if child.is_dir()
    },
}
status_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
print(json.dumps(payload, indent=2, sort_keys=True))
PY

echo "[fusion] wrote $SUMMARY_TSV"
echo "[fusion] wrote $STATUS_JSON"
