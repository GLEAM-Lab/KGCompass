#!/usr/bin/env python3
"""
模拟 issue 匹配过程，找出标题差异过大的案例
不修改现有代码，而是重新模拟匹配逻辑
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pylcs
from github import Github
from config import GITHUB_TOKEN, DATASET_NAME
from datasets import load_dataset
import pandas as pd

def calculate_similarity(title1, title2):
    """计算两个标题的相似度（与 fl.py 中的逻辑一致）"""
    # 移除空格和标点
    title1_clean = title1.lower().replace('.', '').replace(' ', '')
    title2_clean = title2.lower().replace('.', '').replace(' ', '')
    
    same_length = pylcs.lcs(title1_clean, title2_clean)
    max_len = max(len(title1_clean), len(title2_clean))
    if max_len == 0:
        return 0.0
    return same_length / max_len

def extract_title(problem_statement):
    """提取标题（problem_statement 的第一行）"""
    return problem_statement.split('\n')[0].strip()

def find_best_match_github(github_client, repo_name, title, created_at_timestamp):
    """模拟 GitHub issue 匹配逻辑"""
    # 搜索时间范围
    end_time = created_at_timestamp + 8 * 60 * 60
    start_time = end_time - (60 * 24 * 60 * 60)  # 60 天
    
    start_date = datetime.fromtimestamp(start_time).strftime('%Y-%m-%d')
    end_date = datetime.fromtimestamp(end_time).strftime('%Y-%m-%d')
    
    search_query = f'repo:{repo_name} is:issue created:{start_date}..{end_date} sort:created-desc'
    
    max_similarity = 0
    best_match_issue = None
    
    try:
        matching_issues = github_client.search_issues(search_query)
        
        for issue in matching_issues:
            # 时间检查
            if issue.created_at.timestamp() > created_at_timestamp:
                continue
            
            similarity = calculate_similarity(title, issue.title)
            
            if similarity > max_similarity:
                max_similarity = similarity
                best_match_issue = {
                    'number': issue.number,
                    'title': issue.title,
                    'similarity': similarity
                }
                
    except Exception as e:
        print(f"  GitHub API 错误: {e}")
        return None, 0
    
    return best_match_issue, max_similarity

def find_best_match_django(df, title, created_at_timestamp):
    """模拟 Django ticket 匹配逻辑"""
    max_similarity = 0
    best_match = None
    
    for _, row in df.iterrows():
        similarity = calculate_similarity(title, row['Summary'])
        
        try:
            created_at = datetime.strptime(row['Created'].split()[0], "%Y年%m月%d日").timestamp()
        except:
            continue
            
        if created_at > created_at_timestamp:
            continue
        
        if similarity > max_similarity:
            max_similarity = similarity
            best_match = {
                'number': row['id'],
                'title': row['Summary'],
                'similarity': similarity
            }
    
    return best_match, max_similarity

def main():
    print("=" * 80)
    print("模拟 Issue 匹配分析")
    print("=" * 80)
    
    # 加载数据集
    print(f"\n加载数据集: {DATASET_NAME}...")
    try:
        ds = load_dataset(DATASET_NAME, split='test')
    except Exception as e:
        print(f"无法加载数据集: {e}")
        return
    
    print(f"数据集加载完成，共 {len(ds)} 个实例\n")
    
    # 初始化 GitHub 客户端
    github_client = Github(GITHUB_TOKEN)
    
    # 加载 Django tickets（如果需要）
    django_df = None
    if os.path.exists('django-tickets.csv'):
        django_df = pd.read_csv('django-tickets.csv')
        print(f"加载了 Django tickets CSV，共 {len(django_df)} 条记录\n")
    
    # 收集低相似度匹配的案例
    low_similarity_cases = []
    similarity_threshold = 0.5  # 相似度阈值
    
    # 只分析已有结果文件的实例
    results_base_dir = Path("runs/kg_verified")
    
    if not results_base_dir.exists():
        print(f"结果目录不存在: {results_base_dir}")
        return
    
    processed_count = 0
    api_limit_reached = False
    
    for item in ds:
        instance_id = item['instance_id']
        repo_name = item['repo']
        
        # 检查是否有对应的结果文件
        result_file = None
        for repo_dir in results_base_dir.iterdir():
            if repo_dir.is_dir():
                potential_file = repo_dir / f"{instance_id}.json"
                if potential_file.exists():
                    result_file = potential_file
                    break
        
        if not result_file:
            continue
        
        processed_count += 1
        
        # 提取标题
        problem_statement = item.get('problem_statement', '')
        title = extract_title(problem_statement)
        
        # 提取创建时间
        created_at_str = item.get('created_at', '')
        try:
            created_at = datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except:
            continue
        
        print(f"[{processed_count}] {instance_id}")
        print(f"  预期标题: {title[:80]}...")
        
        # 查找最佳匹配
        if repo_name == 'django/django' and django_df is not None:
            best_match, similarity = find_best_match_django(django_df, title, created_at)
        else:
            if api_limit_reached:
                print(f"  跳过 (GitHub API 限制)")
                continue
            
            try:
                best_match, similarity = find_best_match_github(github_client, repo_name, title, created_at)
            except Exception as e:
                if "API rate limit exceeded" in str(e):
                    print(f"  GitHub API 限制已达到，停止查询")
                    api_limit_reached = True
                continue
        
        if best_match:
            print(f"  找到匹配: #{best_match['number']} (相似度: {similarity:.3f})")
            print(f"  匹配标题: {best_match['title'][:80]}...")
            
            if similarity < similarity_threshold:
                low_similarity_cases.append({
                    'instance_id': instance_id,
                    'repo': repo_name,
                    'expected_title': title,
                    'matched_issue': best_match['number'],
                    'matched_title': best_match['title'],
                    'similarity': similarity
                })
                print(f"  ⚠️ 相似度低于阈值 {similarity_threshold}")
        else:
            print(f"  未找到匹配的 issue")
        
        print()
        
        # 限制处理数量以避免 API 限制
        if processed_count >= 50:
            print("达到处理上限，停止分析")
            break
    
    # 输出结果
    print("\n" + "=" * 80)
    print(f"分析完成！共处理 {processed_count} 个实例")
    print(f"发现 {len(low_similarity_cases)} 个低相似度匹配案例")
    print("=" * 80)
    
    if low_similarity_cases:
        print(f"\n低相似度匹配案例（相似度 < {similarity_threshold}）：\n")
        
        # 按相似度排序
        low_similarity_cases.sort(key=lambda x: x['similarity'])
        
        for i, case in enumerate(low_similarity_cases, 1):
            print(f"{i}. {case['instance_id']}")
            print(f"   仓库: {case['repo']}")
            print(f"   预期标题: {case['expected_title']}")
            print(f"   匹配 Issue: #{case['matched_issue']}")
            print(f"   匹配标题: {case['matched_title']}")
            print(f"   相似度: {case['similarity']:.3f}")
            print()
        
        # 保存到文件
        output_file = "low_similarity_matches.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(low_similarity_cases, f, indent=2, ensure_ascii=False)
        print(f"结果已保存到: {output_file}")

if __name__ == "__main__":
    main()


