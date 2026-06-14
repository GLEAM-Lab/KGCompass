#!/bin/bash

# 在 Docker 容器中运行 Java 批处理脚本
# 使用方法: ./run_java_docker.sh [output_dir] [start_idx] [end_idx] [max_workers]

export http_proxy=http://172.27.16.1:7890
export https_proxy=http://172.27.16.1:7890
unset all_proxy

set -e

# 默认参数
OUTPUT_DIR=${1:-"java_results_docker"}
START_IDX=${2:-0}
END_IDX=${3:-""}
MAX_WORKERS=${4:-2}

echo "=== Docker 容器中的 Java 批处理脚本 ==="
echo "输出目录: $OUTPUT_DIR"
echo "开始索引: $START_IDX"
if [ -n "$END_IDX" ]; then
    echo "结束索引: $END_IDX"
else
    echo "结束索引: 处理所有"
fi
echo "并行数量: $MAX_WORKERS"

# 检查是否在容器中运行
if [ ! -d "/opt/KGCompass" ]; then
    echo "错误: 脚本必须在 Docker 容器中运行"
    echo "请使用以下命令在 app 容器中运行:"
    echo "docker-compose exec app bash"
    echo "然后在容器内运行: ./run_java_docker.sh"
    exit 1
fi

# 切换到工作目录
cd /opt/KGCompass

# 检查必要的文件
if [ ! -f "mine_kg_java_docker.py" ]; then
    echo "错误: mine_kg_java_docker.py 文件不存在"
    exit 1
fi

if [ ! -f "kgcompass/fl.py" ]; then
    echo "错误: kgcompass/fl.py 文件不存在"
    exit 1
fi

# 检查环境变量
echo "检查环境变量..."
if [ -z "$GITHUB_TOKEN" ]; then
    echo "警告: GITHUB_TOKEN 环境变量未设置，可能无法获取 PR 创建时间"
fi

if [ -z "$NEO4J_URI" ]; then
    echo "警告: NEO4J_URI 环境变量未设置，可能无法连接到 Neo4j 数据库"
fi

# 构建命令
CMD="python3 mine_kg_java_docker.py $OUTPUT_DIR $START_IDX"
if [ -n "$END_IDX" ]; then
    CMD="$CMD $END_IDX"
fi
CMD="$CMD $MAX_WORKERS"

echo "执行命令: $CMD"
echo "开始时间: $(date)"

# 创建日志文件
LOG_FILE="/opt/KGCompass/${OUTPUT_DIR}/processing.log"
mkdir -p "/opt/KGCompass/${OUTPUT_DIR}"

# 运行脚本，同时输出到控制台和日志文件
$CMD 2>&1 | tee "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

echo "结束时间: $(date)"
echo "退出代码: $EXIT_CODE"
echo "日志文件: $LOG_FILE"

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Java 批处理完成成功!"
    
    # 显示统计信息
    STATS_FILE="/opt/KGCompass/${OUTPUT_DIR}/processing_stats.json"
    if [ -f "$STATS_FILE" ]; then
        echo ""
        echo "=== 处理统计 ==="
        cat "$STATS_FILE" | python -m json.tool
    fi
    
    # 显示输出目录信息
    echo ""
    echo "=== 输出目录信息 ==="
    echo "目录: /opt/KGCompass/${OUTPUT_DIR}"
    echo "文件数量: $(find "/opt/KGCompass/${OUTPUT_DIR}" -name "*.json" ! -name "processing_stats.json" | wc -l)"
    echo "总大小: $(du -sh "/opt/KGCompass/${OUTPUT_DIR}" | cut -f1)"
else
    echo "❌ Java 批处理执行失败，退出代码: $EXIT_CODE"
    echo "请查看日志文件获取详细错误信息: $LOG_FILE"
fi

exit $EXIT_CODE 