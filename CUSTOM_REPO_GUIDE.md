# KGCompass 自定义仓库支持指南

## 📋 改造概述

KGCompass 现已支持对**任意 GitHub 仓库的 Issue** 进行修复补丁生成，不再局限于 SWE-bench 数据集中的预定义仓库。

## 🎯 主要功能

### 1. 双模式支持

- **SWE-bench 仓库模式**：使用预定义的 SWE-bench 数据集仓库（原有功能）
- **自定义 GitHub 仓库模式**：支持任意 GitHub 开源项目（新功能）

### 2. GitHub 集成

- ✅ 自动验证 GitHub 仓库是否存在
- ✅ 自动获取仓库信息（描述、Stars、语言等）
- ✅ 自动验证 Issue 是否存在
- ✅ 自动获取 Issue 详情（标题、内容等）
- ✅ 支持多种 URL 格式输入

## 🚀 使用方法

### 方法 1: 使用 Web 界面

1. **启动 Web 服务**
   ```bash
   python app.py
   ```

2. **访问界面**
   - 打开浏览器访问：http://localhost:5000

3. **选择自定义仓库模式**
   - 点击 "自定义 GitHub 仓库" 选项卡

4. **输入仓库信息**
   - **GitHub 仓库 URL**：支持以下格式
     - `https://github.com/owner/repo`
     - `https://github.com/owner/repo.git`
     - `github.com/owner/repo`
     - `owner/repo`
   - **Issue 编号**：输入要修复的 Issue 号码（纯数字）

5. **验证仓库**
   - 点击 "验证仓库和 Issue" 按钮
   - 或直接输入后等待自动验证（1秒后）
   - 系统会显示仓库信息和验证状态

6. **开始修复**
   - 验证通过后，点击 "开始修复" 按钮
   - 实时查看修复进度和日志
   - 完成后可下载或查看生成的补丁

### 方法 2: 使用命令行（Docker）

```bash
# 直接在 Docker 容器中执行自定义修复
docker-compose exec app bash run_repair_custom.sh \
    "owner__repo-123" \
    "https://github.com/owner/repo.git" \
    "owner__repo" \
    "123"
```

参数说明：
- 参数1：实例ID（格式：owner__repo-issue_number）
- 参数2：Git 克隆 URL
- 参数3：仓库标识符（格式：owner__repo）
- 参数4：Issue 编号

## 📁 文件结构

### 新增/修改的文件

```
KGCompass/
├── app.py                        # [修改] 添加 GitHub API 集成和自定义仓库支持
├── run_repair_custom.sh          # [新增] 自定义仓库修复脚本
├── requirements_web.txt          # [修改] 添加 requests 依赖
├── templates/
│   └── index.html                # [修改] 添加自定义仓库输入界面
├── static/
│   └── js/
│       └── app.js                # [修改] 添加自定义仓库前端逻辑
└── CUSTOM_REPO_GUIDE.md          # [新增] 本文档
```

## 🔧 技术实现

### 后端改造（app.py）

1. **GitHubHelper 类**
   - `parse_github_url()`: 解析多种格式的 GitHub URL
   - `validate_repo()`: 验证仓库是否存在
   - `get_repo_info()`: 获取仓库详细信息
   - `get_issue_info()`: 获取 Issue 详细信息

2. **RepairTaskManager 扩展**
   - `start_repair_task()`: 支持自定义仓库参数
   - `_execute_custom_repair_pipeline()`: 自定义仓库修复流程
   - `_create_custom_instance_file()`: 创建实例数据文件

3. **新增 API 端点**
   - `POST /api/validate_github_repo`: 验证 GitHub 仓库和 Issue
   - `POST /api/start_repair`: 扩展支持自定义仓库模式

### 前端改造

1. **双模式选项卡**
   - Bootstrap Tabs 实现模式切换
   - 独立的表单验证逻辑

2. **实时验证**
   - 输入1秒后自动验证
   - 显示仓库信息和验证状态

3. **状态管理**
   - `isCustomMode`: 当前模式标识
   - `validatedRepoInfo`: 已验证的仓库信息

## 🔑 GitHub Token（可选）

为了避免 GitHub API 速率限制，可以设置环境变量：

```bash
export GITHUB_TOKEN="your_github_personal_access_token"
```

或在 `.env` 文件中添加：
```
GITHUB_TOKEN=your_github_personal_access_token
```

### 创建 GitHub Token

1. 访问：https://github.com/settings/tokens
2. 点击 "Generate new token (classic)"
3. 选择 `public_repo` 权限
4. 生成并复制 Token

## 📊 API 限制

- **无 Token**: 60 次/小时
- **有 Token**: 5000 次/小时

## 🎯 支持的仓库类型

理论上支持所有公开的 GitHub 仓库，但建议：

- ✅ Python 项目（最佳支持）
- ⚠️ 其他语言项目（需要确保 KGCompass 支持该语言）
- ❌ 私有仓库（需要配置 GitHub Token 并有权限）

## 🐛 故障排查

### 问题：仓库验证失败

**可能原因：**
- 仓库不存在或已删除
- 仓库是私有的
- GitHub API 限制（添加 Token）
- 网络连接问题

### 问题：Issue 验证失败

**可能原因：**
- Issue 编号不存在
- Issue 是 Pull Request（不支持）
- GitHub API 限制

### 问题：修复流程失败

**可能原因：**
- 仓库代码结构不符合预期
- 缺少必要的依赖
- Issue 描述信息不足
- Neo4j 连接问题

## 📝 示例

### 示例 1: 修复 Flask 的 Issue

```
仓库 URL: https://github.com/pallets/flask
Issue 编号: 4992
```

### 示例 2: 修复 Requests 的 Issue

```
仓库 URL: psf/requests
Issue 编号: 2148
```

### 示例 3: 修复任意项目

```
仓库 URL: https://github.com/username/project
Issue 编号: 42
```

## 🔄 工作流程

```
用户输入仓库和Issue
    ↓
验证仓库和Issue（GitHub API）
    ↓
克隆仓库到 playground/
    ↓
KG-based Bug Location（知识图谱分析）
    ↓
LLM-based Bug Location（大模型定位）
    ↓
Merge and Fix（融合定位结果）
    ↓
Patch Generation（生成修复补丁）
    ↓
下载/查看补丁
```

## 📈 性能优化

- 仓库克隆后会缓存，重复修复同一仓库会更快
- 中间结果会缓存，可以复用之前的分析结果
- 支持断点续传，失败后可以从上次位置继续

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

与 KGCompass 主项目保持一致

---

**注意**: 这是实验性功能，对于非 SWE-bench 数据集的仓库，修复成功率可能会有所不同。建议先在小型、结构清晰的项目上测试。






