#!/usr/bin/env python3
"""
从 runs/kg_verified/*/*.json 结果文件出发
检查非 Django 实例的 issue 匹配质量
重新模拟匹配逻辑，比较 benchmark 标题与匹配的 issue 标题
"""

import json
from pathlib import Path
from datetime import datetime, timezone
import pylcs
from datasets import load_dataset
from github import Github, RateLimitExceededException
import time
import os
import sys

# 添加 kgcompass 到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'kgcompass'))

try:
    from config import GITHUB_TOKEN
except ImportError:
    # 如果无法导入，尝试直接读取环境变量
    GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
    if not GITHUB_TOKEN:
        print("错误: 无法获取 GITHUB_TOKEN")
        print("请设置环境变量: export GITHUB_TOKEN='your_token'")
        sys.exit(1)

def calculate_similarity(title1, title2):
    """计算相似度（与 fl.py 一致）"""
    title1_clean = title1.lower().replace('.', '').replace(' ', '')
    title2_clean = title2.lower().replace('.', '').replace(' ', '')
    
    same_length = pylcs.lcs(title1_clean, title2_clean)
    max_len = max(len(title1_clean), len(title2_clean))
    if max_len == 0:
        return 0.0
    return same_length / max_len

def extract_title(problem_statement):
    """提取标题"""
    return problem_statement.split('\n')[0].strip()

def find_best_match_github(github_client, repo_name, title, created_at_timestamp):
    """模拟 fl.py 的 GitHub issue 匹配逻辑"""
    # 时间范围（与 fl.py 当前逻辑一致）
    end_time = created_at_timestamp + 8 * 60 * 60
    start_time = end_time - (60 * 24 * 60 * 60)  # 60 天
    
    start_date = datetime.fromtimestamp(start_time).strftime('%Y-%m-%d')
    end_date = datetime.fromtimestamp(end_time).strftime('%Y-%m-%d')
    
    search_query = f'repo:{repo_name} is:issue created:{start_date}..{end_date} sort:created-desc'
    
    max_similarity = 0
    best_match = None
    
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
        raise
    except Exception as e:
        print(f"    GitHub API 错误: {e}")
        return None, 0

def main():
    print("=" * 80)
    print("检查非 Django 实例的 Issue 匹配质量")
    print("=" * 80)
    
    SIMILARITY_THRESHOLD = 0.5
    
    # 1. 加载数据集
    print("\n[1/5] 加载 SWE-bench Verified 数据集...")
    try:
        ds = load_dataset("princeton-nlp/SWE-bench_Verified", split='test')
        instance_map = {item['instance_id']: item for item in ds}
        print(f"✓ 加载成功，共 {len(ds)} 个实例")
    except Exception as e:
        print(f"✗ 加载失败: {e}")
        return
    
    # 2. 扫描结果文件
    print("\n[2/5] 扫描结果文件 (runs/kg_verified/*/*.json)...")
    results_base_dir = Path("runs/kg_verified")
    
    if not results_base_dir.exists():
        print(f"✗ 结果目录不存在: {results_base_dir}")
        return
    
    result_files = []
    for repo_dir in results_base_dir.iterdir():
        if repo_dir.is_dir():
            for json_file in repo_dir.glob("*.json"):
                result_files.append({
                    'path': json_file,
                    'instance_id': json_file.stem,
                    'repo': repo_dir.name.replace('__', '/')
                })
    
    print(f"✓ 找到 {len(result_files)} 个结果文件")
    
    # 3. 筛选非 Django 实例
    print("\n[3/5] 筛选非 Django 实例...")
    non_django_files = []
    django_count = 0
    
    for file_info in result_files:
        instance_id = file_info['instance_id']
        
        if instance_id not in instance_map:
            continue
        
        dataset_item = instance_map[instance_id]
        repo_name = dataset_item['repo']
        
        if repo_name == 'django/django':
            django_count += 1
        else:
            non_django_files.append({
                'instance_id': instance_id,
                'repo': repo_name,
                'dataset_item': dataset_item,
                'result_path': file_info['path']
            })
    
    print(f"✓ Django 实例: {django_count} 个（跳过）")
    print(f"✓ 非 Django 实例: {len(non_django_files)} 个（需要检查）")
    
    # 4. 初始化 GitHub 客户端
    print("\n[4/5] 初始化 GitHub API 客户端...")
    try:
        github_client = Github(GITHUB_TOKEN)
        rate_limit = github_client.get_rate_limit()
        search_remaining = rate_limit.search.remaining
        print(f"✓ Search API 剩余配额: {search_remaining}/{rate_limit.search.limit}")
        
        if search_remaining < 10:
            print(f"⚠️  配额不足，建议稍后再试")
            response = input("是否继续？(y/n): ")
            if response.lower() != 'y':
                return
    except Exception as e:
        print(f"✗ 初始化失败: {e}")
        return
    
    # 5. 检查每个非 Django 实例
    print(f"\n[5/5] 检查 issue 匹配质量（阈值: {SIMILARITY_THRESHOLD}）...")
    print(f"⚠️  这将调用 GitHub API，可能需要较长时间\n")
    
    low_similarity_cases = []
    no_match_cases = []
    analyzed_count = 0
    
    for i, file_info in enumerate(non_django_files, 1):
        instance_id = file_info['instance_id']
        repo_name = file_info['repo']
        dataset_item = file_info['dataset_item']
        
        # 提取信息
        problem_statement = dataset_item.get('problem_statement', '')
        expected_title = extract_title(problem_statement)
        
        created_at_str = dataset_item.get('created_at', '')
        try:
            created_at = datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except:
            continue
        
        print(f"[{i}/{len(non_django_files)}] {instance_id}")
        print(f"  仓库: {repo_name}")
        print(f"  预期标题: {expected_title[:70]}")
        
        # 查找最佳匹配
        try:
            best_match, similarity = find_best_match_github(github_client, repo_name, expected_title, created_at)
            
            if best_match:
                print(f"  找到匹配: #{best_match['number']} (相似度: {similarity:.3f})")
                print(f"  匹配标题: {best_match['title'][:70]}")
                
                if similarity < SIMILARITY_THRESHOLD:
                    print(f"  ⚠️  相似度低于阈值 {SIMILARITY_THRESHOLD}")
                    low_similarity_cases.append({
                        'instance_id': instance_id,
                        'repo': repo_name,
                        'expected_title': expected_title,
                        'matched_issue': best_match['number'],
                        'matched_title': best_match['title'],
                        'similarity': similarity
                    })
                else:
                    print(f"  ✓ 相似度正常")
            else:
                print(f"  未找到匹配")
                no_match_cases.append({
                    'instance_id': instance_id,
                    'repo': repo_name,
                    'expected_title': expected_title
                })
            
            analyzed_count += 1
            print()
            
            # 每 10 个检查一次 rate limit
            if analyzed_count % 10 == 0:
                rate_limit = github_client.get_rate_limit()
                remaining = rate_limit.search.remaining
                print(f"  💡 API 配额剩余: {remaining}/{rate_limit.search.limit}")
                
                if remaining < 5:
                    print(f"  ⚠️  配额不足，停止检查")
                    break
            
            # 避免 rate limit
            time.sleep(2)
            
        except RateLimitExceededException:
            print(f"  ⚠️  API rate limit 达到，已检查 {analyzed_count} 个实例")
            break
        except KeyboardInterrupt:
            print(f"\n\n⚠️  用户中断，已检查 {analyzed_count} 个实例")
            break
        except Exception as e:
            print(f"  错误: {e}")
            continue
    
    # 输出结果
    print("\n" + "=" * 80)
    print("📊 分析结果:")
    print(f"  - 非 Django 实例总数: {len(non_django_files)}")
    print(f"  - 已检查: {analyzed_count}")
    print(f"  - 低相似度匹配: {len(low_similarity_cases)}")
    print(f"  - 未找到匹配: {len(no_match_cases)}")
    print("=" * 80)
    
    if low_similarity_cases:
        print(f"\n🔴 低相似度匹配案例（< {SIMILARITY_THRESHOLD}）：")
        print("=" * 80)
        
        # 按相似度排序
        low_similarity_cases.sort(key=lambda x: x['similarity'])
        
        for i, case in enumerate(low_similarity_cases, 1):
            print(f"\n{i}. {case['instance_id']}")
            print(f"   仓库: {case['repo']}")
            print(f"   预期标题: {case['expected_title'][:70]}")
            print(f"   匹配 Issue: #{case['matched_issue']}")
            print(f"   匹配标题: {case['matched_title'][:70]}")
            print(f"   相似度: {case['similarity']:.3f}")
        
        # 保存结果
        low_sim_ids = [case['instance_id'] for case in low_similarity_cases]
        
        with open('low_similarity_instance_ids.txt', 'w') as f:
            for instance_id in low_sim_ids:
                f.write(f"{instance_id}\n")
        
        print(f"\n✓ 低相似度 instance_id 已保存到: low_similarity_instance_ids.txt")
        
        with open('low_similarity_matches_detailed.json', 'w', encoding='utf-8') as f:
            json.dump(low_similarity_cases, f, indent=2, ensure_ascii=False)
        
        print(f"✓ 详细信息已保存到: low_similarity_matches_detailed.json")
        
        # 按仓库统计
        repo_stats = {}
        for case in low_similarity_cases:
            repo = case['repo']
            repo_stats[repo] = repo_stats.get(repo, 0) + 1
        
        if repo_stats:
            print(f"\n📦 按仓库统计:")
            for repo, count in sorted(repo_stats.items(), key=lambda x: -x[1]):
                print(f"  - {repo}: {count} 个")
    
    if analyzed_count < len(non_django_files):
        print(f"\n💡 提示: 还有 {len(non_django_files) - analyzed_count} 个实例未检查")
        print(f"   由于 API 限制，建议稍后继续")
    
    print("\n" + "=" * 80)
    print("完成！")

if __name__ == "__main__":
    main()

