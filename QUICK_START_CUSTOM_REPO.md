# 🚀 快速开始：自定义仓库修复

## 前提条件

1. Docker 和 Docker Compose 已安装
2. Python 3.8+ 已安装
3. 网络连接正常（需要访问 GitHub API）

## 5 分钟快速开始

### 步骤 1: 安装依赖

```bash
cd /home/barty/GLEAM-Lab/KGCompass
pip install -r requirements_web.txt
```

### 步骤 2: 启动服务

```bash
# 启动 Neo4j 和 Docker 服务（如果还没启动）
docker-compose up -d

# 启动 Web 界面
python app.py
```

### 步骤 3: 访问 Web 界面

打开浏览器访问：http://localhost:5000

### 步骤 4: 使用自定义仓库

1. 点击 **"自定义 GitHub 仓库"** 选项卡
2. 输入仓库 URL（例如：`pallets/flask`）
3. 输入 Issue 编号（例如：`4992`）
4. 点击 **"验证仓库和 Issue"**
5. 验证通过后，点击 **"开始修复"**
6. 等待修复完成，下载或查看补丁

## 🎯 快速测试示例

### 示例 1: Flask 项目

```
仓库: pallets/flask
Issue: 4992
预期: 应该能成功生成修复补丁
```

### 示例 2: Requests 项目

```
仓库: https://github.com/psf/requests
Issue: 2148
预期: 应该能成功生成修复补丁
```

### 示例 3: Django 项目

```
仓库: django/django
Issue: 11001
预期: 应该能成功生成修复补丁（SWE-bench 中的示例）
```

## 📊 功能验证清单

- [ ] GitHub 仓库 URL 解析正常
- [ ] 仓库验证功能正常
- [ ] Issue 验证功能正常
- [ ] 仓库信息显示正确
- [ ] 修复流程能够启动
- [ ] 实时日志显示正常
- [ ] 进度更新正常
- [ ] 补丁文件生成成功
- [ ] 补丁下载功能正常
- [ ] 补丁预览功能正常

## 🔧 故障排查

### 问题 1: 无法连接到 GitHub API

**解决方案：**
```bash
# 检查网络连接
curl https://api.github.com/repos/pallets/flask

# 如果需要，设置代理
export http_proxy=http://your-proxy:port
export https_proxy=http://your-proxy:port
```

### 问题 2: API 速率限制

**解决方案：**
```bash
# 设置 GitHub Token
export GITHUB_TOKEN="your_github_token_here"

# 或在 .env 文件中添加
echo "GITHUB_TOKEN=your_github_token_here" >> .env
```

### 问题 3: Docker 服务未启动

**解决方案：**
```bash
# 检查 Docker 服务状态
docker-compose ps

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 问题 4: 修复流程失败

**解决方案：**
```bash
# 查看详细日志
docker-compose logs app

# 检查 Neo4j 连接
docker-compose logs neo4j

# 重启服务
docker-compose restart
```

## 🧪 运行测试

```bash
# 基础测试（不需要启动 Flask）
python test_custom_repo.py

# 完整测试（需要先启动 Flask）
python app.py &  # 后台运行
python test_custom_repo.py --with-flask
```

## 📝 测试结果示例

成功的修复流程应该显示：

```
🚀 开始为自定义仓库 pallets/flask Issue #4992 执行修复流程
✅ Docker 服务已运行
📝 已创建实例数据文件
🔄 开始执行修复流程...
⚙️  正在分析代码结构，构建知识图谱...
✅ 知识图谱构建完成
⚙️  使用大语言模型分析问题描述，定位可疑代码...
✅ 故障定位分析完成
⚙️  融合知识图谱和LLM定位结果，精确定位错误位置...
✅ 错误定位融合完成
⚙️  基于定位结果生成修复补丁...
✅ 修复补丁生成完成
✅ 补丁文件已存在
📄 补丁内容预览:
  --- a/src/flask/app.py
  +++ b/src/flask/app.py
  @@ -123,7 +123,7 @@
...
🎉 pallets__flask-4992 修复完成!
```

## 🎓 进阶使用

### 使用命令行模式

```bash
# 直接在 Docker 容器中执行
docker-compose exec app bash run_repair_custom.sh \
    "pallets__flask-4992" \
    "https://github.com/pallets/flask.git" \
    "pallets__flask" \
    "4992"
```

### 批量处理

```bash
# 创建批量处理脚本
cat > batch_repair.sh << 'EOF'
#!/bin/bash
repos=(
  "pallets/flask:4992"
  "psf/requests:2148"
  "django/django:11001"
)

for item in "${repos[@]}"; do
  IFS=':' read -r repo issue <<< "$item"
  echo "Processing $repo #$issue"
  # 调用 API 或命令行工具
done
EOF

chmod +x batch_repair.sh
./batch_repair.sh
```

## 📚 更多资源

- [完整功能文档](CUSTOM_REPO_GUIDE.md)
- [KGCompass 主文档](README.md)
- [Web 界面总结](WEB_INTERFACE_SUMMARY.md)
- [配置说明](CONFIG.md)

## 🤝 获取帮助

如果遇到问题：

1. 查看日志文件：`web_outputs/*/`
2. 检查 Docker 日志：`docker-compose logs`
3. 运行测试脚本：`python test_custom_repo.py`
4. 查看完整文档：`CUSTOM_REPO_GUIDE.md`

## 🎉 成功！

如果你看到补丁文件生成，恭喜你已经成功使用 KGCompass 修复自定义仓库的 Issue！

---

**下一步**: 尝试更多的仓库和 Issue，探索 KGCompass 的强大功能！






