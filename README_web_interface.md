# KGCompass Web 界面

一个直观的 Web 界面，让用户能够轻松体验 KGCompass 的软件修复流程，实时查看修复过程并获取最终补丁。

## 🌟 特性

### 🎯 核心功能
- **直观操作**: 通过 Web 界面选择仓库和输入 Issue ID
- **实时反馈**: WebSocket 实时显示修复进度和日志
- **流程可视化**: 清晰展示知识图谱挖掘、故障定位、补丁生成等步骤
- **补丁下载**: 修复完成后可直接下载生成的补丁文件
- **多仓库支持**: 支持 12 个热门 Python 开源项目

### 🛠️ 技术特性
- **响应式设计**: 支持桌面和移动设备
- **现代化界面**: 使用 Bootstrap 5 和 Font Awesome
- **实时通信**: 基于 Socket.IO 的双向通信
- **优雅动画**: 流畅的过渡效果和加载动画
- **错误处理**: 完善的错误处理和用户反馈

## 📋 支持的仓库

| 仓库 | 描述 | Stars |
|------|------|-------|
| astropy/astropy | Python库，用于天文学和天体物理学 | 4.3k ⭐ |
| django/django | 高级Python Web框架 | 79k ⭐ |
| matplotlib/matplotlib | Python 2D绘图库 | 19k ⭐ |
| mwaskom/seaborn | 基于matplotlib的统计数据可视化库 | 12k ⭐ |
| psf/requests | 优雅简洁的Python HTTP库 | 52k ⭐ |
| pallets/flask | 轻量级Python Web框架 | 67k ⭐ |
| pydata/xarray | N-D标记数组和数据集处理库 | 3.6k ⭐ |
| pylint-dev/pylint | Python代码静态分析工具 | 5.2k ⭐ |
| pytest-dev/pytest | Python测试框架 | 11k ⭐ |
| scikit-learn/scikit-learn | Python机器学习库 | 59k ⭐ |
| sphinx-doc/sphinx | Python文档生成工具 | 6.4k ⭐ |
| sympy/sympy | Python符号数学库 | 12k ⭐ |

## 🚀 快速开始

### 方法一：Docker 模式（推荐 - 完整功能）

Docker 模式提供完整的 KGCompass 修复功能，包括 Neo4j 数据库和 GPU 支持。

```bash
# 给启动脚本添加执行权限
chmod +x start_web_docker.sh

# 启动 Docker 模式 Web 界面
./start_web_docker.sh
```

**前置要求**：
- Docker 和 Docker Compose
- NVIDIA GPU 和 Container Toolkit（用于 GPU 加速）
- `.env` 文件配置（API 密钥等）

### 方法二：独立模式（仅演示）

独立模式仅用于界面演示，不执行真实的修复流程。

```bash
# 给启动脚本添加执行权限
chmod +x start_web.sh

# 启动独立模式 Web 界面
./start_web.sh
```

### 方法三：手动启动

```bash
# 1. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 2. 安装依赖
pip install -r requirements_web.txt

# 3. 启动应用
python3 app.py
```

### 访问界面

打开浏览器访问: **http://localhost:5000**

## 🎮 使用指南

### 1. 选择仓库
- 从下拉菜单中选择要修复的仓库
- 界面会显示仓库描述和星标数

### 2. 输入实例ID
- 输入 SWE-bench 格式的实例ID
- 格式: `repo__repo-number`（如：`astropy__astropy-12907`）

### 3. 使用快速示例
- 点击界面上的示例按钮快速填充
- 选择仓库后会显示该仓库的相关示例

### 4. 开始修复
- 点击"开始修复"按钮启动流程
- 实时查看修复进度和详细日志

### 5. 获取结果
- 修复完成后可下载补丁文件
- 查看修复报告了解详细信息

## 🔄 修复流程

### 阶段 1: 知识图谱挖掘 (0-30%)
- 📥 克隆仓库
- 🔍 分析代码结构
- 📊 构建知识图谱
- 🔗 链接问题和代码
- 💾 保存KG数据

### 阶段 2: LLM 故障定位 (30-60%)
- 📖 分析问题描述
- 🤖 调用Claude模型
- 🎯 定位可疑文件
- 📍 识别可疑方法

### 阶段 3: 结果融合 (60-80%)
- 🔗 合并KG和LLM的定位结果
- ✅ 优化定位精度

### 阶段 4: 补丁生成 (80-100%)
- 📝 准备修复上下文
- 🤖 调用Claude API
- ⚡ 生成候选补丁
- ✅ 验证补丁语法

## 📁 项目结构

```
KGCompass/
├── app.py                      # Flask 主应用
├── requirements_web.txt        # Web 界面依赖
├── start_web.sh               # 快速启动脚本
├── templates/
│   └── index.html             # 主页模板
├── static/
│   ├── css/
│   │   └── style.css          # 自定义样式
│   └── js/
│       └── app.js             # 前端逻辑
└── web_outputs/               # 输出目录
    └── [task_id]/
        ├── [instance]_patch.diff    # 补丁文件
        └── [instance]_report.json   # 修复报告
```

## 🔧 技术栈

### 后端
- **Flask**: Web 框架
- **Flask-SocketIO**: WebSocket 支持
- **Threading**: 异步任务处理
- **JSON**: 数据交换格式

### 前端
- **Bootstrap 5**: UI 框架
- **Font Awesome**: 图标库
- **Socket.IO**: 实时通信
- **Vanilla JavaScript**: 前端逻辑

### 核心依赖
```python
Flask==3.0.0
Flask-SocketIO==5.3.6
python-socketio==5.10.0
```

## 📊 示例用法

### 1. 简单修复任务
```
仓库: matplotlib/matplotlib
实例ID: matplotlib__matplotlib-13989
问题: hist() 函数在 density=True 时不遵守 range 参数
```

### 2. 复杂修复任务
```
仓库: scikit-learn/scikit-learn
实例ID: scikit-learn__scikit-learn-13497
问题: 机器学习算法的性能优化问题
```

## 🎯 高级功能

### 实时日志
- WebSocket 连接实时推送执行日志
- 自动滚动到最新日志
- 支持日志搜索和过滤

### 任务管理
- 支持多个并发修复任务
- 任务状态实时更新
- 任务历史记录

### 错误处理
- 优雅的错误处理和用户反馈
- 详细的错误信息和解决建议
- 自动重试机制

## 🔍 故障排除

### 常见问题

**1. 端口被占用**
```bash
# 查找占用端口的进程
lsof -i :5000

# 杀死进程（替换 PID）
kill -9 <PID>
```

**2. 依赖安装失败**
```bash
# 升级 pip
pip install --upgrade pip

# 清理缓存重新安装
pip cache purge
pip install -r requirements_web.txt
```

**3. WebSocket 连接失败**
- 检查防火墙设置
- 确保端口 5000 可访问
- 检查浏览器 WebSocket 支持

### 调试模式

启用详细日志：
```bash
export FLASK_DEBUG=1
python3 app.py
```

## 🚧 开发说明

### 本地开发环境

```bash
# 克隆仓库
git clone <repo-url>
cd KGCompass

# 安装开发依赖
pip install -r requirements_web.txt

# 启动开发服务器
python3 app.py
```

### 自定义配置

修改 `app.py` 中的配置：
```python
# 更改端口
socketio.run(app, host='0.0.0.0', port=8080, debug=True)

# 添加新的仓库
SUPPORTED_REPOS['new_repo'] = {
    "name": "owner/repo",
    "description": "描述",
    "language": "Python",
    "stars": "1k"
}
```

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 项目
2. 创建特性分支
3. 提交更改
4. 推送到分支
5. 创建 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🙏 致谢

- [KGCompass 论文](https://arxiv.org/abs/2503.21710) - 核心算法
- [SWE-bench](https://www.swebench.com/) - 评估数据集
- [Bootstrap](https://getbootstrap.com/) - UI 框架
- [Font Awesome](https://fontawesome.com/) - 图标库

---

**🚀 开始您的软件修复之旅！** 