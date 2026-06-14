#!/bin/bash
# 启动 Flask 应用，确保加载环境变量

cd /home/barty/GLEAM-Lab/KGCompass

# 加载环境变量
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
    echo "✅ 已加载 .env 环境变量"
else
    echo "⚠️  未找到 .env 文件"
fi

# 验证 GITHUB_TOKEN
if [ -n "$GITHUB_TOKEN" ]; then
    echo "✅ GITHUB_TOKEN 已设置"
else
    echo "❌ GITHUB_TOKEN 未设置"
    exit 1
fi

# 启动 Flask
echo "🚀 启动 Flask 应用..."
python3 app.py





