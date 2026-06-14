#!/bin/bash

# Java Multi-SWE-bench 批量修复脚本 (KG已构建完成版本)
# 用于在KG构建完成后执行后续修复流程

set -e

# 设置参数
KG_DIR="java_kg_results"  # KG结果目录
OUTPUT_DIR="java_results"
MAX_WORKERS=2  # 减少默认并行数，因为修复过程更耗资源
START_IDX=0
END_IDX=""  # 空表示处理所有
MODEL_NAME="deepseek"
TEMPERATURE=0.3

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        -k|--kg-dir)
            KG_DIR="$2"
            shift 2
            ;;
        -o|--output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -w|--workers)
            MAX_WORKERS="$2"
            shift 2
            ;;
        -s|--start)
            START_IDX="$2"
            shift 2
            ;;
        -e|--end)
            END_IDX="$2"
            shift 2
            ;;
        -m|--model)
            MODEL_NAME="$2"
            shift 2
            ;;
        -t|--temperature)
            TEMPERATURE="$2"
            shift 2
            ;;
        -h|--help)
            echo "用法: $0 [选项]"
            echo "选项:"
            echo "  -k, --kg-dir DIR     KG结果目录 (默认: java_kg_results)"
            echo "  -o, --output DIR     输出目录 (默认: java_results)"
            echo "  -w, --workers N      并行数量 (默认: 2)"
            echo "  -s, --start N        开始索引 (默认: 0)"
            echo "  -e, --end N          结束索引 (默认: 处理所有)"
            echo "  -m, --model NAME     模型名称 (默认: deepseek)"
            echo "  -t, --temperature F  温度参数 (默认: 0.3)"
            echo "  -h, --help           显示帮助信息"
            echo ""
            echo "示例:"
            echo "  $0 -o my_results -w 4                   # 使用4个并行，输出到my_results目录"
            echo "  $0 -s 0 -e 10                          # 只处理前10个实例"
            echo "  $0 -s 50 -e 100 -w 1                   # 处理索引50-99的实例，使用1个并行"
            echo "  $0 -k my_kg_results                     # 使用自定义KG目录"
            exit 0
            ;;
        *)
            echo "未知选项: $1"
            echo "使用 $0 --help 查看帮助"
            exit 1
            ;;
    esac
done

# 检查必要的依赖
echo "检查环境依赖..."

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 Python3"
    exit 1
fi

# 检查必要的Python包
python3 -c "import datasets, github, neo4j" 2>/dev/null || {
    echo "错误: 缺少必要的 Python 包。请安装:"
    echo "pip install datasets PyGithub neo4j"
    exit 1
}

# 检查配置文件
if [ ! -f "kgcompass/config.py" ]; then
    echo "错误: 未找到 kgcompass/config.py 文件"
    exit 1
fi

# 检查必要的脚本文件
for script in "kgcompass/llm_loc.py" "kgcompass/fix_fl_line.py" "kgcompass/repair.py"; do
    if [ ! -f "$script" ]; then
        echo "错误: 未找到 $script 文件"
        exit 1
    fi
done

# 检查KG目录
if [ ! -d "$KG_DIR" ]; then
    echo "错误: KG目录不存在: $KG_DIR"
    echo "请确保已经完成KG构建步骤"
    exit 1
fi

# 创建必要的目录
echo "创建目录结构..."
mkdir -p playground
mkdir -p tests_java

# 显示配置信息
echo "=== 配置信息 ==="
echo "KG 目录: $KG_DIR"
echo "输出目录: $OUTPUT_DIR"
echo "并行数量: $MAX_WORKERS"
echo "开始索引: $START_IDX"
echo "模型名称: $MODEL_NAME"
echo "温度参数: $TEMPERATURE"
if [ -n "$END_IDX" ]; then
    echo "结束索引: $END_IDX"
else
    echo "结束索引: 处理所有"
fi
echo "==============="

# 构建命令 - 使用java_repair_batch.py进行批量修复
CMD="python3 java_repair_batch.py --kg_dir $KG_DIR --workers $MAX_WORKERS --model $MODEL_NAME --temperature $TEMPERATURE --start $START_IDX"
if [ -n "$END_IDX" ]; then
    LIMIT=$((END_IDX - START_IDX))
    CMD="$CMD --limit $LIMIT"
fi

echo "执行命令: $CMD"
echo ""

# 记录开始时间
START_TIME=$(date)
echo "开始时间: $START_TIME"

# 运行批量修复
if eval "$CMD"; then
    END_TIME=$(date)
    echo ""
    echo "=== 修复完成 ==="
    echo "开始时间: $START_TIME"
    echo "结束时间: $END_TIME"
    echo "结果目录: tests_java/"
    
    # 显示结果统计
    echo ""
    echo "=== 修复统计 ==="
    TOTAL_INSTANCES=$(find tests_java -name "*_${MODEL_NAME}" -type d | wc -l)
    SUCCESSFUL_PATCHES=$(find tests_java -name "*.patch" | wc -l)
    echo "总处理实例: $TOTAL_INSTANCES 个"
    echo "成功生成补丁: $SUCCESSFUL_PATCHES 个"
    
    if [ $TOTAL_INSTANCES -gt 0 ]; then
        SUCCESS_RATE=$(echo "scale=2; $SUCCESSFUL_PATCHES * 100 / $TOTAL_INSTANCES" | bc 2>/dev/null || echo "N/A")
        echo "成功率: $SUCCESS_RATE%"
    fi
else
    echo "批量修复失败"
    exit 1
fi 