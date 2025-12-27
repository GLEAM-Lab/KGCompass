#!/usr/bin/env python3
"""
遍历 SWE-bench Verified 所有实例，使用 GitHub API 检查 issue 匹配质量
可以分析所有仓库，但会受到 API rate limit 限制
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
import pylcs
from datasets import load_dataset
import pandas as pd
from tqdm import tqdm
from github import Github, RateLimitExceededException
from config import GITHUB_TOKEN

def calculate_similarity(title1, title2):
    """计算两个标题的相似度（与 fl.py 当前逻辑一致）"""
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

def find_best_match_github(github_client, repo_name, title, created_at_timestamp, max_retries=3):
    """使用 GitHub API 查找最佳匹配"""
    # 时间范围（与 fl.py 逻辑一致）
    end_time = created_at_timestamp + 8 * 60 * 60
    start_time = end_time - (60 * 24 * 60 * 60)  # 60 天
    
    start_date = datetime.fromtimestamp(start_time).strftime('%Y-%m-%d')
    end_date = datetime.fromtimestamp(end_time).strftime('%Y-%m-%d')
    
    search_query = f'repo:{repo_name} is:issue created:{start_date}..{end_date} sort:created-desc'
    
    max_similarity = 0
    best_match = None
    
    for attempt in range(max_retries):
        try:
            matching_issues = github_client.search_issues(search_query)
            
            for issue in matching_issues:
                # 时间检查
                if issue.created_at.timestamp() > created_at_timestamp:
                    continue
                
                similarity = calculate_similarity(title, issue.title)
                
                if similarity > max_similarity:
                    max_similarity = similarity
                    best_match = {
                        'number': issue.number,
                        'title': issue.title,
                        'similarity': similarity
                    }
            
            return best_match, max_similarity
            
        except RateLimitExceededException:
            core_rate_limit = github_client.get_rate_limit().core
            reset_time = core_rate_limit.reset
            wait_seconds = (reset_time - datetime.now()).total_seconds() + 10
            
            print(f"\n⚠️  GitHub API rate limit 达到，需要等待 {wait_seconds/60:.1f} 分钟")
            
            if attempt < max_retries - 1:
                print(f"   将在 {datetime.fromtimestamp(reset_time.timestamp()).strftime('%H:%M:%S')} 后重试...")
                time.sleep(wait_seconds)
            else:
                raise
                
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 指数退避
            else:
                print(f"   GitHub API 错误: {e}")
                return None, 0
    
    return None, 0

def find_best_match_django(df, title, created_at_timestamp):
    """基于本地 CSV 查找 Django ticket 最佳匹配"""
    max_similarity = 0
    best_match = None
    
    for _, row in df.iterrows():
        try:
            similarity = calculate_similarity(title, row['Summary'])
            
            created_str = row['Created'].split()[0]
            created_at = datetime.strptime(created_str, "%Y年%m月%d日").timestamp()
            
            if created_at > created_at_timestamp:
                continue
            
            if similarity > max_similarity:
                max_similarity = similarity
                best_match = {
                    'number': row['id'],
                    'title': row['Summary'],
                    'similarity': similarity
                }
        except Exception:
            continue
    
    return best_match, max_similarity

def check_rate_limit(github_client):
    """检查并显示 API rate limit 状态"""
    rate_limit = github_client.get_rate_limit()
    core = rate_limit.core
    search = rate_limit.search
    
    print(f"\n📊 GitHub API Rate Limit 状态:")
    print(f"   Core API: {core.remaining}/{core.limit} (重置时间: {core.reset.strftime('%H:%M:%S')})")
    print(f"   Search API: {search.remaining}/{search.limit} (重置时间: {search.reset.strftime('%H:%M:%S')})")
    
    return search.remaining

def main():
    print("=" * 100)
    print("SWE-bench Verified 完整 Issue 匹配质量分析（使用 GitHub API）")
    print("=" * 100)
    
    # 设置阈值
    SIMILARITY_THRESHOLD = 0.5
    
    # 检查是否有保存的进度
    progress_file = 'analysis_progress.json'
    if os.path.exists(progress_file):
        print(f"\n发现进度文件: {progress_file}")
        response = input("是否从上次中断处继续？(y/n): ")
        if response.lower() == 'y':
            with open(progress_file, 'r') as f:
                progress = json.load(f)
            processed_ids = set(progress.get('processed_ids', []))
            low_similarity_cases = progress.get('low_similarity_cases', [])
            no_match_cases = progress.get('no_match_cases', [])
            print(f"✓ 已加载进度，已处理 {len(processed_ids)} 个实例")
        else:
            processed_ids = set()
            low_similarity_cases = []
            no_match_cases = []
    else:
        processed_ids = set()
        low_similarity_cases = []
        no_match_cases = []
    
    # 加载数据集
    print("\n[1/6] 加载 SWE-bench Verified 数据集...")
    try:
        ds = load_dataset("princeton-nlp/SWE-bench_Verified", split='test')
        print(f"✓ 加载成功，共 {len(ds)} 个实例")
    except Exception as e:
        print(f"✗ 加载失败: {e}")
        return
    
    instance_map = {item['instance_id']: item for item in ds}
    
    # 加载 Django tickets
    print("\n[2/6] 加载 Django tickets CSV...")
    django_df = None
    if os.path.exists('django-tickets.csv'):
        try:
            django_df = pd.read_csv('django-tickets.csv')
            print(f"✓ 加载成功，共 {len(django_df)} 条记录")
        except Exception as e:
            print(f"✗ 加载失败: {e}")
    else:
        print("✗ 文件不存在，将使用 GitHub API 查询 Django issues")
    
    # 初始化 GitHub 客户端
    print("\n[3/6] 初始化 GitHub API 客户端...")
    try:
        github_client = Github(GITHUB_TOKEN)
        remaining = check_rate_limit(github_client)
        
        if remaining < 10:
            print("\n⚠️  Search API 配额不足，建议稍后再试")
            response = input("是否继续？(y/n): ")
            if response.lower() != 'y':
                return
    except Exception as e:
        print(f"✗ 初始化失败: {e}")
        return
    
    # 查找所有结果文件
    print("\n[4/6] 扫描结果文件...")
    results_base_dir = Path("runs/kg_verified")
    
    if not results_base_dir.exists():
        print(f"✗ 结果目录不存在: {results_base_dir}")
        return
    
    result_files = []
    for repo_dir in results_base_dir.iterdir():
        if repo_dir.is_dir():
            for json_file in repo_dir.glob("*.json"):
                instance_id = json_file.stem
                if instance_id not in processed_ids:
                    result_files.append({
                        'path': json_file,
                        'instance_id': instance_id,
                        'repo': repo_dir.name
                    })
    
    print(f"✓ 找到 {len(result_files)} 个待处理结果文件")
    
    # 分析每个实例
    print(f"\n[5/6] 分析 issue 匹配质量...")
    
    api_limit_reached = False
    analyzed_count = 0
    
    try:
        for file_info in tqdm(result_files, desc="处理中"):
            if api_limit_reached:
                print(f"\n⚠️  API 限制已达到，停止分析")
                break
            
            instance_id = file_info['instance_id']
            repo_name = file_info['repo'].replace('__', '/')
            
            # 获取数据集信息
            if instance_id not in instance_map:
                processed_ids.add(instance_id)
                continue
            
            dataset_item = instance_map[instance_id]
            problem_statement = dataset_item.get('problem_statement', '')
            title = extract_title(problem_statement)
            
            # 解析创建时间
            created_at_str = dataset_item.get('created_at', '')
            try:
                created_at = datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            except:
                processed_ids.add(instance_id)
                continue
            
            # 查找最佳匹配
            try:
                if repo_name == 'django/django' and django_df is not None:
                    # 优先使用本地 CSV
                    best_match, similarity = find_best_match_django(django_df, title, created_at)
                else:
                    # 使用 GitHub API
                    best_match, similarity = find_best_match_github(github_client, repo_name, title, created_at)
                
                if best_match:
                    if similarity < SIMILARITY_THRESHOLD:
                        low_similarity_cases.append({
                            'instance_id': instance_id,
                            'repo': repo_name,
                            'expected_title': title,
                            'matched_issue': best_match['number'],
                            'matched_title': best_match['title'],
                            'similarity': similarity
                        })
                else:
                    no_match_cases.append({
                        'instance_id': instance_id,
                        'repo': repo_name,
                        'expected_title': title
                    })
                
                processed_ids.add(instance_id)
                analyzed_count += 1
                
                # 每处理 10 个保存一次进度
                if analyzed_count % 10 == 0:
                    with open(progress_file, 'w') as f:
                        json.dump({
                            'processed_ids': list(processed_ids),
                            'low_similarity_cases': low_similarity_cases,
                            'no_match_cases': no_match_cases
                        }, f, indent=2)
                
            except RateLimitExceededException:
                api_limit_reached = True
                print(f"\n⚠️  API rate limit 达到，已处理 {analyzed_count} 个实例")
                break
            except Exception as e:
                print(f"\n⚠️  处理 {instance_id} 时出错: {e}")
                processed_ids.add(instance_id)
                continue
    
    except KeyboardInterrupt:
        print(f"\n\n⚠️  用户中断，保存当前进度...")
    
    # 保存最终进度
    with open(progress_file, 'w') as f:
        json.dump({
            'processed_ids': list(processed_ids),
            'low_similarity_cases': low_similarity_cases,
            'no_match_cases': no_match_cases
        }, f, indent=2)
    
    # 输出结果
    print(f"\n[6/6] 分析完成！")
    print("=" * 100)
    
    print(f"\n📊 统计信息:")
    print(f"  - 总实例数: {len(instance_map)}")
    print(f"  - 已处理: {len(processed_ids)}")
    print(f"  - 低相似度匹配: {len(low_similarity_cases)}")
    print(f"  - 未找到匹配: {len(no_match_cases)}")
    
    # 输出并保存低相似度案例
    if low_similarity_cases:
        print(f"\n🔴 低相似度匹配案例（< {SIMILARITY_THRESHOLD}）：{len(low_similarity_cases)} 个")
        print("=" * 100)
        
        low_similarity_cases.sort(key=lambda x: x['similarity'])
        
        # 显示前 10 个
        for i, case in enumerate(low_similarity_cases[:10], 1):
            print(f"\n{i}. {case['instance_id']}")
            print(f"   仓库: {case['repo']}")
            print(f"   预期标题: {case['expected_title'][:70]}")
            print(f"   匹配 Issue: #{case['matched_issue']}")
            print(f"   匹配标题: {case['matched_title'][:70]}")
            print(f"   相似度: {case['similarity']:.3f}")
        
        if len(low_similarity_cases) > 10:
            print(f"\n... 还有 {len(low_similarity_cases) - 10} 个（详见输出文件）")
        
        # 保存 instance_id 列表
        low_sim_ids = [case['instance_id'] for case in low_similarity_cases]
        
        with open('low_similarity_instance_ids.txt', 'w') as f:
            for instance_id in low_sim_ids:
                f.write(f"{instance_id}\n")
        
        print(f"\n✓ 低相似度 instance_id 列表已保存到: low_similarity_instance_ids.txt")
        
        # 保存详细信息
        with open('low_similarity_matches_detailed.json', 'w', encoding='utf-8') as f:
            json.dump(low_similarity_cases, f, indent=2, ensure_ascii=False)
        
        print(f"✓ 详细信息已保存到: low_similarity_matches_detailed.json")
        
        # 按仓库统计
        repo_stats = {}
        for case in low_similarity_cases:
            repo = case['repo']
            repo_stats[repo] = repo_stats.get(repo, 0) + 1
        
        print(f"\n📊 按仓库统计:")
        for repo, count in sorted(repo_stats.items(), key=lambda x: -x[1]):
            print(f"   {repo}: {count} 个")
    
    print("\n" + "=" * 100)
    print("分析完成！")
    
    if len(processed_ids) < len(instance_map):
        print(f"\n💡 提示: 还有 {len(instance_map) - len(processed_ids)} 个实例未处理")
        print(f"   重新运行此脚本将从上次中断处继续")

if __name__ == "__main__":
    main()


