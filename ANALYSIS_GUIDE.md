# Issue 匹配分析指南

## 问题描述

当前的 `fl.py` 在 Step 2 中会查找与 problem_statement 标题最相似的 GitHub issue，但结果 JSON 文件中没有保存找到的 issue 信息，导致无法事后分析匹配质量。

## 建议的改进方案

### 方案 1：在结果中保存 issue 匹配信息（推荐）

修改 `fl.py` 的 `analyze()` 方法，在返回结果中添加 issue 匹配信息：

```python
# 在 analyze() 方法的返回值中添加
return {
    'related_entities': related_entities,
    'artifact_stats': self.artifact_stats,
    'matched_issue_info': {  # 新增字段
        'best_match_issue_number': best_match_issue.number if best_match_issue else None,
        'best_match_issue_title': best_match_issue.title if best_match_issue else None,
        'similarity_score': max_similarity,
        'expected_title': title,  # problem_statement 的第一行
    }
}
```

具体修改位置：

1. 在 `_process_repository()` 方法中，将 `best_match_issue` 和相关信息保存为实例变量：

```python
# 在 Step 2 找到 best_match_issue 后
self.best_match_issue_info = {
    'number': best_match_issue.number if best_match_issue else None,
    'title': best_match_issue.title if best_match_issue else None,
    'similarity': max_similarity,
    'expected_title': title
}
```

2. 在 `analyze()` 方法返回时包含这些信息：

```python
return {
    'related_entities': related_entities,
    'artifact_stats': self.artifact_stats,
    'matched_issue_info': getattr(self, 'best_match_issue_info', None),
}
```

### 方案 2：使用现有脚本分析（需要 GitHub API）

运行 `simulate_issue_matching.py` 脚本来重新模拟匹配过程：

```bash
python simulate_issue_matching.py
```

**注意**：此方案会调用 GitHub API，可能受到 rate limit 限制。

## 分析步骤

### 如果采用方案 1：

1. 修改 `fl.py` 添加 issue 匹配信息保存
2. 重新运行 fl.py 生成新的结果文件
3. 运行分析脚本：

```python
#!/usr/bin/env python3
import json
from pathlib import Path

results_dir = Path("runs/kg_verified")
low_similarity_cases = []
THRESHOLD = 0.5

for repo_dir in results_dir.iterdir():
    if not repo_dir.is_dir():
        continue
    for json_file in repo_dir.glob("*.json"):
        with open(json_file) as f:
            data = json.load(f)
        
        matched_info = data.get('matched_issue_info')
        if matched_info and matched_info.get('similarity', 1.0) < THRESHOLD:
            low_similarity_cases.append({
                'instance_id': json_file.stem,
                'repo': repo_dir.name,
                'expected_title': matched_info['expected_title'],
                'matched_issue': matched_info['number'],
                'matched_title': matched_info['title'],
                'similarity': matched_info['similarity']
            })

# 按相似度排序
low_similarity_cases.sort(key=lambda x: x['similarity'])

print(f"发现 {len(low_similarity_cases)} 个低相似度匹配案例:\n")
for i, case in enumerate(low_similarity_cases, 1):
    print(f"{i}. {case['instance_id']}")
    print(f"   预期: {case['expected_title'][:80]}")
    print(f"   匹配: #{case['matched_issue']} - {case['matched_title'][:80]}")
    print(f"   相似度: {case['similarity']:.3f}\n")
```

### 如果采用方案 2：

直接运行 `simulate_issue_matching.py`（受 API 限制）。

## 相似度阈值建议

- **0.5**: 保守阈值，低于此值的匹配可能不够准确
- **0.3**: 宽松阈值，用于发现更多潜在问题
- **0.7**: 严格阈值，只接受高质量匹配

## 常见低相似度原因

1. **标题提取错误**: problem_statement 第一行不是真正的标题
2. **标题格式差异**: 使用了不同的描述方式（如主动/被动语态）
3. **时间窗口问题**: 相关 issue 在时间窗口之外
4. **相似度计算方法**: 移除空格的方法可能导致误判

## 改进建议

1. 改进标题提取逻辑（优先使用 dataset 中的 title 字段）
2. 改进相似度计算（保留单词边界）
3. 添加相似度阈值检查
4. 扩大时间搜索窗口
5. 修复时间泄漏问题（end_time 不应该超过 created_at）


