#!/usr/bin/env python3
"""
分析 KG 结果，找出挖掘的 issue 标题与 problem_statement 第一行差异过大的案例
"""

import json
import os
from pathlib import Path
from datasets import load_dataset
import pylcs

def calculate_similarity(title1, title2):
    """计算两个标题的相似度"""
    # 标准化：小写、移除空格和标点
    title1_clean = ' '.join(title1.lower().split())
    title2_clean = ' '.join(title2.lower().split())
    
    same_length = pylcs.lcs(title1_clean, title2_clean)
    max_len = max(len(title1_clean), len(title2_clean))
    if max_len == 0:
        return 0.0
    return same_length / max_len

def extract_first_non_empty_line(text):
    """提取第一个非空行作为标题"""
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            return line
    return lines[0].strip() if lines else ""

def find_matching_issue_from_logs(kg_result_dir, instance_id):
    """从日志文件中查找匹配的 issue 信息"""
    # 这个函数可以后续实现，从日志中提取找到的 issue
    # 目前返回 None
    return None

def main():
    print("加载 SWE-bench Verified 数据集...")
    
    # 加载数据集
    try:
        ds = load_dataset("princeton-nlp/SWE-bench_Verified", split='test')
    except Exception as e:
        print(f"无法加载数据集: {e}")
        print("尝试从本地 JSONL 文件读取...")
        ds = []
        # 这里可以添加从本地文件读取的逻辑
        return
    
    # 创建 instance_id 到数据的映射
    instance_map = {}
    for item in ds:
        instance_map[item['instance_id']] = item
    
    print(f"数据集加载完成，共 {len(instance_map)} 个实例")
    
    # 遍历结果目录
    results_base_dir = Path("runs/kg_verified")
    if not results_base_dir.exists():
        print(f"结果目录不存在: {results_base_dir}")
        return
    
    mismatches = []
    processed_count = 0
    
    # 遍历所有 JSON 结果文件
    for repo_dir in results_base_dir.iterdir():
        if not repo_dir.is_dir():
            continue
            
        for json_file in repo_dir.glob("*.json"):
            instance_id = json_file.stem
            processed_count += 1
            
            # 获取对应的数据集条目
            if instance_id not in instance_map:
                continue
            
            dataset_item = instance_map[instance_id]
            problem_statement = dataset_item.get('problem_statement', '')
            
            # 提取标题
            expected_title = extract_first_non_empty_line(problem_statement)
            
            # 从数据集中提取可能的 issue 信息
            # 注意：SWE-bench 中可能没有直接的 issue 标题字段
            # 我们需要从其他信息推断
            
            # 检查是否有明确的相关 issue 号
            if 'hints_text' in dataset_item and dataset_item['hints_text']:
                hints = dataset_item['hints_text']
                # 这里可以解析 hints 来查找 issue 引用
            
            # 由于 JSON 结果文件中没有保存找到的 issue 信息，
            # 我们需要从日志文件或其他来源获取
            # 暂时跳过这个实例
            
            if processed_count % 100 == 0:
                print(f"已处理 {processed_count} 个实例...")
    
    print(f"\n总共处理 {processed_count} 个实例")
    
    # 由于结果 JSON 文件中不包含找到的 issue 信息，
    # 我们需要修改方法：从日志文件或重新运行时记录这些信息
    print("\n注意：当前结果 JSON 文件中没有包含找到的 issue 信息")
    print("建议：在运行 fl.py 时，将找到的 best_match_issue 信息保存到结果文件中")

if __name__ == "__main__":
    main()


