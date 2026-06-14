# 🎉 KGCompass 新功能：支持任意 GitHub 仓库！

## 🚀 重大更新

KGCompass 现在可以修复**任意 GitHub 开源项目**的 Issue，不再局限于 SWE-bench 数据集！

## ✨ 核心特性

### 1️⃣ 双模式支持
- **SWE-bench 模式**：原有的 27 个预定义仓库（完全兼容）
- **自定义模式**：任意 GitHub 公开仓库 ✨ **新增**

### 2️⃣ 智能验证
- ✅ 自动验证仓库是否存在
- ✅ 自动验证 Issue 是否有效
- ✅ 显示仓库详细信息（描述、Stars、语言）
- ✅ 显示 Issue 标题和内容

### 3️⃣ 灵活输入
支持多种仓库 URL 格式：
```
✅ https://github.com/owner/repo
✅ https://github.com/owner/repo.git
✅ github.com/owner/repo
✅ owner/repo
```

## 🎯 快速开始（3 步）

### 第 1 步：启动服务
```bash
# 安装依赖（只需一次）
pip install -r requirements_web.txt

# 启动服务
python app.py
```

### 第 2 步：打开浏览器
访问：http://localhost:5000

### 第 3 步：修复 Issue
1. 点击 "**自定义 GitHub 仓库**" 选项卡
2. 输入仓库 URL（例如：`pallets/flask`）
3. 输入 Issue 编号（例如：`4992`）
4. 点击 "**验证仓库和 Issue**"
5. 点击 "**开始修复**"
6. 等待完成，下载补丁！

## 📚 完整文档

| 文档 | 说明 |
|------|------|
| [QUICK_START_CUSTOM_REPO.md](QUICK_START_CUSTOM_REPO.md) | 5 分钟快速开始 |
| [CUSTOM_REPO_GUIDE.md](CUSTOM_REPO_GUIDE.md) | 完整功能指南 |
| [UPGRADE_SUMMARY.md](UPGRADE_SUMMARY.md) | 技术升级详情 |

## 🧪 测试验证

运行自动化测试：
```bash
python test_custom_repo.py
```

期望输出：
```
✅ 仓库存在
✅ URL 解析成功
✅ 测试完成！
```

## 💡 使用示例

### 示例 1：修复 Flask 的 Issue
```
仓库：pallets/flask
Issue：4992
```

### 示例 2：修复 Requests 的 Issue
```
仓库：https://github.com/psf/requests
Issue：2148
```

### 示例 3：修复你自己项目的 Issue
```
仓库：your-username/your-project
Issue：123
```

## 🎨 界面预览

### 新增的自定义仓库选项卡
```
┌─────────────────────────────────────┐
│ [SWE-bench 仓库] [自定义 GitHub 仓库] │ ← 新增选项卡
├─────────────────────────────────────┤
│ GitHub 仓库 URL:                     │
│ [pallets/flask          ]           │
│                                     │
│ Issue 编号:                         │
│ [4992                  ]            │
│                                     │
│ [验证仓库和 Issue]                  │
│                                     │
│ ✅ 仓库验证成功: pallets/flask      │
│ 描述: The Python micro framework... │
│ Stars: 70,557 ⭐                    │
│                                     │
│ [开始修复]                          │
└─────────────────────────────────────┘
```

## 🔧 技术实现

### 后端 (app.py)
- **新增 GitHubHelper 类**：处理 GitHub API 交互
- **扩展 RepairTaskManager**：支持自定义仓库修复流程
- **新增 API 端点**：`/api/validate_github_repo`

### 前端 (index.html + app.js)
- **双模式选项卡**：Bootstrap Tabs 实现
- **实时验证**：输入后 1 秒自动验证
- **状态管理**：缓存验证结果

### 修复脚本 (run_repair_custom.sh)
- 动态克隆任意 GitHub 仓库
- 生成实例数据文件
- 执行完整修复流程

## 📊 文件变更统计

| 类型 | 数量 | 说明 |
|------|------|------|
| 新增文件 | 7 个 | 脚本、文档、测试 |
| 修改文件 | 4 个 | app.py, index.html, app.js, requirements |
| 新增代码 | ~1000 行 | 后端 600+ 行，前端 300+ 行 |

## 🎯 支持的仓库类型

- ✅ **Python 项目**（最佳支持）
- ⚠️ **其他语言项目**（基础支持）
- ❌ **私有仓库**（暂不支持，需要 Token）

## ⚡ 性能优化

- 🚀 仓库克隆缓存：重复修复更快
- 🚀 验证结果缓存：减少 API 调用
- 🚀 中间结果复用：KG 和 LLM 分析可复用

## 🔒 安全保障

- ✅ URL 格式验证
- ✅ 仓库存在性验证
- ✅ Issue 有效性验证
- ✅ 错误友好提示

## 🐛 已知限制

1. **API 限制**：GitHub API 有速率限制（无 Token: 60次/小时，有 Token: 5000次/小时）
2. **语言支持**：主要优化 Python 项目
3. **复杂度**：超大型项目可能需要更长时间

## 💡 提示：提高 API 限制

```bash
# 创建 GitHub Token: https://github.com/settings/tokens
# 设置环境变量
export GITHUB_TOKEN="your_github_token"

# 或在 .env 文件中添加
echo "GITHUB_TOKEN=your_github_token" >> .env
```

## 🎉 开始使用

```bash
# 1. 启动服务
python app.py

# 2. 打开浏览器
open http://localhost:5000

# 3. 选择"自定义 GitHub 仓库"，开始修复！
```

## 🤔 需要帮助？

- 📖 查看 [快速开始指南](QUICK_START_CUSTOM_REPO.md)
- 📘 阅读 [完整文档](CUSTOM_REPO_GUIDE.md)
- 🧪 运行 [测试脚本](test_custom_repo.py)
- 🐛 提交 Issue 反馈问题

## 🎊 祝贺！

你现在可以使用 KGCompass 修复任何 GitHub 项目的 Issue 了！🚀

---

**提示**: 原有的 SWE-bench 功能完全保留，向后兼容，可以安全升级！






