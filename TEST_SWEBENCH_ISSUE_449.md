# 测试 SWE-bench Issue #449

## 📋 Issue 信息

**仓库：** [SWE-bench/SWE-bench](https://github.com/SWE-bench/SWE-bench)  
**Issue：** [#449 - report_dir CLI argument not working as expected](https://github.com/SWE-bench/SWE-bench/issues/449)  
**语言：** Python  
**类型：** Bug Fix

## 🐛 问题描述

`report_dir` CLI 参数在 SWE-bench 中不工作。虽然 CLI 接受这个参数，但它没有被传递给 `make_run_report` 函数，导致报告总是保存到默认位置。

### 问题细节

**根本原因：**
1. `report_dir` 在 `run_evaluation.py#L471-L475` 中被使用
2. 但 `make_run_report` 函数（`reporting.py#L17`）的签名中缺少 `report_dir` 参数
3. 结果：报告被保存到默认位置，忽略用户指定的目录

**受影响的命令示例：**
```bash
python -m swebench.harness.run_evaluation \
    --predictions_path gold \
    --max_workers 1 \
    --report_dir reports \
    --instance_ids sympy__sympy-20590 \
    --run_id validate-gold
```

## 🚀 测试方法

### 方法 1：使用 Web 界面（推荐）⭐

1. **启动 Web 服务**
   ```bash
   python app.py
   ```

2. **打开浏览器**
   - 访问：http://localhost:5000

3. **填写信息**
   - 点击 **"自定义 GitHub 仓库"** 选项卡
   - **GitHub 仓库 URL：** `SWE-bench/SWE-bench` 或 `https://github.com/SWE-bench/SWE-bench`
   - **Issue 编号：** `449`

4. **验证仓库**
   - 点击 "验证仓库和 Issue" 按钮
   - 应该显示：
     - ✅ 仓库验证成功: SWE-bench/SWE-bench
     - ✅ Issue #449 验证成功: report_dir CLI argument not working as expected

5. **开始修复**
   - 点击 "开始修复" 按钮
   - 实时查看修复进度和日志

6. **查看结果**
   - 等待修复完成
   - 下载或查看生成的补丁文件

### 方法 2：使用命令行脚本

```bash
# 运行专门的测试脚本
./test_swebench_issue_449.sh
```

### 方法 3：使用 Docker 命令

```bash
# 直接在 Docker 容器中执行
docker-compose exec app bash run_repair_custom.sh \
    "SWE-bench__SWE-bench-449" \
    "https://github.com/SWE-bench/SWE-bench.git" \
    "SWE-bench__SWE-bench" \
    "449"
```

## 🎯 预期结果

### 修复流程应该生成：

1. **知识图谱分析** (`kg_locations/`)
   - 分析 SWE-bench 代码结构
   - 识别 `run_evaluation.py` 和 `reporting.py` 的关系

2. **LLM 故障定位** (`llm_locations/`)
   - 基于 Issue 描述定位问题代码
   - 应该定位到 `reporting.py` 中的 `make_run_report` 函数

3. **融合定位结果** (`final_locations/`)
   - 合并 KG 和 LLM 的分析结果
   - 精确定位需要修改的位置

4. **修复补丁** (`patches/`)
   - 生成修复 `report_dir` 参数传递问题的补丁
   - 可能的修复内容：
     ```python
     # 在 reporting.py 的 make_run_report 函数签名中添加 report_dir 参数
     def make_run_report(
         traj_data,
         report_dir=None,  # 新增参数
         ...
     ):
     ```

## 📊 修复验证

### 补丁应该包含的修改：

1. **修改 `reporting.py`：**
   - 在 `make_run_report` 函数中添加 `report_dir` 参数
   - 使用 `report_dir` 参数来指定报告保存位置

2. **可能修改 `run_evaluation.py`：**
   - 确保 `report_dir` 参数被正确传递给 `make_run_report`

### 预期的补丁格式：

```diff
--- a/swebench/harness/reporting.py
+++ b/swebench/harness/reporting.py
@@ -14,7 +14,7 @@ from swebench.metrics.metrics import ...
 
-def make_run_report(traj_data, ...):
+def make_run_report(traj_data, report_dir=None, ...):
     """Generate evaluation report"""
+    if report_dir:
+        output_dir = report_dir
+    else:
+        output_dir = DEFAULT_REPORT_DIR
     ...
```

## 🧪 测试步骤详解

### 1. 仓库克隆
```bash
# KGCompass 会自动克隆仓库到 playground/SWE-bench__SWE-bench/
ls -la playground/SWE-bench__SWE-bench/
```

### 2. 查看分析结果
```bash
# 查看 KG 分析结果
cat tests/SWE-bench__SWE-bench-449_deepseek/kg_locations/SWE-bench__SWE-bench-449.json

# 查看 LLM 定位结果
cat tests/SWE-bench__SWE-bench-449_deepseek/llm_locations/SWE-bench__SWE-bench-449.json

# 查看最终定位结果
cat tests/SWE-bench__SWE-bench-449_deepseek/final_locations/SWE-bench__SWE-bench-449.json
```

### 3. 查看生成的补丁
```bash
# 查看补丁内容
cat tests/SWE-bench__SWE-bench-449_deepseek/patches/*.diff

# 或从 Web 界面下载
# web_outputs/[task_id]/SWE-bench__SWE-bench-449_patch.diff
```

### 4. 验证补丁
```bash
# 应用补丁到克隆的仓库
cd playground/SWE-bench__SWE-bench/
git apply ../../tests/SWE-bench__SWE-bench-449_deepseek/patches/*.diff

# 检查修改
git diff

# 运行测试验证修复
python -m pytest tests/
```

## 📈 成功标准

✅ **修复成功的标志：**

1. **补丁生成成功**
   - 生成了 `.diff` 文件
   - 补丁内容合理，针对问题核心

2. **定位准确**
   - 正确识别 `reporting.py` 文件
   - 准确定位到 `make_run_report` 函数

3. **修复合理**
   - 在函数签名中添加 `report_dir` 参数
   - 在函数体中正确使用该参数
   - 保持向后兼容（默认值）

4. **代码质量**
   - 补丁格式正确
   - 代码风格一致
   - 没有引入新的 Bug

## 🔍 深度分析

### 问题根源分析

1. **调用链：**
   ```
   run_evaluation.py (CLI入口)
       ↓ 接收 --report_dir 参数
       ↓
   run_evaluation.py#L471-L475
       ↓ 应该传递 report_dir
       ↓
   reporting.py#make_run_report()
       ✗ 但函数签名中没有这个参数！
   ```

2. **为什么会出现这个问题？**
   - 可能是重构时遗漏
   - 或者是功能新增但接口没有同步更新

3. **修复需要考虑的点：**
   - 向后兼容性（可能有其他地方调用这个函数）
   - 默认行为（如果不提供 report_dir 怎么办）
   - 路径处理（确保目录存在、权限等）

## 🎓 学习价值

这个 Issue 很好地展示了：

1. **参数传递问题** - 经典的软件工程问题
2. **接口不匹配** - CLI 和内部函数的契约问题
3. **向后兼容** - 如何在修复 Bug 时保持兼容性

## 🐛 可能遇到的问题

### 问题 1：仓库太大，克隆时间长

**解决方案：**
- 耐心等待，或者使用浅克隆（shallow clone）
- SWE-bench 仓库大小约 50MB，应该很快

### 问题 2：LLM 定位不准确

**解决方案：**
- 检查 Issue 描述是否完整
- 查看中间结果文件，了解定位过程
- 可能需要调整 LLM 提示词

### 问题 3：补丁格式不正确

**解决方案：**
- 检查生成的补丁文件格式
- 确保路径正确
- 必要时手动调整

## 📞 需要帮助？

- 查看实时日志（Web 界面或 Docker logs）
- 检查 `web_outputs/` 目录中的任务输出
- 运行 `docker-compose logs app` 查看详细日志

## 🎉 完成后

如果修复成功：

1. 📋 记录补丁内容和修复思路
2. 🧪 验证补丁是否真正解决问题
3. 📊 分析 KGCompass 的定位准确性
4. 💡 思考如何改进修复流程

---

**祝测试顺利！** 🚀

这是一个很好的真实案例来验证 KGCompass 的自定义仓库修复能力！






