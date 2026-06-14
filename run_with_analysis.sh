#!/bin/bash
#
# 运行 fl.py 并自动分析 issue 匹配质量
# 用法: ./run_with_analysis.sh <instance_id> <repo_path> <output_dir> [benchmark_name]
#

if [ $# -lt 3 ]; then
    echo "用法: ./run_with_analysis.sh <instance_id> <repo_path> <output_dir> [benchmark_name]"
    echo ""
    echo "示例:"
    echo "  ./run_with_analysis.sh django__django-10097 django output_dir"
    echo "  ./run_with_analysis.sh apache__dubbo-10638 dubbo java_output multi-swe-bench"
    exit 1
fi

INSTANCE_ID=$1
REPO_PATH=$2
OUTPUT_DIR=$3
BENCHMARK=${4:-swe-bench}

LOG_FILE="logs/${INSTANCE_ID}_$(date +%Y%m%d_%H%M%S).log"

mkdir -p logs

echo "运行 fl.py for ${INSTANCE_ID}..."
echo "日志将保存到: ${LOG_FILE}"
echo ""

# 运行 fl.py 并记录日志
python kgcompass/fl.py "$INSTANCE_ID" "$REPO_PATH" "$OUTPUT_DIR" "$BENCHMARK" 2>&1 | tee "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ fl.py 执行失败 (exit code: $EXIT_CODE)"
    exit $EXIT_CODE
fi

echo ""
echo "=" * 80
echo "分析 issue 匹配质量..."
echo "=" * 80
echo ""

# 解析日志并分析
python parse_fl_logs.py "$LOG_FILE"

echo ""
echo "完成！"
echo "  - KG 结果: ${OUTPUT_DIR}/${INSTANCE_ID}.json"
echo "  - 运行日志: ${LOG_FILE}"
echo "  - 匹配分析: parsed_issue_matches.json"


