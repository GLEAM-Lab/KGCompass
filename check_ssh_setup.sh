#!/usr/bin/env bash
# check_ssh_setup.sh
# 检查 SSH 密钥设置和 GitHub 连接状态
#
# 使用方法:
#   bash check_ssh_setup.sh

echo "🔐 检查 SSH 设置和 GitHub 连接..."
echo ""

# 1. 检查 SSH 密钥
echo "1️⃣ 检查 SSH 密钥..."
if [[ -f ~/.ssh/id_rsa.pub ]]; then
  echo "✅ 找到 RSA 公钥: ~/.ssh/id_rsa.pub"
elif [[ -f ~/.ssh/id_ed25519.pub ]]; then
  echo "✅ 找到 Ed25519 公钥: ~/.ssh/id_ed25519.pub"
else
  echo "❌ 未找到 SSH 公钥"
  echo "💡 生成 SSH 密钥命令："
  echo "   ssh-keygen -t ed25519 -C \"your_email@example.com\""
  echo "   # 或者使用 RSA"
  echo "   ssh-keygen -t rsa -b 4096 -C \"your_email@example.com\""
fi
echo ""

# 2. 检查 SSH 代理
echo "2️⃣ 检查 SSH 代理..."
if ssh-add -l >/dev/null 2>&1; then
  echo "✅ SSH 代理正在运行"
  echo "📋 已加载的密钥:"
  ssh-add -l
else
  echo "⚠️  SSH 代理未运行或无密钥"
  echo "💡 启动 SSH 代理并添加密钥："
  echo "   eval \"\$(ssh-agent -s)\""
  echo "   ssh-add ~/.ssh/id_ed25519  # 或 ~/.ssh/id_rsa"
fi
echo ""

# 3. 测试 GitHub 连接
echo "3️⃣ 测试 GitHub SSH 连接..."
if ssh -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
  echo "✅ GitHub SSH 连接成功"
  ssh -T git@github.com 2>&1 | head -1
else
  echo "❌ GitHub SSH 连接失败"
  echo "💡 请确保："
  echo "   1. SSH 公钥已添加到 GitHub (https://github.com/settings/keys)"
  echo "   2. SSH 代理正在运行"
  echo "   3. 网络连接正常"
  echo ""
  echo "🔧 手动测试命令："
  echo "   ssh -T git@github.com"
fi
echo ""

# 4. 显示公钥内容（用于复制到 GitHub）
echo "4️⃣ SSH 公钥内容（复制到 GitHub）..."
if [[ -f ~/.ssh/id_ed25519.pub ]]; then
  echo "📋 Ed25519 公钥:"
  cat ~/.ssh/id_ed25519.pub
elif [[ -f ~/.ssh/id_rsa.pub ]]; then
  echo "📋 RSA 公钥:"
  cat ~/.ssh/id_rsa.pub
else
  echo "❌ 未找到公钥文件"
fi
echo ""

# 5. 检查现有仓库的 remote 设置
echo "5️⃣ 检查当前目录下仓库的 remote 设置..."
REPO_COUNT=0
SSH_COUNT=0
HTTPS_COUNT=0

for dir in */; do
  if [[ -d "$dir/.git" ]]; then
    REPO_COUNT=$((REPO_COUNT + 1))
    remote_url=$(git -C "$dir" remote get-url origin 2>/dev/null || echo "")
    
    if [[ "$remote_url" == git@github.com:* ]]; then
      echo "✅ $dir -> SSH: $remote_url"
      SSH_COUNT=$((SSH_COUNT + 1))
    elif [[ "$remote_url" == https://github.com/* ]]; then
      echo "⚠️  $dir -> HTTPS: $remote_url"
      HTTPS_COUNT=$((HTTPS_COUNT + 1))
    else
      echo "❓ $dir -> Other: $remote_url"
    fi
  fi
done

if [[ $REPO_COUNT -eq 0 ]]; then
  echo "📁 当前目录下没有 Git 仓库"
else
  echo ""
  echo "📊 仓库统计:"
  echo "   总计: $REPO_COUNT"
  echo "   SSH: $SSH_COUNT"
  echo "   HTTPS: $HTTPS_COUNT"
  
  if [[ $HTTPS_COUNT -gt 0 ]]; then
    echo ""
    echo "💡 转换 HTTPS 为 SSH:"
    echo "   bash convert_to_ssh.sh"
  fi
fi
echo ""

# 6. 快速设置指南
echo "6️⃣ 快速设置指南..."
echo "🔧 如果需要设置 SSH："
echo "   1. 生成密钥: ssh-keygen -t ed25519 -C \"your_email@example.com\""
echo "   2. 启动代理: eval \"\$(ssh-agent -s)\""
echo "   3. 添加密钥: ssh-add ~/.ssh/id_ed25519"
echo "   4. 复制公钥: cat ~/.ssh/id_ed25519.pub"
echo "   5. 添加到 GitHub: https://github.com/settings/keys"
echo "   6. 测试连接: ssh -T git@github.com"
echo ""

echo "✅ SSH 检查完成！" 