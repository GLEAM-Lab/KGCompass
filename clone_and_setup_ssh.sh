#!/usr/bin/env bash
# clone_and_setup_ssh.sh
# 克隆所有 SWE-bench 相关仓库并设置为 SSH 连接
#
# 使用方法:
#   bash clone_and_setup_ssh.sh
#
# 注意: 确保你的 GitHub SSH 密钥已经配置好

set -uo pipefail

echo "🚀 开始克隆并设置 SSH 连接..."

# 定义仓库映射（从 mine_kg_bulk.sh 中提取）
declare -A REPO_MAP=(
  ["astropy__astropy"]="astropy/astropy"
  ["django__django"]="django/django"
  ["matplotlib__matplotlib"]="matplotlib/matplotlib"
  ["mwaskom__seaborn"]="mwaskom/seaborn"
  ["psf__requests"]="psf/requests"
  ["pallets__flask"]="pallets/flask"
  ["pydata__xarray"]="pydata/xarray"
  ["pylint-dev__pylint"]="pylint-dev/pylint"
  ["pytest-dev__pytest"]="pytest-dev/pytest"
  ["scikit-learn__scikit-learn"]="scikit-learn/scikit-learn"
  ["sphinx-doc__sphinx"]="sphinx-doc/sphinx"
  ["sympy__sympy"]="sympy/sympy"
)

# 统计变量
TOTAL=${#REPO_MAP[@]}
COUNT=0
SUCCESS_COUNT=0
FAILED_COUNT=0
SKIPPED_COUNT=0

echo "📋 将处理 $TOTAL 个仓库"
echo "📁 克隆目录: $(pwd)"
echo ""

# 遍历所有仓库
for repo_id in "${!REPO_MAP[@]}"; do
  COUNT=$((COUNT + 1))
  repo_name="${REPO_MAP[$repo_id]}"
  
  echo "[$COUNT/$TOTAL] 🔄 处理仓库: $repo_name"
  
  # 检查目录是否已存在
  if [[ -d "$repo_id" ]]; then
    echo "[$COUNT/$TOTAL] 📁 目录 $repo_id 已存在，检查并更新 remote..."
    
    cd "$repo_id"
    
    # 检查当前 remote
    current_remote=$(git remote get-url origin 2>/dev/null || echo "")
    ssh_url="git@github.com:${repo_name}.git"
    
    if [[ "$current_remote" == "$ssh_url" ]]; then
      echo "[$COUNT/$TOTAL] ✅ SSH remote 已正确配置"
      SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    else
      echo "[$COUNT/$TOTAL] 🔧 更新 remote 为 SSH: $ssh_url"
      if git remote set-url origin "$ssh_url"; then
        echo "[$COUNT/$TOTAL] ✅ Remote 更新成功"
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
      else
        echo "[$COUNT/$TOTAL] ❌ Remote 更新失败"
        FAILED_COUNT=$((FAILED_COUNT + 1))
      fi
    fi
    
    cd ..
  else
    echo "[$COUNT/$TOTAL] 📥 克隆仓库: $repo_name"
    ssh_url="git@github.com:${repo_name}.git"
    
    if git clone "$ssh_url" "$repo_id"; then
      echo "[$COUNT/$TOTAL] ✅ 克隆成功: $repo_id"
      SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    else
      echo "[$COUNT/$TOTAL] ❌ 克隆失败: $repo_name"
      echo "[$COUNT/$TOTAL] 💡 可能原因: SSH 密钥未配置或网络问题"
      FAILED_COUNT=$((FAILED_COUNT + 1))
    fi
  fi
  
  echo ""
done

# 显示统计结果
echo "======================================================"
echo "📊 处理完成统计报告"
echo "======================================================"
echo "📄 总仓库数: $TOTAL"
echo "✅ 成功处理: $SUCCESS_COUNT"
echo "❌ 处理失败: $FAILED_COUNT"
echo "⏭️  跳过数量: $SKIPPED_COUNT"
echo ""

if [[ $FAILED_COUNT -gt 0 ]]; then
  echo "⚠️  如果有失败，请检查:"
  echo "   1. SSH 密钥是否已添加到 GitHub"
  echo "   2. SSH 代理是否运行: ssh-add -l"
  echo "   3. 网络连接是否正常"
  echo ""
fi

echo "🔧 验证 SSH 连接命令:"
echo "   ssh -T git@github.com"
echo ""

echo "📋 查看所有仓库状态:"
echo "   ls -la"
echo ""

echo "✅ 脚本执行完成！"
echo "======================================================" 