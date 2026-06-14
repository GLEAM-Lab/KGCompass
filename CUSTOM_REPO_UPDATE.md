# 🎯 自定义仓库支持 - 重要更新

## 📋 更新内容

### 修复的问题

之前的实现中，`kgcompass/fl.py` 仍然试图从 SWE-bench 数据集中查找实例，导致自定义仓库（如 SWE-bench 自己的 Issue）无法正常工作。

### 解决方案

添加了 **`custom` benchmark 模式**，让 KGCompass 可以：

1. **直接从 GitHub 获取 Issue 信息**，不依赖 SWE-bench 数据集
2. **包括所有评论**，提供完整的上下文
3. **自动处理任意 GitHub 仓库**

## 🚀 现在可以工作了！

### 测试 SWE-bench Issue #449

```bash
docker-compose exec app bash run_repair_custom.sh \
    "SWE-bench__SWE-bench-449" \
    "https://github.com/SWE-bench/SWE-bench.git" \
    "SWE-bench__SWE-bench" \
    "449"
```

### 预期输出

```
=================================================
Starting KGCompass repair for custom repository
Instance ID: SWE-bench__SWE-bench-449
Repository: SWE-bench__SWE-bench
Clone URL: https://github.com/SWE-bench/SWE-bench.git
Issue Number: 449
=================================================

--- Step 1: KG-based Bug Location ---
⚙️  正在分析代码结构，构建知识图谱...
Custom repository mode: repo_name='SWE-bench/SWE-bench'
Fetching issue #449 from GitHub for SWE-bench/SWE-bench...
Successfully fetched issue #449 from GitHub
  Title: report_dir CLI argument not working as expected in SWE-bench
  Created: 2025-08-07 XX:XX:XX
  Comments: X

✅ 知识图谱构建完成
```

## 📝 修改的文件

### 1. `kgcompass/fl.py`

**新增 `custom` benchmark 支持：**

```python
if benchmark_name == 'custom':
    # 直接从 GitHub 获取 Issue 信息
    # 不依赖 SWE-bench 数据集
    repo = self.github.get_repo(self.config['repo_name'])
    issue = repo.get_issue(int(issue_number))
    
    # 获取完整内容（包括所有评论）
    # 构造 target_sample
```

**主程序增强：**

```python
if benchmark_name_arg == 'custom':
    # 解析自定义仓库的 instance_id
    # 格式: OWNER__REPO-ISSUENUMBER
    repo_name = owner_repo_part.replace('__', '/', 1)
```

### 2. `run_repair_custom.sh`

**传递 `custom` benchmark：**

```bash
# 调用 fl.py 时传递 'custom' 作为第4个参数
python3 kgcompass/fl.py "$INSTANCE_ID" "$REPO_IDENTIFIER" "$KG_LOCATIONS_DIR" "custom"
```

## 🎯 支持的仓库格式

### Instance ID 格式

```
OWNER__REPO-ISSUENUMBER
```

**示例：**
- `SWE-bench__SWE-bench-449`
- `pallets__flask-4992`
- `django__django-11001`
- `microsoft__vscode-12345`

### Repo Name 格式

```
OWNER/REPO
```

**示例：**
- `SWE-bench/SWE-bench`
- `pallets/flask`
- `django/django`
- `microsoft/vscode`

## 🔧 工作流程

### 1. Clone 仓库

```bash
git clone https://github.com/OWNER/REPO.git playground/OWNER__REPO/
```

### 2. 获取 Issue 信息

```python
# 从 GitHub API 获取
issue = github.get_repo('OWNER/REPO').get_issue(ISSUE_NUMBER)

# 构造 problem_statement
problem_statement = f"# {issue.title}\n\n{issue.body}\n\n{comments}"
```

### 3. 分析代码

- KG-based 定位
- LLM-based 定位
- 结果融合
- 生成补丁

## 🆚 模式对比

### SWE-bench 模式 (原有)

```bash
# 从 SWE-bench 数据集加载
python3 kgcompass/fl.py "django__django-11001" "django__django" "./output"
```

- ✅ 使用预定义的数据集
- ✅ 包含测试用例
- ❌ 仅限 SWE-bench 中的实例

### Custom 模式 (新增)

```bash
# 从 GitHub 直接获取
python3 kgcompass/fl.py "SWE-bench__SWE-bench-449" "SWE-bench__SWE-bench" "./output" "custom"
```

- ✅ 支持任意 GitHub 仓库
- ✅ 直接从 GitHub 获取最新信息
- ✅ 包括所有评论
- ⚠️ 没有预定义的测试用例

## 💡 使用建议

### 推荐使用 Web 界面

```bash
# 1. 启动 Web 服务
python app.py

# 2. 浏览器访问
http://localhost:5000

# 3. 选择"自定义 GitHub 仓库"
# 4. 输入: SWE-bench/SWE-bench
# 5. Issue: 449
# 6. 点击"开始修复"
```

### 命令行快捷方式

```bash
# 使用测试脚本
./test_swebench_issue_449.sh

# 或直接使用 run_repair_custom.sh
docker-compose exec app bash run_repair_custom.sh \
    "OWNER__REPO-ISSUE" \
    "https://github.com/OWNER/REPO.git" \
    "OWNER__REPO" \
    "ISSUE"
```

## 🐛 故障排查

### 问题：找不到实例

**症状：**
```
No sample found for instance_id 'XXX' in repo 'YYY' for benchmark 'swe-bench'
```

**解决方案：**
- ✅ 确保使用 `custom` benchmark（已修复）
- ✅ 使用 `run_repair_custom.sh` 而不是 `run_repair.sh`

### 问题：GitHub API 限制

**症状：**
```
GitHub API rate limit exceeded
```

**解决方案：**
```bash
# 设置 GitHub Token
export GITHUB_TOKEN="your_token_here"
```

### 问题：Issue 不存在

**症状：**
```
Error: Issue #XXX not found in OWNER/REPO
```

**解决方案：**
- 检查 Issue 号是否正确
- 确认仓库名格式正确
- 验证 Issue 是公开的

## ✅ 验证修复

### 快速测试

```bash
# 1. 测试 GitHub API 访问
curl https://api.github.com/repos/SWE-bench/SWE-bench/issues/449

# 2. 运行修复流程
docker-compose exec app bash run_repair_custom.sh \
    "SWE-bench__SWE-bench-449" \
    "https://github.com/SWE-bench/SWE-bench.git" \
    "SWE-bench__SWE-bench" \
    "449"

# 3. 检查结果
ls -la tests/SWE-bench__SWE-bench-449_deepseek/
```

### 期望的输出

```
tests/SWE-bench__SWE-bench-449_deepseek/
├── kg_locations/
│   └── SWE-bench__SWE-bench-449.json     ✅ KG 分析结果
├── llm_locations/
│   └── SWE-bench__SWE-bench-449.json     ✅ LLM 定位结果
├── final_locations/
│   └── SWE-bench__SWE-bench-449.json     ✅ 融合结果
└── patches/
    └── *.diff                             ✅ 修复补丁
```

## 📚 相关文档

- **[NEW_FEATURES.md](NEW_FEATURES.md)** - 新功能概览
- **[CUSTOM_REPO_GUIDE.md](CUSTOM_REPO_GUIDE.md)** - 完整使用指南
- **[TEST_SWEBENCH_ISSUE_449.md](TEST_SWEBENCH_ISSUE_449.md)** - Issue #449 测试指南

## 🎉 总结

通过这次更新：

1. ✅ **修复了自定义仓库无法工作的问题**
2. ✅ **添加了 `custom` benchmark 模式**
3. ✅ **直接从 GitHub 获取 Issue 信息**
4. ✅ **支持任意公开 GitHub 仓库**
5. ✅ **包括完整的 Issue 上下文（评论等）**

现在你可以使用 KGCompass 修复**任何 GitHub 项目**的 Issue，包括 SWE-bench 自己的 Issue #449！🚀

---

**下一步：** 运行 `./test_swebench_issue_449.sh` 开始测试！






