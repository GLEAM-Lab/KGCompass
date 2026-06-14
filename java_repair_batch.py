#!/usr/bin/env python3
"""
Java 批量修复脚本 - 在 KG 生成后继续后续流程
使用 DeepSeek 模型生成修复方案
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

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

def setup_environment():
    """设置环境变量"""
    os.environ['PYTHONPATH'] = os.getcwd()
    os.environ['http_proxy'] = 'http://172.27.16.1:7890'
    os.environ['https_proxy'] = 'http://172.27.16.1:7890'
    if 'all_proxy' in os.environ:
        del os.environ['all_proxy']
    print("✅ 环境变量已设置")

def clone_repository(repo_identifier):
    """克隆仓库"""
    clone_url = JAVA_REPO_URL_MAP.get(repo_identifier)
    if not clone_url:
        print(f"❌ 不支持的仓库: {repo_identifier}")
        return None
    
    repos_dir = "./playground"
    repo_path = os.path.join(repos_dir, repo_identifier)
    
    if os.path.exists(repo_path):
        print(f"✅ 仓库 {repo_identifier} 已存在")
        return repo_path
    
    print(f"🔄 正在克隆仓库: {repo_identifier}")
    os.makedirs(repos_dir, exist_ok=True)
    
    try:
        subprocess.run(['git', 'clone', clone_url, repo_path], check=True, capture_output=True)
        print(f"✅ 仓库克隆成功: {repo_path}")
        return repo_path
    except subprocess.CalledProcessError as e:
        print(f"❌ 克隆仓库失败: {e}")
        return None

def process_single_instance(instance_id, kg_dir, model_name="deepseek", temperature=0.3):
    """处理单个实例"""
    print(f"\n🔄 开始处理实例: {instance_id}")
    
    # 提取仓库标识符
    repo_identifier = instance_id.rsplit('-', 1)[0]
    
    # 检查 KG 文件是否存在
    kg_file = os.path.join(kg_dir, repo_identifier, f"{instance_id}.json")
    if not os.path.exists(kg_file):
        print(f"❌ KG 文件不存在: {kg_file}")
        return False
    
    # 克隆仓库
    repo_path = clone_repository(repo_identifier)
    if not repo_path:
        return False
    
    # 创建运行目录
    run_dir = f"tests_java/{instance_id}_{model_name}"
    os.makedirs(run_dir, exist_ok=True)
    
    # 创建子目录
    kg_locations_dir = os.path.join(run_dir, "kg_locations")
    llm_locations_dir = os.path.join(run_dir, "llm_locations")
    final_locations_dir = os.path.join(run_dir, "final_locations")
    patch_dir = os.path.join(run_dir, "patches")
    
    for dir_path in [kg_locations_dir, llm_locations_dir, final_locations_dir, patch_dir]:
        os.makedirs(dir_path, exist_ok=True)
    
    try:
        # Step 1: 复制 KG 文件
        kg_result_file = os.path.join(kg_locations_dir, f"{instance_id}.json")
        if not os.path.exists(kg_result_file):
            import shutil
            shutil.copy2(kg_file, kg_result_file)
            print(f"✅ KG 文件已复制: {kg_result_file}")
        
        # Step 2: LLM-based Bug Location
        llm_result_file = os.path.join(llm_locations_dir, f"{instance_id}.json")
        if not os.path.exists(llm_result_file):
            print("🔄 生成 LLM 位置...")
            cmd = [
                'python3', 'kgcompass/llm_loc.py', llm_locations_dir,
                '--instance_id', instance_id,
                '--benchmark', 'multi-swe-bench'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                print(f"❌ LLM 位置生成失败: {result.stderr}")
                return False
            print("✅ LLM 位置生成完成")
        
        # Step 3: Merge Bug Locations
        final_result_file = os.path.join(final_locations_dir, f"{instance_id}.json")
        if not os.path.exists(final_result_file):
            print("🔄 合并位置信息...")
            cmd = [
                'python3', 'kgcompass/fix_fl_line.py', llm_locations_dir, final_locations_dir,
                '--instance_id', instance_id,
                '--benchmark', 'multi-swe-bench'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                print(f"❌ 位置合并失败: {result.stderr}")
                return False
            print("✅ 位置合并完成")
        
        # Step 4: Generate Patch
        patch_file = os.path.join(patch_dir, f"{instance_id}.patch")
        if not os.path.exists(patch_file):
            print("🔄 生成修复补丁...")
            cmd = [
                'python3', 'kgcompass/repair.py', final_locations_dir,
                '--instance_id', instance_id,
                '--playground_dir', './playground',
                '--repo_identifier', repo_identifier,
                '--language', 'java'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
            if result.returncode != 0:
                print(f"❌ 补丁生成失败: {result.stderr}")
                return False
            print("✅ 补丁生成完成")
        
        print(f"🎉 实例 {instance_id} 处理完成")
        return True
        
    except subprocess.TimeoutExpired:
        print(f"❌ 处理实例超时: {instance_id}")
        return False
    except Exception as e:
        print(f"❌ 处理实例异常: {instance_id}, 错误: {e}")
        return False

def get_java_instances(kg_dir):
    """获取所有 Java 实例"""
    instances = []
    kg_path = Path(kg_dir)
    
    if not kg_path.exists():
        print(f"❌ KG 目录不存在: {kg_dir}")
        return instances
    
    # 遍历所有仓库目录
    for repo_dir in kg_path.iterdir():
        if repo_dir.is_dir() and repo_dir.name in JAVA_REPO_URL_MAP:
            # 遍历该仓库的所有 JSON 文件
            for json_file in repo_dir.glob("*.json"):
                instance_id = json_file.stem
                instances.append(instance_id)
    
    return sorted(instances)

def main():
    parser = argparse.ArgumentParser(description="Java 批量修复脚本")
    parser.add_argument("--kg_dir", default="java_kg_results", help="KG 结果目录")
    parser.add_argument("--model", default="deepseek", help="使用的模型")
    parser.add_argument("--temperature", type=float, default=0.3, help="温度参数")
    parser.add_argument("--workers", type=int, default=2, help="并行工作数")
    parser.add_argument("--instance_id", help="处理特定实例")
    parser.add_argument("--limit", type=int, help="限制处理数量")
    parser.add_argument("--start", type=int, default=0, help="开始索引")
    
    args = parser.parse_args()
    
    # 设置环境
    setup_environment()
    
    # 获取要处理的实例
    if args.instance_id:
        instances = [args.instance_id]
    else:
        instances = get_java_instances(args.kg_dir)
        if args.limit:
            instances = instances[args.start:args.start + args.limit]
        else:
            instances = instances[args.start:]
    
    if not instances:
        print("❌ 没有找到要处理的实例")
        return
    
    print(f"📋 将处理 {len(instances)} 个实例")
    for i, instance_id in enumerate(instances[:5]):  # 显示前5个
        print(f"  {i+1}. {instance_id}")
    if len(instances) > 5:
        print(f"  ... 还有 {len(instances) - 5} 个实例")
    
    # 处理实例
    success_count = 0
    failed_count = 0
    
    if args.workers == 1:
        # 单线程处理
        for instance_id in instances:
            success = process_single_instance(instance_id, args.kg_dir, args.model, args.temperature)
            if success:
                success_count += 1
            else:
                failed_count += 1
    else:
        # 多线程处理
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_instance = {
                executor.submit(process_single_instance, instance_id, args.kg_dir, args.model, args.temperature): instance_id
                for instance_id in instances
            }
            
            for future in as_completed(future_to_instance):
                instance_id = future_to_instance[future]
                try:
                    success = future.result()
                    if success:
                        success_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    print(f"❌ 实例 {instance_id} 处理异常: {e}")
                    failed_count += 1
    
    print(f"\n🎉 批量处理完成!")
    print(f"✅ 成功: {success_count} 个")
    print(f"❌ 失败: {failed_count} 个")
    print(f"📊 总计: {success_count + failed_count} 个")

if __name__ == "__main__":
    main() 