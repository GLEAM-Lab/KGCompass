# 🔄 重新测试 - 关键问题已修复

## ✅ 已修复的关键问题

### 1. 数据泄露问题 ⚠️
- **修复前**: 使用 HEAD commit（可能包含修复后的代码）
- **修复后**: 使用 Issue 创建时刻的 commit

### 2. 方法匹配问题 🔧  
- **修复前**: 完整限定名无法匹配（`src.pip._internal.vcs.git.Git.has_commit` vs `has_commit`）
- **修复后**: 支持多种名称格式的灵活匹配

### 3. 实例加载问题
- **修复前**: 只从 SWE-bench 数据集加载
- **修复后**: 支持从 GitHub API 直接获取

---

## 🚀 立即重新测试

### 清理之前的结果（可选）

```bash
# 删除旧的测试结果，强制重新分析
rm -rf tests/SWE-bench__SWE-bench-449_deepseek/
rm -rf tests/pypa__pip-13491_deepseek/
```

### 方法 1: 测试 SWE-bench Issue #449

```bash
docker-compose exec app bash run_repair_custom.sh \
    "SWE-bench__SWE-bench-449" \
    "https://github.com/SWE-bench/SWE-bench.git" \
    "SWE-bench__SWE-bench" \
    "449"
```

### 方法 2: 使用测试脚本

```bash
./test_swebench_issue_449.sh
```

### 方法 3: 使用 Web 界面

```bash
python app.py
# 访问 http://localhost:5000
# 选择"自定义 GitHub 仓库"
# 输入: SWE-bench/SWE-bench, Issue: 449
```

---

## 📊 预期改进

### Step 1: KG 分析
```
✅ 获取 Issue #449 from GitHub
✅ Issue created at: 2025-08-07 XX:XX:XX
✅ Finding commit at Issue creation time...
✅ Found base_commit: [某个 8 月的 commit]
✅ Switching to commit: [该 commit]
✅ 分析该版本的代码
✅ 找到 50 个相关方法
```

### Step 2: LLM 定位
```
✅ Loading target sample from instance file
✅ LLM 推荐 10 个最相关的位置
✅ 所有推荐都基于 8 月的代码版本
```

### Step 3: 版本统一
```
✅ Using base_commit: [8 月的 commit]
✅ Found file swebench/harness/reporting.py in commit
✅ Found entity make_run_report ← 改进的匹配逻辑
✅ Found entity run_evaluation ← 灵活匹配
✅ 保留了 40/50 个方法 ← 大幅提升！
```

### Step 4: 生成补丁
```
✅ 基于正确的代码版本
✅ 提供了充足的上下文（40个方法的源代码）
✅ LLM 能看到完整的相关代码
✅ 生成合理的修复补丁
```

---

## 🔍 验证要点

### 检查 1: Commit 版本
```bash
# 查看使用的 base_commit
cat tests/SWE-bench__SWE-bench-449_deepseek/kg_locations/*.json | grep base_commit
cat web_outputs/*/SWE-bench__SWE-bench-449_instance.json | grep base_commit

# 应该看到: 一个 8 月初的 commit，而不是 10 月的
```

### 检查 2: 方法匹配率
```bash
# 查看 fix_fl_line 的输出
grep -E "(Found entity|keeping it|Not found)" \
    tests/SWE-bench__SWE-bench-449_deepseek/*.log | tail -20

# 应该看到更多 "Found entity" 而不是 "Not found"
```

### 检查 3: 最终结果
```bash
# 查看最终保留的方法数量
python3 -c "
import json
with open('tests/SWE-bench__SWE-bench-449_deepseek/final_locations/SWE-bench__SWE-bench-449.json') as f:
    data = json.load(f)
print('Final methods count:', len(data['related_entities'].get('methods', [])))
"

# 应该 > 30 个方法
```

### 检查 4: 补丁质量
```bash
# 查看生成的补丁
cat tests/SWE-bench__SWE-bench-449_deepseek/patches/*.diff

# 应该包含对 reporting.py 的修改
# 应该添加 report_dir 参数
```

---

## 📈 成功标准

| 指标 | 目标 | 说明 |
|------|------|------|
| Commit 版本 | Issue 创建时刻 | 防止数据泄露 |
| 方法匹配率 | > 70% | 之前只有 0% |
| 最终方法数 | > 30 个 | 提供充足上下文 |
| 补丁生成 | 成功 | 包含合理的修复 |

---

## 🐛 如果还有问题

### 问题 1: 方法匹配率仍然低

**可能原因：**
- `get_class_and_method_from_content` 返回的名称格式不同
- 需要进一步调试匹配逻辑

**调试方法：**
```bash
# 添加调试输出
# 在 fix_fl_line.py 中打印 method['name'] 和 entity['name']
```

### 问题 2: 无法获取历史 commit

**可能原因：**
- GitHub API 限制
- 网络问题

**解决方案：**
```bash
# 设置 GitHub Token
export GITHUB_TOKEN="your_token"
```

### 问题 3: LLM 仍然说没有代码

**检查：**
```bash
# 查看 final_locations 中有多少方法有 source_code
python3 -c "
import json
with open('tests/SWE-bench__SWE-bench-449_deepseek/final_locations/SWE-bench__SWE-bench-449.json') as f:
    data = json.load(f)
methods_with_code = [m for m in data['related_entities'].get('methods', []) if m.get('source_code')]
print(f'{len(methods_with_code)}/{len(data[\"related_entities\"].get(\"methods\", []))} methods have source_code')
"
```

---

## 🎉 期待结果

修复后，你应该看到：

1. ✅ **正确的 commit 版本** - Issue 创建时刻的代码
2. ✅ **高方法匹配率** - 大部分方法都能找到
3. ✅ **丰富的上下文** - 30+ 个方法的完整代码
4. ✅ **合理的补丁** - LLM 能生成有意义的修复

**现在重新运行测试，看看效果如何！** 🚀

---

**提示**: 如果看到 "Entity X already has source_code from KG, keeping it"，说明匹配成功了！






