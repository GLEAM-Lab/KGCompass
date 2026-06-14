#!/bin/bash

# 简单的 Java 批处理脚本运行器
# 使用方法: ./run_java_simple.sh [limit] [start_idx]

set -e

# 设置代理
export http_proxy=http://172.27.16.1:7890
export https_proxy=http://172.27.16.1:7890
unset all_proxy

# 参数
LIMIT=${1:-""}
START=${2:-0}

echo "=== 简单 Java 批处理脚本 ==="
echo "开始索引: $START"
if [ -n "$LIMIT" ]; then
    echo "处理数量: $LIMIT"
else
    echo "处理数量: 全部"
fi

# 构建命令
CMD="python3 mine_kg_java_simple.py --start $START"
if [ -n "$LIMIT" ]; then
    CMD="$CMD --limit $LIMIT"
fi

echo "执行命令: $CMD"
echo "开始时间: $(date)"

# 运行脚本
$CMD

echo "结束时间: $(date)"
echo "✅ Java 批处理完成!" 