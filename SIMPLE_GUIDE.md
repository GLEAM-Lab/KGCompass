# 简单指南：找出低相似度 Issue 匹配的实例

## 核心理解

- ✅ **Django 项目**: 使用本地 CSV (`django-tickets.csv`)，**不需要检查**
- 🔍 **非 Django 项目**: 通过 GitHub API 搜索匹配，**需要检查相似度**

## 🎯 目标

找出所有非 Django 项目中，benchmark 标题与挖掘出的 issue 标题差异过大的 instance_id 列表。

## 📝 两步走方案

### 步骤 1: 列出非 Django 实例（必需）

```bash
python3 list_non_django_instances.py
```

**输出文件**:
- `non_django_instance_ids.txt` - 所有非 Django 实例的 ID
- `non_django_instances_detail.json` - 详细信息（含 benchmark 标题）

这一步**不需要网络**，几秒钟完成。

### 步骤 2: 检查匹配质量（两种方式）

#### 方式 A：从现有日志提取（推荐，如果有日志）

如果你之前运行过 fl.py 并保存了日志：

```bash
python3 extract_issue_matches_from_logs.py
```

**前提**: `logs/` 目录下有运行日志

**输出**:
- `low_similarity_instance_ids.txt` - 低相似度的 instance_id
- `low_similarity_matches_from_logs.json` - 详细对比信息

#### 方式 B：重新运行并记录（如果没有日志）

对非 Django 实例重新运行 fl.py 并记录日志：

```bash
# 单个实例
./run_with_analysis.sh <instance_id> <repo_path> output_dir

# 批量处理（示例）
for id in $(cat non_django_instance_ids.txt | head -10); do
    echo "处理 $id ..."
    # 提取 repo_path（简化示例）
    python3 kgcompass/fl.py $id <repo_path> output_dir 2>&1 | tee logs/${id}.log
done

# 然后运行
python3 extract_issue_matches_from_logs.py
```

## 📊 快速示例

```bash
# 1. 列出非 Django 实例
python3 list_non_django_instances.py

# 输出示例:
# 📊 统计结果:
#   - Django 实例: 220 个（使用本地 CSV，无需检查）
#   - 非 Django 实例: 280 个（需要检查 issue 匹配质量）

# 2. 如果有日志，直接分析
python3 extract_issue_matches_from_logs.py

# 输出示例:
# 🔴 低相似度匹配案例（< 0.5）：
# 
# 1. matplotlib__matplotlib-23412
#    预期标题: Fix colorbar ticks for LogNorm
#    匹配 Issue: #23401
#    匹配标题: Add option to disable colorbar
#    相似度: 0.345

# 3. 查看结果
cat low_similarity_instance_ids.txt
```

## 📁 输出文件说明

| 文件 | 来源 | 内容 |
|------|------|------|
| `non_django_instance_ids.txt` | 步骤1 | 所有非 Django 实例 |
| `non_django_instances_detail.json` | 步骤1 | 非 Django 实例详情 |
| `low_similarity_instance_ids.txt` | 步骤2 | ⭐ 低相似度实例列表 |
| `low_similarity_matches_from_logs.json` | 步骤2 | 详细对比信息 |

## ⚙️ 调整阈值

在脚本中修改 `SIMILARITY_THRESHOLD`（默认 0.5）：

```python
# extract_issue_matches_from_logs.py 第 18 行
SIMILARITY_THRESHOLD = 0.5  # 改为 0.3 或 0.7
```

## ❓ 如果没有日志怎么办？

**选项 1**: 重新运行几个实例生成日志
```bash
# 随机选几个测试
head -5 non_django_instance_ids.txt | while read id; do
    ./run_with_analysis.sh $id <repo_path> output_dir
done
```

**选项 2**: 查看是否有集中式运行日志
```bash
# 检查是否有批量运行的日志
ls logs/
ls *.log
```

**选项 3**: 手动检查几个案例
```bash
# 查看某个实例的详细信息
python3 -c "
import json
with open('non_django_instances_detail.json') as f:
    instances = json.load(f)
for inst in instances[:5]:
    print(f'{inst[\"instance_id\"]}: {inst[\"title\"][:60]}')
"
```

## 🎉 最终目标

拿到 `low_similarity_instance_ids.txt`，这个文件包含所有需要重点关注的实例 ID。

---

**总结**: 
1. 运行 `list_non_django_instances.py` 获取非 Django 列表（必需）
2. 如果有日志，运行 `extract_issue_matches_from_logs.py` 分析（推荐）
3. 如果没日志，考虑重新运行部分实例或手动检查


