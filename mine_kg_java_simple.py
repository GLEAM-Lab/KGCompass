#!/usr/bin/env python3
"""
简单的 Java KG 挖掘脚本，直接从 swe-bench_java 目录读取 JSONL 文件
"""

import argparse
import json
import subprocess
import os
from pathlib import Path
import glob

# Java 仓库 URL 映射
JAVA_REPO_URL_MAP = {
    "google__gson": "https://github.com/google/gson.git",
    "fasterxml__jackson-databind": "https://github.com/FasterXML/jackson-databind.git",
    "fasterxml__jackson-core": "https://github.com/FasterXML/jackson-core.git",
    "fasterxml__jackson-dataformat-xml": "https://github.com/FasterXML/jackson-dataformat-xml.git",
    "mockito__mockito": "https://github.com/mockito/mockito.git",
    "apache__dubbo": "https://github.com/apache/dubbo.git",
    "elastic__logstash": "https://github.com/elastic/logstash.git",
    "alibaba__fastjson2": "https://github.com/alibaba/fastjson2.git",
    "googlecontainertools__jib": "https://github.com/GoogleContainerTools/jib.git",
}

def set_proxy_env():
    """设置代理环境变量"""
    os.environ['http_proxy'] = 'http://172.27.16.1:7890'
    os.environ['https_proxy'] = 'http://172.27.16.1:7890'
    print("代理已设置: http://172.27.16.1:7890")

def run_cmd(cmd: list):
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

def process_instance(instance_data: dict, repos_dir: Path, output_root: Path, idx: int, total: int):
    instance_id = instance_data.get('instance_id')
    if not instance_id:
        print(f"❌ 缺少 instance_id，跳过")
        return

    # 从 org/repo 构建 repo_identifier
    org = instance_data.get('org', '')
    repo = instance_data.get('repo', '')
    repo_identifier = f"{org}__{repo}"

    kg_output_dir = output_root / repo_identifier
    kg_output_dir.mkdir(parents=True, exist_ok=True)
    result_file = kg_output_dir / f"{instance_id}.json"
    
    if result_file.exists():
        print(f"[{idx}/{total}] ✅ KG exists for {instance_id}, skipping.")
        return

    clone_url = JAVA_REPO_URL_MAP.get(repo_identifier)
    if not clone_url:
        print(f"❌ Repo identifier {repo_identifier} not found in mapping, skipping {instance_id}.")
        return

    repo_path = repos_dir / repo_identifier
    if not repo_path.exists():
        print(f"[{idx}/{total}] 🌀 Cloning {repo_identifier} … (full history, this may take a while)")
        run_cmd(["git", "clone", clone_url, str(repo_path)])
    else:
        print(f"[{idx}/{total}] ✅ Repo exists, skip clone.")

    # 确保目标提交存在：获取最新远程历史（如果之前已浅克隆，此步骤会补全缺失提交）
    run_cmd(["git", "-C", str(repo_path), "fetch", "--all", "--tags"])

    # 执行 KG 挖掘，使用 multi-swe-bench 基准
    print(f"[{idx}/{total}] 🚀 Mining KG for {instance_id} …")
    run_cmd(["python3", "kgcompass/fl.py", instance_id, repo_identifier, str(kg_output_dir), "multi-swe-bench"])
    print(f"[{idx}/{total}] 🎉 Saved to {result_file}\n")

def load_java_datasets(data_dir: Path):
    """从 swe-bench_java 目录加载所有 JSONL 文件"""
    print(f"从 {data_dir} 目录加载 Java 数据集...")
    
    # 查找所有 JSONL 文件
    jsonl_files = list(data_dir.glob("*_dataset.jsonl"))
    if not jsonl_files:
        print(f"❌ 在 {data_dir} 目录中没有找到 *_dataset.jsonl 文件")
        return []
    
    all_instances = []
    for jsonl_file in jsonl_files:
        print(f"正在加载: {jsonl_file.name}")
        try:
            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        data = json.loads(line.strip())
                        # 生成 instance_id（如果没有的话）
                        if 'instance_id' not in data:
                            org = data.get('org', '')
                            repo = data.get('repo', '')
                            number = data.get('number', '')
                            data['instance_id'] = f"{org}__{repo}-{number}"
                        all_instances.append(data)
                    except json.JSONDecodeError as e:
                        print(f"⚠️  {jsonl_file.name} 第 {line_num} 行 JSON 解析错误: {e}")
                        continue
        except Exception as e:
            print(f"❌ 读取文件 {jsonl_file} 失败: {e}")
            continue
    
    print(f"总共加载了 {len(all_instances)} 个 Java 实例")
    return all_instances

def main():
    parser = argparse.ArgumentParser(description="简单的 Java KG 挖掘脚本")
    parser.add_argument("--output", default="java_kg_results", help="输出目录")
    parser.add_argument("--repos_dir", default="playground", help="仓库克隆目录")
    parser.add_argument("--limit", type=int, default=None, help="限制处理实例数量（调试用）")
    parser.add_argument("--start", type=int, default=0, help="开始索引")
    parser.add_argument("--data_file", default=None, help="指定单个 JSONL 文件路径（可选）")
    args = parser.parse_args()

    # 设置代理
    set_proxy_env()

    os.environ.setdefault("PYTHONPATH", os.getcwd())

    output_root = Path(args.output)
    output_root.mkdir(parents=True, exist_ok=True)
    repos_dir = Path(args.repos_dir)
    repos_dir.mkdir(parents=True, exist_ok=True)

    # 加载数据
    if args.data_file:
        # 从指定文件加载
        print(f"从指定文件加载: {args.data_file}")
        all_instances = []
        with open(args.data_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    data = json.loads(line.strip())
                    if 'instance_id' not in data:
                        org = data.get('org', '')
                        repo = data.get('repo', '')
                        number = data.get('number', '')
                        data['instance_id'] = f"{org}__{repo}-{number}"
                    all_instances.append(data)
                except json.JSONDecodeError as e:
                    print(f"⚠️  第 {line_num} 行 JSON 解析错误: {e}")
                    continue
    else:
        # 从 swe-bench_java 目录加载所有文件
        data_dir = Path("swe-bench_java")
        if not data_dir.exists():
            print(f"❌ 数据目录 {data_dir} 不存在")
            return
        all_instances = load_java_datasets(data_dir)

    if not all_instances:
        print("❌ 没有找到任何实例")
        return

    # 应用范围限制
    start_idx = args.start
    end_idx = len(all_instances)
    if args.limit:
        end_idx = min(start_idx + args.limit, len(all_instances))
    
    instances_to_process = all_instances[start_idx:end_idx]
    total = len(instances_to_process)
    
    print(f"将处理 {total} 个实例 (索引 {start_idx}-{end_idx-1})")

    # 处理实例
    for idx, instance_data in enumerate(instances_to_process, start=1):
        try:
            process_instance(instance_data, repos_dir, output_root, idx, total)
        except Exception as e:
            instance_id = instance_data.get('instance_id', 'unknown')
            print(f"❌ 处理实例 {instance_id} 时出错: {e}")
            continue

    print("===========================================")
    print("🎉 所有实例处理完成")
    print(f"KG JSON 文件保存在 {output_root}")
    print("===========================================")

if __name__ == "__main__":
    main() 