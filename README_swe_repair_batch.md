# SWE-bench Verified 批量修复脚本使用指南

本脚本支持使用多种 LLM API（Claude、OpenAI、DeepSeek、Qwen）对 SWE-bench Verified 数据集进行批量修复，特别支持只处理在 Verified 中但不在 Lite 中的实例。

## 前置要求

1. **安装依赖**：
   ```bash
   pip install datasets anthropic openai tiktoken
   ```

2. **设置 API Keys**：
   ```bash
   export CLAUDE_API_KEY="your-claude-api-key"
   export OPENAI_API_KEY="your-openai-api-key"
   export DEEPSEEK_API_KEY="your-deepseek-api-key"
   export QWEN_API_KEY="your-qwen-api-key"
   ```

3. **准备 KG 文件**：
   确保已运行 KG 生成流程，KG 文件保存在 `runs/kg_verified` 目录中。

## 基本使用流程

### 步骤 1：生成 Verified-only 实例列表

首先生成只在 SWE-bench Verified 中但不在 SWE-bench Lite 中的实例列表：

```bash
python prepare_verified_only_jsonl.py
```

这将生成 `SWE-bench_Verified_only_ids.jsonl` 文件，包含所有 verified-only 实例。

### 步骤 2：批量修复

使用不同的 API 和配置进行批量修复：

```bash
# 使用 Claude API 处理所有 verified-only 实例
python swe_repair_batch.py --verified-only --api_type anthropic

# 使用 OpenAI API 处理前 10 个 verified-only 实例
python swe_repair_batch.py --verified-only --api_type openai --limit 10

# 使用 DeepSeek API 并行处理（4 个线程）
python swe_repair_batch.py --verified-only --api_type deepseek --workers 4

# 自定义温度参数
python swe_repair_batch.py --verified-only --api_type anthropic --temperature 0.5
```

## 命令行参数

| 参数 | 描述 | 默认值 |
|------|------|--------|
| `--kg_dir` | KG 结果目录 | `runs/kg_verified` |
| `--api_type` | API 类型 (anthropic/openai/deepseek/qwen) | `anthropic` |
| `--temperature` | LLM 生成温度 | `0.3` |
| `--workers` | 并行工作数 | `2` |
| `--verified-only` | 只处理 verified-only 实例 | `False` |
| `--verified-only-file` | verified-only 实例文件路径 | `SWE-bench_Verified_only_ids.jsonl` |
| `--instance_id` | 处理特定实例 | - |
| `--limit` | 限制处理数量 | - |
| `--start` | 开始索引 | `0` |

## 使用示例

### 1. 处理所有 verified-only 实例

```bash
# 使用 Claude（推荐）
python swe_repair_batch.py --verified-only --api_type anthropic

# 使用 OpenAI GPT-4
python swe_repair_batch.py --verified-only --api_type openai
```

### 2. 分批处理

```bash
# 处理前 20 个实例
python swe_repair_batch.py --verified-only --limit 20

# 从第 20 个开始处理接下来的 20 个
python swe_repair_batch.py --verified-only --start 20 --limit 20
```

### 3. 并行处理

```bash
# 使用 8 个并行线程
python swe_repair_batch.py --verified-only --workers 8 --api_type anthropic
```

### 4. 处理单个实例

```bash
python swe_repair_batch.py --instance_id django__django-12345 --api_type anthropic
```

### 5. 自定义文件路径

```bash
python swe_repair_batch.py \
  --verified-only \
  --verified-only-file custom_instances.jsonl \
  --kg_dir custom_kg_dir \
  --api_type anthropic
```

## 输出结构

处理完成后，每个实例会在 `tests/` 目录下生成以下结构：

```
tests/
└── {instance_id}_{api_type}/
    ├── kg_locations/          # 复制的 KG 文件
    ├── llm_locations/         # LLM 位置预测
    ├── final_locations/       # 合并后的位置
    └── patches/              # 生成的修复补丁
```

## 监控和调试

1. **查看进度**：脚本会实时显示处理进度和结果统计
2. **错误处理**：失败的实例会被记录，可以单独重新处理
3. **日志输出**：每个步骤都有详细的状态输出

## 注意事项

1. **API 限制**：注意各 API 的调用频率限制
2. **磁盘空间**：确保有足够空间存储生成的文件
3. **网络连接**：需要稳定的网络连接访问 API
4. **中断恢复**：脚本支持增量处理，重新运行会跳过已完成的实例

## 故障排除

### 常见问题

1. **API Key 错误**：
   ```bash
   export CLAUDE_API_KEY="your-actual-key"
   ```

2. **KG 文件不存在**：
   ```bash
   # 确保先运行 KG 生成
   python kgcompass/fl.py instance_id repo_name kg_output_dir
   ```

3. **内存不足**：
   ```bash
   # 减少并行数
   python swe_repair_batch.py --verified-only --workers 1
   ```

### 测试脚本

运行测试确保所有功能正常：

```bash
python test_swe_repair_batch.py
```

## 性能建议

1. **API 选择**：Claude 通常质量最高，DeepSeek 成本最低
2. **并行数量**：根据 API 限制和机器性能调整 `--workers`
3. **分批处理**：对于大量实例，建议分批处理避免长时间运行
4. **温度设置**：较低的温度（0.1-0.3）通常更适合代码修复任务 