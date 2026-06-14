#!/bin/bash
# 测试 SWE-bench Issue #449 的修复
# Issue: report_dir CLI argument not working as expected

set -e

echo "================================================="
echo "测试 SWE-bench Issue #449 修复"
echo "================================================="

# 仓库信息
REPO_URL="https://github.com/SWE-bench/SWE-bench"
REPO_OWNER="SWE-bench"
REPO_NAME="SWE-bench"
ISSUE_NUMBER="449"

# 实例 ID
INSTANCE_ID="${REPO_OWNER}__${REPO_NAME}-${ISSUE_NUMBER}"

echo ""
echo "📋 Issue 信息:"
echo "  仓库: ${REPO_URL}"
echo "  Issue: #${ISSUE_NUMBER}"
echo "  实例 ID: ${INSTANCE_ID}"
echo ""

# 检查 Docker 是否运行
echo "🐳 检查 Docker 环境..."
if docker-compose ps app | grep -q "Up"; then
    echo "✅ Docker 服务已运行"
else
    echo "🚀 启动 Docker 服务..."
    docker-compose up -d
    sleep 10
fi

# 使用自定义修复脚本
echo ""
echo "🔧 开始修复流程..."
echo "================================================="

docker-compose exec -T app bash run_repair_custom.sh \
    "${INSTANCE_ID}" \
    "${REPO_URL}.git" \
    "${REPO_OWNER}__${REPO_NAME}" \
    "${ISSUE_NUMBER}"

echo ""
echo "================================================="
echo "✅ 修复流程完成！"
echo ""
echo "📁 查看结果:"
echo "  运行目录: tests/${INSTANCE_ID}_deepseek/"
echo "  补丁文件: tests/${INSTANCE_ID}_deepseek/patches/"
echo ""
echo "🎉 测试完成！"
echo "================================================="






