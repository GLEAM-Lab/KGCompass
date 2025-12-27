#!/usr/bin/env python3
"""
遍历 SWE-bench Verified 所有实例，检查 issue 匹配质量
找出所有标题差异度过高的 instance_id 列表
"""

import json
import os
from pathlib import Path
from datetime import datetime, timezone
import pylcs
from datasets import load_dataset
import pandas as pd
from tqdm import tqdm

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

def find_best_match_django(df, title, created_at_timestamp):
    """基于本地 CSV 查找 Django ticket 最佳匹配"""
    max_similarity = 0
    best_match = None
    
    for _, row in df.iterrows():
        try:
            similarity = calculate_similarity(title, row['Summary'])
            
            # 解析创建时间
            created_str = row['Created'].split()[0]
            created_at = datetime.strptime(created_str, "%Y年%m月%d日").timestamp()
            
            # 时间检查（与 fl.py 逻辑一致）
            if created_at > created_at_timestamp:
                continue
            
            if similarity > max_similarity:
                max_similarity = similarity
                best_match = {
                    'number': row['id'],
                    'title': row['Summary'],
                    'similarity': similarity
                }
        except Exception as e:
            continue
    
    return best_match, max_similarity

def main():
    print("=" * 100)
    print("SWE-bench Verified Issue 匹配质量分析")
    print("=" * 100)
    
    # 设置阈值
    SIMILARITY_THRESHOLD = 0.5
    
    # 加载数据集
    print("\n[1/5] 加载 SWE-bench Verified 数据集...")
    try:
        ds = load_dataset("princeton-nlp/SWE-bench_Verified", split='test')
        print(f"✓ 加载成功，共 {len(ds)} 个实例")
    except Exception as e:
        print(f"✗ 加载失败: {e}")
        return
    
    # 创建实例映射
    instance_map = {item['instance_id']: item for item in ds}
    
    # 加载 Django tickets
    print("\n[2/5] 加载 Django tickets CSV...")
    django_df = None
    if os.path.exists('django-tickets.csv'):
        try:
            django_df = pd.read_csv('django-tickets.csv')
            print(f"✓ 加载成功，共 {len(django_df)} 条记录")
        except Exception as e:
            print(f"✗ 加载失败: {e}")
    else:
        print("✗ 文件不存在")
    
    # 查找所有结果文件
    print("\n[3/5] 扫描结果文件...")
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
                    'repo': repo_dir.name
                })
    
    print(f"✓ 找到 {len(result_files)} 个结果文件")
    
    # 分析每个实例
    print(f"\n[4/5] 分析 issue 匹配质量（仅 Django，其他仓库需要 GitHub API）...")
    
    low_similarity_cases = []
    no_match_cases = []
    django_only_analyzed = []
    skipped_non_django = []
    
    for file_info in tqdm(result_files, desc="处理中"):
        instance_id = file_info['instance_id']
        repo_name = file_info['repo'].replace('__', '/')
        
        # 获取数据集信息
        if instance_id not in instance_map:
            continue
        
        dataset_item = instance_map[instance_id]
        problem_statement = dataset_item.get('problem_statement', '')
        title = extract_title(problem_statement)
        
        # 解析创建时间
        created_at_str = dataset_item.get('created_at', '')
        try:
            created_at = datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except:
            continue
        
        # 只分析 Django（因为有本地 CSV）
        if repo_name == 'django/django' and django_df is not None:
            best_match, similarity = find_best_match_django(django_df, title, created_at)
            
            if best_match:
                django_only_analyzed.append(instance_id)
                
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
        else:
            # 非 Django 仓库跳过（需要 GitHub API）
            skipped_non_django.append({
                'instance_id': instance_id,
                'repo': repo_name,
                'expected_title': title
            })
    
    # 输出结果
    print(f"\n[5/5] 分析完成！")
    print("=" * 100)
    
    print(f"\n📊 统计信息:")
    print(f"  - 总结果文件: {len(result_files)}")
    print(f"  - Django 实例分析: {len(django_only_analyzed)}")
    print(f"  - 非 Django 跳过: {len(skipped_non_django)}")
    print(f"  - 低相似度匹配: {len(low_similarity_cases)}")
    print(f"  - 未找到匹配: {len(no_match_cases)}")
    
    # 输出低相似度案例
    if low_similarity_cases:
        print(f"\n🔴 低相似度匹配案例（< {SIMILARITY_THRESHOLD}）：{len(low_similarity_cases)} 个")
        print("=" * 100)
        
        # 按相似度排序
        low_similarity_cases.sort(key=lambda x: x['similarity'])
        
        for i, case in enumerate(low_similarity_cases, 1):
            print(f"\n{i}. {case['instance_id']}")
            print(f"   预期标题: {case['expected_title'][:80]}")
            print(f"   匹配 Issue: #{case['matched_issue']}")
            print(f"   匹配标题: {case['matched_title'][:80]}")
            print(f"   相似度: {case['similarity']:.3f}")
        
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
    
    # 输出未匹配案例
    if no_match_cases:
        print(f"\n⚠️  未找到匹配的案例：{len(no_match_cases)} 个")
        for case in no_match_cases[:5]:  # 只显示前5个
            print(f"  - {case['instance_id']}: {case['expected_title'][:60]}")
        if len(no_match_cases) > 5:
            print(f"  ... 还有 {len(no_match_cases) - 5} 个")
    
    # 关于非 Django 仓库的说明
    if skipped_non_django:
        print(f"\n💡 注意: {len(skipped_non_django)} 个非 Django 实例被跳过")
        print("   原因: 需要 GitHub API 才能分析（避免 rate limit）")
        
        # 列出涉及的仓库
        repos = {}
        for case in skipped_non_django:
            repo = case['repo']
            repos[repo] = repos.get(repo, 0) + 1
        
        print(f"\n   涉及仓库:")
        for repo, count in sorted(repos.items(), key=lambda x: -x[1])[:10]:
            print(f"     - {repo}: {count} 个")
        
        # 保存跳过的列表
        skipped_ids = [case['instance_id'] for case in skipped_non_django]
        with open('skipped_non_django_ids.txt', 'w') as f:
            for instance_id in skipped_ids:
                f.write(f"{instance_id}\n")
        
        print(f"\n   已保存跳过的 instance_id 到: skipped_non_django_ids.txt")
        print(f"   如需分析这些实例，请使用 simulate_issue_matching.py（需要 GitHub API）")
    
    print("\n" + "=" * 100)
    print("分析完成！")
    
    # 生成总结报告
    summary = {
        'total_result_files': len(result_files),
        'django_analyzed': len(django_only_analyzed),
        'low_similarity_count': len(low_similarity_cases),
        'no_match_count': len(no_match_cases),
        'skipped_non_django': len(skipped_non_django),
        'similarity_threshold': SIMILARITY_THRESHOLD,
        'low_similarity_ids': [case['instance_id'] for case in low_similarity_cases]
    }
    
    with open('analysis_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    print(f"✓ 总结报告已保存到: analysis_summary.json")

if __name__ == "__main__":
    main()


