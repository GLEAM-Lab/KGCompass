#!/usr/bin/env bash

export http_proxy=http://172.27.16.1:7890
export https_proxy=http://172.27.16.1:7890
unset all_proxy
export HF_ENDPOINT=https://hf-mirror.com
export KGCOMPASS_LOAD_DOTENV="${KGCOMPASS_LOAD_DOTENV:-0}"
unset OPENAI_API_KEY ANTHROPIC_API_KEY DASHSCOPE_API_KEY MOONSHOT_API_KEY BAILIAN_API_KEY DEEPSEEK_API_KEY QWEN_API_KEY

BASE_DIR="${1:-runs/kg_verified}"
LOG_DIR="${2:-logs/calc_prefl}"
JOBS="${JOBS:-1}"
RESUME="${RESUME:-1}"

mkdir -p "$LOG_DIR"

run_ids=()
if [[ -n "${RUN_IDS:-}" ]]; then
  read -r -a run_ids <<< "$RUN_IDS"
else
  for d in "$BASE_DIR"/*; do
    if [[ -d "$d" ]]; then
      name="$(basename "$d")"
      if [[ "$name" != _* ]]; then
        run_ids+=("$name")
      fi
    fi
  done
fi

if [[ ${#run_ids[@]} -eq 0 ]]; then
  echo "No run-id directories found under $BASE_DIR"
  exit 0
fi

IFS=$'\n' sorted=($(printf "%s\n" "${run_ids[@]}" | sort))
unset IFS

for run_id in "${sorted[@]}"; do
  log_file="$LOG_DIR/${run_id}.log"
  if [[ ! -d "$BASE_DIR/$run_id" ]]; then
    echo "===== Skip run-id ${run_id} (directory not found under $BASE_DIR) ====="
    continue
  fi
  if ! compgen -G "$BASE_DIR/$run_id/*.json" >/dev/null && \
     ! compgen -G "$BASE_DIR/$run_id/*/*.json" >/dev/null; then
    echo "===== Skip run-id ${run_id} (no JSON location files) ====="
    continue
  fi
  if [[ "$RESUME" == "1" && -f "$log_file" ]] && grep -q "========== Figure 8 ==========" "$log_file"; then
    echo "===== Skip run-id ${run_id} (completed log exists) ====="
    continue
  fi

  echo "===== Running calc_prefl for run-id ${run_id} ====="
  if [[ "$JOBS" -le 1 ]]; then
    python3 kgcompass/calc_prefl.py --base-dir "$BASE_DIR" --run-id "$run_id" 2>&1 | tee "$log_file"
  else
    (
      python3 kgcompass/calc_prefl.py --base-dir "$BASE_DIR" --run-id "$run_id" 2>&1 | tee "$log_file"
    ) &
    while [[ "$(jobs -pr | wc -l)" -ge "$JOBS" ]]; do
      wait -n
    done
  fi
done

if [[ "$JOBS" -gt 1 ]]; then
  wait
fi
