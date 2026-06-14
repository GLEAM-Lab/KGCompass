# 🚀 立即测试 SWE-bench Issue #449

## 最快开始方式（2 分钟）

### 选项 1：Web 界面（最简单）⭐

```bash
# 1. 启动服务
python app.py
```

然后在浏览器中：
1. 访问：http://localhost:5000
2. 点击 **"自定义 GitHub 仓库"** 选项卡
3. 填写：
   - **仓库 URL：** `SWE-bench/SWE-bench`
   - **Issue 编号：** `449`
4. 点击 **"验证仓库和 Issue"**
5. 点击 **"开始修复"**
6. 等待完成，查看补丁！

### 选项 2：命令行（最快）⚡

```bash
# 一键运行
./test_swebench_issue_449.sh
```

## 📋 Issue 简介

**问题：** `report_dir` CLI 参数不工作  
**原因：** 参数没有传递给 `make_run_report` 函数  
**需要修复：** 在 `reporting.py` 中添加 `report_dir` 参数

## 🎯 预期修复

补丁应该修改 `swebench/harness/reporting.py`：

```python
# 修改前
def make_run_report(traj_data, ...):
    ...

# 修改后  
def make_run_report(traj_data, report_dir=None, ...):
    if report_dir:
        # 使用指定的目录
        ...
```

## 📊 查看结果

### Web 界面
- 实时查看日志
- 下载补丁文件
- 查看补丁预览

### 命令行
```bash
# 查看生成的补丁
find tests/ -name "*SWE-bench*449*.diff" -exec cat {} \;

# 或
ls -la tests/SWE-bench__SWE-bench-449_deepseek/patches/
```

## ✅ 成功标志

如果看到：
- ✅ 补丁文件生成成功
- ✅ 修改了 `reporting.py` 文件
- ✅ 添加了 `report_dir` 参数
- ✅ 正确使用了该参数

**恭喜！修复成功！** 🎉

## 🔧 故障排查

### Docker 未启动？
```bash
docker-compose up -d
docker-compose ps  # 检查状态
```

### 网络问题？
```bash
# 测试 GitHub API 访问
curl https://api.github.com/repos/SWE-bench/SWE-bench/issues/449
```

### 详细日志？
```bash
docker-compose logs -f app
```

## 📚 更多信息

- 完整测试指南：[TEST_SWEBENCH_ISSUE_449.md](TEST_SWEBENCH_ISSUE_449.md)
- Issue 链接：https://github.com/SWE-bench/SWE-bench/issues/449
- 自定义仓库文档：[CUSTOM_REPO_GUIDE.md](CUSTOM_REPO_GUIDE.md)

---

**现在就开始测试吧！** 🚀






