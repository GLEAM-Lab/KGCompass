# Issue 匹配质量分析工具

## 概述

当前 `fl.py` 的 Step 2 会通过标题相似度查找相关 GitHub issue。此工具集帮助分析匹配质量，找出标题差异过大的案例。

## 问题背景

在 `fl.py` 第 1273-1327 行的逻辑中存在几个问题：

1. ❌ **时间泄漏**: `end_time = self.created_at + 8 * 60 * 60` 搜索了未来 8 小时的 issues
2. ❌ **无相似度阈值**: 即使相似度很低也会建立关联
3. ⚠️ **标题提取脆弱**: 直接取第一行可能不准确
4. ⚠️ **相似度算法简单**: 移除所有空格可能导致误匹配

## 使用方法

### 方法 1：边运行边分析（推荐）

使用提供的包装脚本，自动记录日志并分析：

```bash
./run_with_analysis.sh <instance_id> <repo_path> <output_dir> [benchmark]
```

**示例：**

```bash
# Python 项目
./run_with_analysis.sh django__django-10097 django output_dir

# Java 项目
./run_with_analysis.sh apache__dubbo-10638 dubbo java_output multi-swe-bench
```

**输出：**
- KG 结果文件
- 运行日志
- `parsed_issue_matches.json` - 匹配分析结果

### 方法 2：分析已有日志

如果你已经有运行日志，可以直接解析：

```bash
python parse_fl_logs.py your_run.log
```

### 方法 3：批量分析多个实例

创建批处理脚本：

```bash
#!/bin/bash
# batch_analyze.sh

INSTANCES=(
    "django__django-10097"
    "django__django-10554"
    "django__django-10880"
    # ... 更多实例
)

for instance in "${INSTANCES[@]}"; do
    echo "处理 $instance..."
    ./run_with_analysis.sh "$instance" django output_dir
done

# 汇总所有结果
python -c "
import json
import glob

all_matches = []
for f in glob.glob('parsed_issue_matches_*.json'):
    with open(f) as fp:
        all_matches.extend(json.load(fp))

low_sim = [m for m in all_matches if m['similarity'] < 0.5]
print(f'总计: {len(all_matches)} 个匹配')
print(f'低相似度: {len(low_sim)} 个 ({len(low_sim)/len(all_matches)*100:.1f}%)')
"
```

## 输出示例

```
解析日志文件: logs/django__django-10097_20241111_143022.log

找到 15 个 issue 匹配记录

低相似度匹配（< 0.5）：3 个

====================================================================================================

1. django__django-10097
   预期标题: Add a PostgreSQL table comment to a table
   匹配 Issue: #9823
   匹配标题: Allow customizing ValidationError's error_list class
   相似度: 0.234

2. django__django-10554
   预期标题: Password changed successfully page does not pass context to the template
   匹配 Issue: #10432
   匹配标题: Template context processors should support kwargs
   相似度: 0.378

3. django__django-10880
   预期标题: FilePathField doesn't allow callable as a path parameter
   匹配 Issue: #10845
   匹配标题: Add path parameter to FieldFile
   相似度: 0.456

统计信息:
  总匹配数: 15
  低相似度 (< 0.5): 3
  平均相似度: 0.672
  最低相似度: 0.234
  最高相似度: 0.954
```

## 分析低相似度案例

找到低相似度案例后，可以：

1. **检查标题提取**: 确认 problem_statement 第一行是否为真正的标题
2. **检查时间窗口**: 相关 issue 可能在搜索时间范围之外
3. **手动验证**: 查看实际的 GitHub issue 确认是否真的相关
4. **调整阈值**: 根据实际情况调整相似度阈值（当前建议 0.5）

## 改进建议

基于分析结果，可以考虑以下改进（已在之前的对话中修复）：

### ✅ 已修复的问题

1. **时间泄漏**: 
   - 原: `end_time = self.created_at + 8 * 60 * 60`
   - 改为: `end_time = self.created_at`

2. **搜索窗口**: 
   - 原: 7 天
   - 改为: 30 天

3. **相似度阈值**:
   - 添加 `SIMILARITY_THRESHOLD = 0.5`
   - 低于阈值时跳过并记录

4. **标题提取**:
   - 优先使用 `target_sample.get('title')`
   - 智能跳过空行和 markdown 标记

5. **相似度计算**:
   - 改用 `' '.join(text.lower().split())` 保留单词边界

### ⚠️ 用户已还原修复

注意：用户在最新的代码中已经将之前的修复还原了。当前代码仍存在以下问题：

1. ❌ 时间泄漏依然存在（Line 1273）
2. ❌ 无相似度阈值（Line 1323）
3. ❌ 标题提取仍使用简单的第一行（Line 1239）
4. ❌ 相似度计算移除所有空格（Line 1282, 1312）

### 建议重新应用修复

如果要解决这些问题，建议重新应用之前的修复，或者根据分析结果手动调整。

## 相似度阈值参考

| 阈值 | 含义 | 适用场景 |
|------|------|----------|
| 0.9+ | 几乎完全匹配 | 严格模式，仅接受高度相关 |
| 0.7-0.9 | 高度相似 | 推荐模式，平衡准确率 |
| 0.5-0.7 | 中等相似 | 当前阈值，允许一定差异 |
| 0.3-0.5 | 低相似度 | 宽松模式，可能需要人工审核 |
| < 0.3 | 几乎不相关 | 建议拒绝匹配 |

## 常见低相似度原因

1. **标题格式差异**
   - 预期: "Add support for PostgreSQL table comments"
   - 匹配: "Table comments for Postgres"
   - 原因: 词序不同，但语义相近

2. **描述方式不同**
   - 预期: "Fix bug in password change success page"
   - 匹配: "Password changed successfully doesn't render correctly"
   - 原因: 主动/被动语态，同义词替换

3. **标题提取错误**
   - 预期: "# Title" 或空行
   - 实际: 应该使用下一行
   - 原因: Markdown 格式或空行干扰

4. **算法限制**
   - 移除空格: "user login" → "userlogin" = "use rlog in" → "userlogin"
   - LCS 对词序敏感度不够

## 后续步骤

1. 运行分析工具收集数据
2. 查看 `parsed_issue_matches.json` 找出低相似度案例
3. 手动验证这些案例
4. 根据需要调整阈值或算法
5. 重新运行并评估效果

## 工具文件清单

- `run_with_analysis.sh` - 运行包装脚本（边跑边记录）
- `parse_fl_logs.py` - 日志解析脚本
- `simulate_issue_matching.py` - 模拟匹配脚本（需要 GitHub API）
- `ANALYSIS_GUIDE.md` - 详细分析指南
- 此文件 - 使用说明

---

**注意**: 由于用户已明确表示"不要改已有代码"，本工具集仅用于分析，不会修改 `fl.py`。如需修复问题，请参考之前对话中的修复方案。


