# KGCompass 配置说明

## 环境变量配置

在项目根目录创建 `.env` 文件，并设置以下环境变量：

```bash
# GitHub Token (用于访问 GitHub API)
GITHUB_TOKEN=your_github_token_here

# Bailian API Key (阿里云百炼大模型)
BAILIAN_API_KEY=your_bailian_api_key_here

# Claude API Key (Anthropic Claude)
CLAUDE_API_KEY=your_claude_api_key_here

# OpenAI API Key (GPT 模型)
OPENAI_API_KEY=your_openai_api_key_here

# DeepSeek API Key
DEEPSEEK_API_KEY=your_deepseek_api_key_here

# Qwen API Key
QWEN_API_KEY=your_qwen_api_key_here

# Neo4j Configuration
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Proxy Settings (如果需要)
# http_proxy=http://172.27.16.1:7890
# https_proxy=http://172.27.16.1:7890
# no_proxy=localhost,127.0.0.1

# Debug Settings
DEBUG=0
FLASK_DEBUG=0
```

## API 密钥获取

### GitHub Token
1. 访问 https://github.com/settings/tokens
2. 点击 "Generate new token"
3. 选择适当的权限（repo, read:org）
4. 复制生成的 token

### Anthropic Claude
1. 访问 https://console.anthropic.com/
2. 创建账户并获取 API 密钥
3. 复制 API 密钥

### OpenAI
1. 访问 https://platform.openai.com/api-keys
2. 创建新的 API 密钥
3. 复制 API 密钥

### DeepSeek
1. 访问 https://platform.deepseek.com/
2. 注册账户并获取 API 密钥

### 阿里云百炼
1. 访问阿里云百炼控制台
2. 创建应用并获取 API 密钥

## Docker 配置

如果使用 Docker 模式，确保：

1. 安装 Docker 和 Docker Compose
2. 如果需要 GPU 支持，安装 NVIDIA Container Toolkit
3. 配置好 `.env` 文件
4. 运行 `./start_web_docker.sh`

## 网络配置

如果在受限网络环境中使用，可能需要配置代理：

```bash
export http_proxy=http://your_proxy:port
export https_proxy=http://your_proxy:port
export no_proxy=localhost,127.0.0.1
```

## 故障排除

### Docker 相关
- 确保 Docker 服务正在运行
- 检查 docker-compose.yml 文件是否存在
- 查看容器日志：`docker-compose logs -f`

### API 相关
- 确保 API 密钥正确且有效
- 检查网络连接和代理设置
- 验证 API 配额和限制

### Neo4j 相关
- 确保 Neo4j 容器正在运行
- 检查连接字符串和认证信息
- 查看 Neo4j 日志排查问题 