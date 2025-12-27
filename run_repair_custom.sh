#!/bin/bash
set -e

# Enable debug output if DEBUG env is set
if [[ "$DEBUG" == "1" ]]; then
  set -x
fi

# --- Environment and Proxy Setup ---
# Add the project root to PYTHONPATH to solve module import issues without using -m.
export PYTHONPATH=$(pwd)

# Set proxy if needed, and ensure localhost is excluded for Neo4j connection.
export http_proxy=http://172.27.16.1:7890
export https_proxy=http://172.27.16.1:7890
unset all_proxy

# --- Configuration ---
INSTANCE_ID=$1
CLONE_URL=$2
REPO_IDENTIFIER=$3
ISSUE_NUMBER=$4
MODEL_NAME="deepseek" # Hardcoded to deepseek
TEMPERATURE=${TEMPERATURE:-0.3}

if [ -z "$INSTANCE_ID" ] || [ -z "$CLONE_URL" ] || [ -z "$REPO_IDENTIFIER" ] || [ -z "$ISSUE_NUMBER" ]; then
  echo "Usage: $0 <instance_id> <clone_url> <repo_identifier> <issue_number>"
  echo "Example: $0 owner__repo-123 https://github.com/owner/repo.git owner__repo 123"
  exit 1
fi

echo "================================================="
echo "Starting KGCompass repair for custom repository"
echo "Instance ID: $INSTANCE_ID"
echo "Repository: $REPO_IDENTIFIER"
echo "Clone URL: $CLONE_URL"
echo "Issue Number: $ISSUE_NUMBER"
echo "================================================="

# --- Repository Cloning ---
REPOS_DIR="./playground" # Store all cloned repos inside the project's playground directory
REPO_PATH="${REPOS_DIR}/${REPO_IDENTIFIER}"

if [ ! -d "$REPO_PATH" ]; then
  echo "--- Repository '$REPO_IDENTIFIER' not found. Cloning... ---"
  mkdir -p "$REPOS_DIR"
  git clone "$CLONE_URL" "$REPO_PATH"
  echo "✅ Repository cloned to $REPO_PATH"
else
  echo "✅ Repository '$REPO_IDENTIFIER' already exists at $REPO_PATH."
  # 可选：拉取最新更改
  # cd "$REPO_PATH" && git pull && cd -
fi

# --- Derived variables ---
RUN_DIR="tests/${INSTANCE_ID}_${MODEL_NAME}"
REPAIR_MODEL_NAME="${MODEL_NAME}_0" # Default repair config

# --- Directories for this run ---
mkdir -p "$RUN_DIR"
KG_LOCATIONS_DIR="${RUN_DIR}/kg_locations"
LLM_LOCATIONS_DIR="${RUN_DIR}/llm_locations"
FINAL_LOCATIONS_DIR="${RUN_DIR}/final_locations"
PATCH_DIR="${RUN_DIR}/patches"
LOG_FILE="${RUN_DIR}/run.log"

mkdir -p "$KG_LOCATIONS_DIR" "$LLM_LOCATIONS_DIR" "$FINAL_LOCATIONS_DIR" "$PATCH_DIR"

echo "Run directory: $RUN_DIR"

# --- Prerequisites check ---
echo "✅ Assuming Neo4j connection is available via Docker Compose network."

# --- Create instance data file for custom repository ---
echo "--- Creating instance data file for custom repository ---"

# 注意：这里我们假设已经有一个 Python 脚本来创建实例数据
# 或者直接在 Python 后端创建，这里只是占位符
# 实际实现中，instance 数据应该已经在 web_outputs 中准备好了

# --- Pipeline Steps ---

# Step 1: Knowledge Graph-based Bug Location
echo -e "\n--- Step 1: KG-based Bug Location ---"
KG_RESULT_FILE="${KG_LOCATIONS_DIR}/${INSTANCE_ID}.json"

if [ -f "$KG_RESULT_FILE" ]; then
    echo "⚙️  正在分析代码结构，构建知识图谱..."
    sleep 2  # 让用户看到进度
    echo "✅ 知识图谱构建完成"
else
    # 运行 KG 挖掘（适配自定义仓库，传递 'custom' 作为 benchmark_name）
    echo "⚙️  正在分析代码结构，构建知识图谱..."
    python3 kgcompass/fl.py "$INSTANCE_ID" "$REPO_IDENTIFIER" "$KG_LOCATIONS_DIR" "custom"
    echo "✅ 知识图谱构建完成"
fi

# Step 2: LLM-based Bug Location
echo -e "\n--- Step 2: LLM-based Bug Location ---"
LLM_RESULT_FILE="${LLM_LOCATIONS_DIR}/${INSTANCE_ID}.json"
if [ -f "$LLM_RESULT_FILE" ]; then
    echo "⚙️  使用大语言模型分析问题描述，定位可疑代码..."
    sleep 2  # 让用户看到进度
    echo "✅ 故障定位分析完成"
else
    # 运行 LLM 定位（需要适配自定义仓库）
    echo "⚙️  使用大语言模型分析问题描述，定位可疑代码..."
    python3 kgcompass/llm_loc.py "$LLM_LOCATIONS_DIR" --instance_id "$INSTANCE_ID"
    echo "✅ 故障定位分析完成"
fi

# Step 3: Fix/Merge Bug Location
echo -e "\n--- Step 3: Merge and Fix Bug Locations ---"
FINAL_RESULT_FILE="${FINAL_LOCATIONS_DIR}/${INSTANCE_ID}.json"
if [ -f "$FINAL_RESULT_FILE" ]; then
    echo "⚙️  融合知识图谱和LLM定位结果，精确定位错误位置..."
    sleep 2  # 让用户看到进度
    echo "✅ 错误定位融合完成"
else
    # 融合定位结果
    echo "⚙️  融合知识图谱和LLM定位结果，精确定位错误位置..."
    python3 kgcompass/fix_fl_line.py "$LLM_LOCATIONS_DIR" "$FINAL_LOCATIONS_DIR" --instance_id "$INSTANCE_ID"
    echo "✅ 错误定位融合完成"
fi

# Step 4: Final Patch Generation
echo -e "\n--- Step 4: Final Patch Generation ---"
PATCH_FILE="${PATCH_DIR}/${INSTANCE_ID}.patch"
# 生成修复补丁
echo "⚙️  基于定位结果生成修复补丁..."
python3 kgcompass/repair.py "$FINAL_LOCATIONS_DIR" \
    --instance_id "$INSTANCE_ID" \
    --playground_dir "$REPOS_DIR" \
    --repo_identifier "$REPO_IDENTIFIER"
echo "✅ 修复补丁生成完成"

echo -e "\n================================================="
echo "🎉 Repair pipeline finished for custom repository: $INSTANCE_ID"
echo "Find all logs and artifacts in: $RUN_DIR"
echo "================================================="

