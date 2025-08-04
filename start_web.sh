#!/usr/bin/env bash
# start_web.sh
# KGCompass Web 界面快速启动脚本

set -euo pipefail

echo "🚀 启动 KGCompass Web 界面..."

# 检查 Python 版本
python_version=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
echo "📍 Python 版本: $python_version"

# 检查是否存在虚拟环境
if [[ ! -d "venv" ]]; then
    echo "🔧 创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
echo "🔧 激活虚拟环境..."
source venv/bin/activate

# 安装依赖
echo "📦 安装/更新依赖..."
pip install -r requirements_web.txt

# 创建必要的目录
echo "📁 创建输出目录..."
mkdir -p web_outputs
mkdir -p static/css static/js templates

# 检查必要文件
echo "🔍 检查必要文件..."
required_files=(
    "app.py"
    "templates/index.html"
    "static/css/style.css"
    "static/js/app.js"
)

missing_files=()
for file in "${required_files[@]}"; do
    if [[ ! -f "$file" ]]; then
        missing_files+=("$file")
    fi
done

if [[ ${#missing_files[@]} -gt 0 ]]; then
    echo "❌ 缺少必要文件:"
    printf "   - %s\n" "${missing_files[@]}"
    echo "请确保所有文件都已创建"
    exit 1
fi

# 设置环境变量
export FLASK_APP=app.py
export FLASK_ENV=development
export FLASK_DEBUG=1

echo ""
echo "======================================================"
echo "🎉 KGCompass Web 界面启动完成!"
echo "======================================================"
echo "📡 访问地址: http://localhost:5000"
echo "🔧 开发模式: 已启用"
echo "📊 实时日志: WebSocket 支持"
echo "🛠️  停止服务: Ctrl+C"
echo "======================================================"
echo ""

# 启动 Flask 应用
python3 app.py 