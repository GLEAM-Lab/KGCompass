# Git SSH 设置脚本集

这个脚本集用于批量克隆 SWE-bench 相关仓库并设置为 SSH 连接。

## 📋 脚本列表

### 1. `clone_and_setup_ssh.sh` - 克隆并设置 SSH
**功能**: 克隆所有 SWE-bench 相关仓库到当前目录，并设置为 SSH 连接

**使用方法**:
```bash
bash clone_and_setup_ssh.sh
```

**包含的仓库**:
- astropy/astropy
- django/django  
- matplotlib/matplotlib
- mwaskom/seaborn
- psf/requests
- pallets/flask
- pydata/xarray
- pylint-dev/pylint
- pytest-dev/pytest
- scikit-learn/scikit-learn
- sphinx-doc/sphinx
- sympy/sympy

### 2. `convert_to_ssh.sh` - 转换现有仓库为 SSH
**功能**: 将当前目录下的所有 HTTPS Git 仓库转换为 SSH 连接

**使用方法**:
```bash
# 转换当前目录下的仓库
bash convert_to_ssh.sh

# 转换指定目录下的仓库
bash convert_to_ssh.sh /path/to/repos
```

### 3. `check_ssh_setup.sh` - 检查 SSH 设置
**功能**: 全面检查 SSH 密钥、代理、GitHub 连接状态和现有仓库设置

**使用方法**:
```bash
bash check_ssh_setup.sh
```

**检查内容**:
- SSH 密钥是否存在
- SSH 代理是否运行
- GitHub 连接是否正常
- 显示公钥内容
- 检查现有仓库的 remote 设置
- 提供设置指南

## 🚀 快速开始

### 第一次设置（推荐流程）

1. **检查 SSH 环境**:
   ```bash
   bash check_ssh_setup.sh
   ```

2. **如果没有 SSH 密钥，生成一个**:
   ```bash
   ssh-keygen -t ed25519 -C "your_email@example.com"
   eval "$(ssh-agent -s)"
   ssh-add ~/.ssh/id_ed25519
   ```

3. **添加公钥到 GitHub**:
   ```bash
   cat ~/.ssh/id_ed25519.pub
   # 复制输出内容到 https://github.com/settings/keys
   ```

4. **测试连接**:
   ```bash
   ssh -T git@github.com
   ```

5. **克隆所有仓库**:
   ```bash
   bash clone_and_setup_ssh.sh
   ```

### 已有 HTTPS 仓库的转换

如果你已经有通过 HTTPS 克隆的仓库：

1. **检查当前状态**:
   ```bash
   bash check_ssh_setup.sh
   ```

2. **批量转换为 SSH**:
   ```bash
   bash convert_to_ssh.sh
   ```

## 📊 脚本特性

### 容错处理
- ✅ 支持增量操作（跳过已存在/已配置的仓库）
- ✅ 详细的错误提示和解决建议
- ✅ 完整的统计报告

### 智能检测
- ✅ 自动检测 SSH 密钥类型（Ed25519/RSA）
- ✅ 识别现有 remote 类型（SSH/HTTPS）
- ✅ 验证 GitHub 连接状态

### 友好输出
- ✅ 彩色图标和进度显示
- ✅ 清晰的步骤说明
- ✅ 实用的命令提示

## 🔧 故障排除

### SSH 连接失败
```bash
# 检查 SSH 代理
ssh-add -l

# 重新启动 SSH 代理
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519

# 测试连接
ssh -T git@github.com
```

### 权限问题
```bash
# 确保密钥文件权限正确
chmod 600 ~/.ssh/id_ed25519
chmod 644 ~/.ssh/id_ed25519.pub
```

### 网络问题
```bash
# 测试基本网络连接
ping github.com

# 测试 SSH 端口
ssh -T -p 22 git@github.com
```

## 📝 注意事项

1. **前置要求**: 确保已安装 `git`, `jq`, `ssh`
2. **权限**: 需要对仓库目录有写权限
3. **网络**: 需要稳定的网络连接
4. **GitHub**: 需要有效的 GitHub 账户和 SSH 密钥

## 🎯 使用场景

- 🆕 **新环境设置**: 在新机器上快速设置所有 SWE-bench 仓库
- 🔄 **协议转换**: 将现有 HTTPS 仓库批量转换为 SSH
- 🔍 **环境检查**: 验证 SSH 配置是否正确
- 🛠️ **故障诊断**: 快速定位 SSH 连接问题

## 📞 获取帮助

运行任何脚本都会显示详细的状态信息和错误提示。如果遇到问题：

1. 首先运行 `bash check_ssh_setup.sh` 进行全面检查
2. 按照输出的建议进行修复
3. 参考上面的故障排除部分

---

**Happy Coding! 🚀** 