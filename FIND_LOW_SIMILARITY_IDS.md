# 查找所有低相似度 Issue 匹配的 Instance IDs

## 🎯 目标

遍历 SWE-bench Verified 的所有实例，检查对应的 KG 结果，找出所有标题差异度过高的 instance_id 列表。

## 📋 准备工作

确保以下文件存在：
- ✅ `runs/kg_verified/` - KG 结果目录
- ✅ `django-tickets.csv` - Django tickets 数据（用于快速分析）
- ✅ `config.py` 中的 `GITHUB_TOKEN` - GitHub API 令牌

## 🚀 使用方法

### 方案 1：快速分析（仅 Django）⚡

**适用场景**: 只需要分析 Django 实例，速度快，无 API 限制

```bash
python analyze_all_verified_matches.py
```

**特点**:
- ✅ 速度快（几秒完成）
- ✅ 无 API 限制
- ❌ 仅分析 Django（约 200+ 个实例）
- ❌ 其他仓库会被跳过

**输出文件**:
- `low_similarity_instance_ids.txt` - 低相似度 instance_id 列表
- `low_similarity_matches_detailed.json` - 详细匹配信息
- `skipped_non_django_ids.txt` - 被跳过的非 Django 实例
- `analysis_summary.json` - 分析总结

### 方案 2：完整分析（所有仓库）🌐

**适用场景**: 需要分析所有仓库，完整但受 API 限制

```bash
python analyze_all_verified_with_api.py
```

**特点**:
- ✅ 分析所有仓库（完整）
- ✅ 支持断点续传（可中断后继续）
- ❌ 受 GitHub API rate limit 限制
- ❌ 需要较长时间（可能需要多次运行）

**API 限制说明**:
- Search API: 30 次/分钟
- Core API: 5000 次/小时
- 建议分批运行，脚本会自动保存进度

**输出文件**:
- `low_similarity_instance_ids.txt` - 低相似度 instance_id 列表
- `low_similarity_matches_detailed.json` - 详细匹配信息
- `analysis_progress.json` - 进度保存（可断点续传）

## 📊 输出示例

### low_similarity_instance_ids.txt
```
django__django-10097
django__django-10554
django__django-10880
django__django-11206
...
```

### low_similarity_matches_detailed.json
```json
[
  {
    "instance_id": "django__django-10097",
    "repo": "django/django",
    "expected_title": "Add a PostgreSQL table comment to a table",
    "matched_issue": 9823,
    "matched_title": "Allow customizing ValidationError's error_list class",
    "similarity": 0.234
  },
  ...
]
```

## 🔍 分析结果

运行完成后会显示：

```
📊 统计信息:
  - 总结果文件: 500
  - Django 实例分析: 220
  - 非 Django 跳过: 280
  - 低相似度匹配: 45
  - 未找到匹配: 12

🔴 低相似度匹配案例（< 0.5）：45 个
====================================================================================================

1. django__django-10097
   预期标题: Add a PostgreSQL table comment to a table
   匹配 Issue: #9823
   匹配标题: Allow customizing ValidationError's error_list class
   相似度: 0.234

2. django__django-10554
   预期标题: Password changed successfully page does not pass context
   匹配 Issue: #10432
   匹配标题: Template context processors should support kwargs
   相似度: 0.378
...
```

## 💡 使用建议

### 推荐流程：

1. **第一步**：先运行方案 1（快速分析 Django）
   ```bash
   python analyze_all_verified_matches.py
   ```

2. **第二步**：如果需要其他仓库，再运行方案 2
   ```bash
   python analyze_all_verified_with_api.py
   ```

3. **第三步**：合并结果（如果运行了两个脚本）
   ```bash
   cat low_similarity_instance_ids.txt | sort | uniq > final_low_similarity_ids.txt
   ```

### 断点续传（方案 2）

如果方案 2 因 API 限制中断：

```bash
# 脚本会自动检测 analysis_progress.json
# 直接重新运行即可继续
python analyze_all_verified_with_api.py
```

选择 "y" 从上次中断处继续。

### API 限制应对

如果遇到 API rate limit：

```bash
# 查看当前 API 状态
python -c "
from github import Github
from config import GITHUB_TOKEN
g = Github(GITHUB_TOKEN)
rl = g.get_rate_limit()
print(f'Search: {rl.search.remaining}/{rl.search.limit}')
print(f'Core: {rl.core.remaining}/{rl.core.limit}')
print(f'Reset: {rl.search.reset}')
"

# 等待重置后继续
python analyze_all_verified_with_api.py
```

## 📈 相似度阈值

当前阈值：**0.5**

- `< 0.3`: 几乎不相关，严重问题
- `0.3-0.5`: 低相似度，需要审查
- `0.5-0.7`: 中等相似，可接受
- `0.7+`: 高相似度，匹配良好

可以在脚本中修改 `SIMILARITY_THRESHOLD` 变量调整阈值。

## 🛠️ 故障排除

### 问题 1: 数据集加载失败

```bash
# 手动下载数据集
python -c "
from datasets import load_dataset
ds = load_dataset('princeton-nlp/SWE-bench_Verified', split='test')
print(f'Loaded {len(ds)} instances')
"
```

### 问题 2: GitHub API 认证失败

检查 `config.py` 中的 `GITHUB_TOKEN`:

```bash
python -c "
from config import GITHUB_TOKEN
from github import Github
g = Github(GITHUB_TOKEN)
print(f'User: {g.get_user().login}')
"
```

### 问题 3: 找不到结果文件

确认路径：

```bash
ls -R runs/kg_verified/ | head -20
```

## 📝 输出文件说明

| 文件 | 描述 | 重要性 |
|------|------|--------|
| `low_similarity_instance_ids.txt` | ⭐ Instance ID 列表（最重要） | ⭐⭐⭐ |
| `low_similarity_matches_detailed.json` | 详细匹配信息 | ⭐⭐⭐ |
| `analysis_summary.json` | 统计总结 | ⭐⭐ |
| `analysis_progress.json` | 进度保存（可删除） | ⭐ |
| `skipped_non_django_ids.txt` | 跳过的实例列表 | ⭐ |

## 🎉 完成后

拿到 `low_similarity_instance_ids.txt` 后，你可以：

1. **审查这些案例** - 确认是否确实匹配错误
2. **重新运行这些实例** - 使用修复后的代码
3. **调整参数** - 修改相似度阈值或匹配逻辑
4. **生成报告** - 分析低相似度的原因

## 📞 快速开始命令

```bash
# 一键运行（仅 Django）
python analyze_all_verified_matches.py

# 查看结果
cat low_similarity_instance_ids.txt
wc -l low_similarity_instance_ids.txt

# 查看详细信息
python -c "
import json
with open('low_similarity_matches_detailed.json') as f:
    data = json.load(f)
print(f'找到 {len(data)} 个低相似度案例')
for i, case in enumerate(data[:5], 1):
    print(f'{i}. {case[\"instance_id\"]}: {case[\"similarity\"]:.3f}')
"
```

---

**推荐**: 先运行快速方案，获得 Django 的低相似度列表，这已经覆盖了约 200+ 个实例。


