#!/usr/bin/env bash
# convert_to_ssh.sh
# 将当前目录下的所有 Git 仓库从 HTTPS 转换为 SSH
#
# 使用方法:
#   bash convert_to_ssh.sh
#   # 或者指定目录
#   bash convert_to_ssh.sh /path/to/repos
#
# 注意: 确保你的 GitHub SSH 密钥已经配置好

set -uo pipefail

TARGET_DIR="${1:-$(pwd)}"
echo "🔧 批量转换 Git 仓库为 SSH 连接..."
echo "📁 目标目录: $TARGET_DIR"
echo ""

# 统计变量
TOTAL=0
SUCCESS_COUNT=0
FAILED_COUNT=0
SKIPPED_COUNT=0

# 查找所有 Git 仓库
echo "🔍 扫描 Git 仓库..."
REPOS=()
while IFS= read -r -d '' repo_dir; do
  if [[ -d "$repo_dir/.git" ]]; then
    REPOS+=("$repo_dir")
  fi
done < <(find "$TARGET_DIR" -maxdepth 1 -type d -print0)

TOTAL=${#REPOS[@]}

if [[ $TOTAL -eq 0 ]]; then
  echo "❌ 未找到任何 Git 仓库"
  exit 1
fi

echo "📋 找到 $TOTAL 个 Git 仓库"
echo ""

# 处理每个仓库
for repo_dir in "${REPOS[@]}"; do
  if [[ "$repo_dir" == "$TARGET_DIR" ]]; then
    continue  # 跳过当前目录本身
  fi
  
  SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
  repo_name=$(basename "$repo_dir")
  
  echo "[$SUCCESS_COUNT/$TOTAL] 🔄 处理仓库: $repo_name"
  
  cd "$repo_dir"
  
  # 获取当前 remote URL
  current_remote=$(git remote get-url origin 2>/dev/null || echo "")
  
  if [[ -z "$current_remote" ]]; then
    echo "[$SUCCESS_COUNT/$TOTAL] ⚠️  没有找到 origin remote，跳过"
    SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    cd "$TARGET_DIR"
    continue
  fi
  
  echo "[$SUCCESS_COUNT/$TOTAL] 📡 当前 remote: $current_remote"
  
  # 检查是否已经是 SSH
  if [[ "$current_remote" == git@github.com:* ]]; then
    echo "[$SUCCESS_COUNT/$TOTAL] ✅ 已经是 SSH 连接，跳过"
    SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    cd "$TARGET_DIR"
    continue
  fi
  
  # 转换 HTTPS 为 SSH
  if [[ "$current_remote" == https://github.com/* ]]; then
    # 提取 owner/repo 部分
    repo_path=$(echo "$current_remote" | sed 's|https://github.com/||' | sed 's|\.git$||')
    ssh_url="git@github.com:${repo_path}.git"
    
    echo "[$SUCCESS_COUNT/$TOTAL] 🔄 转换为 SSH: $ssh_url"
    
    if git remote set-url origin "$ssh_url"; then
      echo "[$SUCCESS_COUNT/$TOTAL] ✅ 转换成功"
      SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    else
      echo "[$SUCCESS_COUNT/$TOTAL] ❌ 转换失败"
      FAILED_COUNT=$((FAILED_COUNT + 1))
    fi
  else
    echo "[$SUCCESS_COUNT/$TOTAL] ⚠️  不是 GitHub HTTPS URL，跳过"
    SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
  fi
  
  cd "$TARGET_DIR"
  echo ""
done

# 重新计算成功数（因为循环中包含了跳过的）
SUCCESS_COUNT=$((TOTAL - SKIPPED_COUNT - FAILED_COUNT))

# 显示统计结果
echo "======================================================"
echo "📊 转换完成统计报告"
echo "======================================================"
echo "📄 总仓库数: $TOTAL"
echo "✅ 转换成功: $SUCCESS_COUNT"
echo "❌ 转换失败: $FAILED_COUNT"
echo "⏭️  跳过数量: $SKIPPED_COUNT"
echo ""

if [[ $FAILED_COUNT -gt 0 ]]; then
  echo "⚠️  如果有失败，请检查:"
  echo "   1. SSH 密钥是否已添加到 GitHub"
  echo "   2. 仓库是否有写权限"
  echo ""
fi

echo "🔧 验证 SSH 连接命令:"
echo "   ssh -T git@github.com"
echo ""

echo "📋 验证转换结果:"
echo "   for dir in */; do echo \"=== \$dir ===\"; git -C \"\$dir\" remote get-url origin; done"
echo ""

echo "✅ 脚本执行完成！"
echo "======================================================" 