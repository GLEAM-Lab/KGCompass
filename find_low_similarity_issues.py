#!/usr/bin/env python3
"""
从 JSON 结果文件中提取挖掘出的 issue 信息
比较初始任务描述与挖掘出的 issue 标题的相似度
完全不需要 GitHub API！
"""

import json
from pathlib import Path
import pylcs
from datasets import load_dataset

def calculate_similarity(title1, title2):
    """计算相似度（与 fl.py 一致）"""
    title1_clean = title1.lower().replace('.', '').replace(' ', '')
    title2_clean = title2.lower().replace('.', '').replace(' ', '')
    
    same_length = pylcs.lcs(title1_clean, title2_clean)
    max_len = max(len(title1_clean), len(title2_clean))
    if max_len == 0:
        return 0.0
    return same_length / max_len

def main():
    print("=" * 80)
    print("分析 JSON 结果文件中的 Issue 匹配质量")
    print("=" * 80)
    
    SIMILARITY_THRESHOLD = 0.95
    
    # 1. 加载数据集（用于获取 repo 信息）
    print("\n[1/4] 加载 SWE-bench Verified 数据集...")
    try:
        ds = load_dataset("princeton-nlp/SWE-bench_Verified", split='test')
        instance_map = {item['instance_id']: item for item in ds}
        print(f"✓ 加载成功，共 {len(ds)} 个实例")
    except Exception as e:
        print(f"⚠️  加载失败: {e}，将继续但无法过滤 Django")
        instance_map = {}
    
    # 2. 扫描结果文件
    print("\n[2/4] 扫描结果文件 (runs/kg_verified/*/*.json)...")
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
                    'instance_id': json_file.stem
                })
    
    print(f"✓ 找到 {len(result_files)} 个结果文件")
    
    # 3. 分析每个文件
    print(f"\n[3/4] 分析 issue 匹配质量（阈值: {SIMILARITY_THRESHOLD}）...")
    
    low_similarity_cases = []
    django_skipped = 0
    non_django_analyzed = 0
    no_issues_found = 0
    
    for file_info in result_files:
        instance_id = file_info['instance_id']
        json_path = file_info['path']
        
        # 获取 repo 信息
        repo = 'unknown'
        if instance_id in instance_map:
            repo = instance_map[instance_id]['repo']
        
        # 跳过 Django（用本地 CSV，不是通过 GitHub API 匹配的）
        if repo == 'django/django':
            django_skipped += 1
            continue
        
        # 读取 JSON 文件
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"  ⚠️  读取 {json_path.name} 失败: {e}")
            continue
        
        # 提取 issues
        issues = data.get('related_entities', {}).get('issues', [])
        
        if not issues:
            no_issues_found += 1
            continue
        
        # issues 列表中：
        # - 第一个是 root issue（初始任务描述）
        # - 第二个是挖掘出的最相关 issue（相似度最高）
        
        if len(issues) < 2:
            continue
        
        root_issue = issues[0]
        best_matched_issue = issues[1]
        
        # 验证第一个确实是 root
        if root_issue.get('issue_id') != 'root':
            # 如果第一个不是 root，尝试找到 root
            root_issue = None
            for issue in issues:
                if issue.get('issue_id') == 'root':
                    root_issue = issue
                    break
            if not root_issue:
                continue
            
            # 找到 root 后，取下一个非 root 的作为最佳匹配
            best_matched_issue = None
            for issue in issues:
                if issue.get('issue_id') != 'root':
                    best_matched_issue = issue
                    break
            if not best_matched_issue:
                continue
        
        root_title = root_issue.get('title', '')
        matched_title = best_matched_issue.get('title', '')
        matched_issue_id = best_matched_issue.get('issue_id', '')
        
        if not root_title or not matched_title:
            continue
        
        non_django_analyzed += 1
        
        # 计算相似度
        similarity = calculate_similarity(root_title, matched_title)
        
        if similarity < SIMILARITY_THRESHOLD:
            low_similarity_cases.append({
                'instance_id': instance_id,
                'repo': repo,
                'root_title': root_title,
                'matched_issue_id': matched_issue_id,
                'matched_title': matched_title,
                'similarity': similarity
            })
    
    # 4. 输出结果
    print("\n" + "=" * 80)
    print("📊 分析结果:")
    print(f"  - 总结果文件: {len(result_files)}")
    print(f"  - Django 实例: {django_skipped} （已跳过）")
    print(f"  - 非 Django 实例: {non_django_analyzed}")
    print(f"  - 未找到 issues: {no_issues_found}")
    print(f"  - 低相似度匹配: {len(low_similarity_cases)}")
    print("=" * 80)
    
    if low_similarity_cases:
        print(f"\n🔴 低相似度匹配案例（< {SIMILARITY_THRESHOLD}）：")
        print("=" * 80)
        
        # 按相似度排序
        low_similarity_cases.sort(key=lambda x: x['similarity'])
        
        for i, case in enumerate(low_similarity_cases, 1):
            print(f"\n{i}. {case['instance_id']}")
            print(f"   仓库: {case['repo']}")
            print(f"   初始任务: {case['root_title'][:70]}")
            print(f"   匹配 Issue: {case['matched_issue_id']}")
            print(f"   匹配标题: {case['matched_title'][:70]}")
            print(f"   相似度: {case['similarity']:.3f}")
        
        # 保存结果
        low_sim_ids = list(set([case['instance_id'] for case in low_similarity_cases]))
        
        with open('low_similarity_instance_ids.txt', 'w') as f:
            for instance_id in sorted(low_sim_ids):
                f.write(f"{instance_id}\n")
        
        print(f"\n✓ 低相似度 instance_id 已保存到: low_similarity_instance_ids.txt")
        print(f"  （共 {len(low_sim_ids)} 个唯一实例）")
        
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
    else:
        print(f"\n✓ 所有非 Django 实例的匹配相似度都 >= {SIMILARITY_THRESHOLD}")
    
    print("\n" + "=" * 80)
    print("完成！")
    print("\n💡 说明:")
    print("  - Django 实例使用本地 CSV 匹配，已跳过")
    print("  - 非 Django 实例通过 GitHub API 匹配，已分析")
    print("  - 低相似度案例可能需要人工审查")

if __name__ == "__main__":
    main()

