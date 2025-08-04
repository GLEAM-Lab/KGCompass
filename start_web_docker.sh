#!/usr/bin/env bash
# start_web_docker.sh
# KGCompass Web 界面启动脚本 (Docker 支持版)

set -euo pipefail

echo "🚀 启动 KGCompass Web 界面 (Docker 模式)..."

# 检查 Docker 环境
echo "🐳 检查 Docker 环境..."

if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose 未安装，请先安装 Docker Compose"
    exit 1
fi

# 检查 .env 文件
if [[ ! -f ".env" ]]; then
    echo "⚠️  .env 文件不存在"
    if [[ -f ".env.example" ]]; then
        echo "📄 从 .env.example 创建 .env 文件..."
        cp .env.example .env
        echo "✅ 请编辑 .env 文件并填入必要的 API 密钥"
    else
        echo "❌ 未找到 .env.example 文件"
        echo "💡 请手动创建 .env 文件并设置必要的环境变量"
    fi
fi

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
    "templates/patch_view.html"
    "static/css/style.css"
    "static/js/app.js"
    "docker-compose.yml"
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

# 检查并启动 Docker 服务
echo "🐳 检查 Docker 服务状态..."

# 检查 docker-compose.yml 是否存在必要的服务
if ! grep -q "app:" docker-compose.yml; then
    echo "❌ docker-compose.yml 中未找到 app 服务"
    exit 1
fi

if ! grep -q "neo4j:" docker-compose.yml; then
    echo "❌ docker-compose.yml 中未找到 neo4j 服务"
    exit 1
fi

# 检查现有容器状态
app_status=$(docker-compose ps -q app 2>/dev/null || echo "")
neo4j_status=$(docker-compose ps -q neo4j 2>/dev/null || echo "")

if [[ -z "$app_status" ]] || [[ -z "$neo4j_status" ]]; then
    echo "🚀 启动 Docker 服务..."
    docker-compose up -d --build
    echo "⏳ 等待服务启动..."
    sleep 15
    echo "✅ Docker 服务已启动"
else
    echo "✅ Docker 服务已运行"
fi

# 验证 Docker 服务
echo "🔍 验证 Docker 服务状态..."
if docker-compose ps | grep -q "Up"; then
    echo "✅ Docker 服务运行正常"
else
    echo "❌ Docker 服务启动失败"
    echo "📋 服务状态:"
    docker-compose ps
    exit 1
fi

# 设置环境变量
export FLASK_APP=app.py
export FLASK_ENV=development
export FLASK_DEBUG=1
export DOCKER_MODE=1

echo ""
echo "======================================================"
echo "🎉 KGCompass Web 界面启动完成! (Docker 模式)"
echo "======================================================"
echo "📡 访问地址: http://localhost:5000"
echo "🔧 开发模式: 已启用"
echo "🐳 Docker 容器: 已启动"
echo "📊 实时日志: WebSocket 支持"
echo "🛠️  停止服务: Ctrl+C"
echo ""
echo "🔧 Docker 服务管理:"
echo "   查看状态: docker-compose ps"
echo "   查看日志: docker-compose logs -f"
echo "   停止服务: docker-compose down"
echo "   重建服务: docker-compose up -d --build"
echo ""
echo "💡 注意: 修复过程将在 Docker 容器中执行"
echo "======================================================"
echo ""

# 启动 Flask 应用
echo "🌐 启动 Web 服务..."
python3 app.py 