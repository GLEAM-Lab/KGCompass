#!/bin/bash
# Demo 脚本：展示如何通过注入正确位置来生成正确的补丁

set -e

INSTANCE_ID="pypa__pip-13548"
TEST_DIR="tests/pypa__pip-13548_deepseek"
LLM_LOCATIONS_FILE="${TEST_DIR}/llm_locations/${INSTANCE_ID}.json"
FINAL_LOCATIONS_FILE="${TEST_DIR}/final_locations/${INSTANCE_ID}.json"

echo "=================================================="
echo "🎬 Demo: 修复 pypa/pip Issue #13548"
echo "=================================================="
echo ""

# Step 1: 注入正确的方法位置
echo "--- Step 1: 注入 Ground Truth 位置 ---"
if [ ! -f "$LLM_LOCATIONS_FILE" ]; then
    echo "❌ LLM locations file not found: $LLM_LOCATIONS_FILE"
    echo "请先运行正常的修复流程到 LLM 定位阶段"
    exit 1
fi

echo "📝 备份原始 LLM locations..."
cp "$LLM_LOCATIONS_FILE" "${LLM_LOCATIONS_FILE}.backup"

echo "💉 注入正确的方法位置..."
python3 inject_parser_location.py "$LLM_LOCATIONS_FILE"

echo ""
echo "--- Step 2: 重新运行版本统一（fix_fl_line） ---"
echo "⚙️  融合知识图谱和LLM定位结果，精确定位错误位置..."
python3 kgcompass/fix_fl_line.py \
    "${TEST_DIR}/llm_locations" \
    "${TEST_DIR}/final_locations" \
    --instance_id "$INSTANCE_ID"

echo ""
echo "--- Step 3: 检查 final_locations ---"
echo "📊 Final locations 中的方法："
if [ -f "$FINAL_LOCATIONS_FILE" ]; then
    python3 -c "
import json
with open('$FINAL_LOCATIONS_FILE', 'r') as f:
    data = json.load(f)
    methods = data.get('related_entities', {}).get('methods', [])
    print(f'共有 {len(methods)} 个方法')
    for i, m in enumerate(methods[:5], 1):
        file_path = m.get('file_path', 'N/A')
        name = m.get('name', 'N/A')
        lines = f\"{m.get('start_line', '?')}-{m.get('end_line', '?')}\"
        note = m.get('note', '')
        marker = '🎯 ' if 'parser.py' in file_path else '   '
        print(f'{marker}{i}. {file_path}')
        print(f'      {name} (lines {lines})')
        if note:
            print(f'      Note: {note}')
"
else
    echo "❌ Final locations file not found"
fi

echo ""
echo "--- Step 4: 生成补丁 ---"
echo "⚙️  基于定位结果生成修复补丁..."

# 进入 Docker 容器运行补丁生成
docker exec kgcompass-app bash -c "
cd /opt/KGCompass && \
python3 kgcompass/repair.py \
    --test_instance_id ${INSTANCE_ID} \
    --locations_dir ${TEST_DIR}/final_locations \
    --output_dir ${TEST_DIR}/patches
"

echo ""
echo "--- Step 5: 查看生成的补丁 ---"
PATCH_FILE=$(find "${TEST_DIR}/patches/diff_patches" -name "*.diff" | head -1)
if [ -f "$PATCH_FILE" ]; then
    echo "✅ 补丁文件: $PATCH_FILE"
    echo ""
    echo "📄 补丁内容："
    echo "----------------------------------------"
    cat "$PATCH_FILE"
    echo "----------------------------------------"
    
    # 检查是否包含 parser.py
    if grep -q "parser.py" "$PATCH_FILE"; then
        echo ""
        echo "🎉 成功！补丁包含了 parser.py 的修改！"
        echo "✅ Ground Truth 位置被正确识别和修复"
    else
        echo ""
        echo "⚠️  补丁不包含 parser.py，可能需要进一步调试"
    fi
else
    echo "❌ 没有找到补丁文件"
fi

echo ""
echo "=================================================="
echo "🎬 Demo 完成！"
echo "=================================================="
echo ""
echo "📝 说明："
echo "1. 我们手动注入了 Ground Truth 位置：_get_ordered_configuration_items"
echo "2. 这展示了当 LLM 能够正确识别方法时，系统可以生成正确的补丁"
echo "3. 原始备份保存在: ${LLM_LOCATIONS_FILE}.backup"
echo ""
echo "🔄 要恢复原始状态，运行："
echo "   mv ${LLM_LOCATIONS_FILE}.backup ${LLM_LOCATIONS_FILE}"
echo ""





