#!/usr/bin/env python3
"""
从日志文件中提取所有实例的 issue 匹配信息
然后与 benchmark 中的标题比较，找出低相似度的案例
"""

import re
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

def extract_title_from_problem_statement(problem_statement):
    """提取标题"""
    return problem_statement.split('\n')[0].strip()

def parse_log_file(log_path):
    """从单个日志文件中提取 issue 匹配信息"""
    current_instance = None
    current_expected_title = None
    matches = []
    
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            
        for i, line in enumerate(lines):
            # 匹配 instance_id
            instance_match = re.search(r'Instance ID: ([^\s]+)', line)
            if instance_match:
                current_instance = instance_match.group(1)
                continue
            
            # 匹配预期标题
            title_match = re.search(r'Extracted title from problem description: (.+)$', line)
            if title_match:
                current_expected_title = title_match.group(1).strip()
                continue
            
            # 匹配找到的 best match
            best_match = re.search(r'Found best match (?:PR|Issue) #(\d+), similarity: ([\d.]+)', line)
            if best_match and current_instance:
                issue_num = best_match.group(1)
                similarity = float(best_match.group(2))
                
                # 获取下一行的标题
                matched_title = None
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and not next_line.startswith('[') and not next_line.startswith('======'):
                        matched_title = next_line
                
                matches.append({
                    'instance_id': current_instance,
                    'expected_title': current_expected_title,
                    'matched_issue': issue_num,
                    'matched_title': matched_title,
                    'similarity': similarity
                })
    except Exception as e:
        print(f"  ⚠️  解析 {log_path.name} 失败: {e}")
    
    return matches

def main():
    print("=" * 80)
    print("从日志提取 Issue 匹配信息并分析")
    print("=" * 80)
    
    SIMILARITY_THRESHOLD = 0.9
    
    # 1. 加载数据集
    print("\n[1/4] 加载 SWE-bench Verified 数据集...")
    try:
        ds = load_dataset("princeton-nlp/SWE-bench_Verified", split='test')
        instance_map = {item['instance_id']: item for item in ds}
        print(f"✓ 加载成功，共 {len(ds)} 个实例")
    except Exception as e:
        print(f"✗ 加载失败: {e}")
        print("将只使用日志中的信息")
        instance_map = {}
    
    # 2. 扫描日志目录
    print("\n[2/4] 扫描日志文件...")
    log_dir = Path("logs")
    
    if not log_dir.exists():
        print(f"✗ 日志目录不存在: {log_dir}")
        print("\n💡 提示: 使用 run_with_analysis.sh 运行 fl.py 会自动生成日志")
        return
    
    log_files = list(log_dir.glob("*.log"))
    print(f"✓ 找到 {len(log_files)} 个日志文件")
    
    if not log_files:
        print("\n⚠️  没有找到日志文件")
        print("\n💡 建议:")
        print("1. 使用 ./run_with_analysis.sh 运行 fl.py 会自动记录日志")
        print("2. 或手动运行: python kgcompass/fl.py ... 2>&1 | tee logs/run.log")
        return
    
    # 3. 解析所有日志
    print("\n[3/4] 解析日志文件...")
    all_matches = []
    
    for log_file in log_files:
        print(f"  处理: {log_file.name}")
        matches = parse_log_file(log_file)
        all_matches.extend(matches)
    
    print(f"✓ 共提取 {len(all_matches)} 条匹配记录")
    
    # 4. 分析相似度
    print(f"\n[4/4] 分析匹配质量（阈值: {SIMILARITY_THRESHOLD}）...")
    
    low_similarity_cases = []
    django_cases = []
    non_django_cases = []
    
    for match in all_matches:
        instance_id = match['instance_id']
        
        # 从数据集获取仓库信息
        repo = 'unknown'
        if instance_id in instance_map:
            repo = instance_map[instance_id]['repo']
        
        match['repo'] = repo
        
        # 分类
        if repo == 'django/django':
            django_cases.append(match)
        else:
            non_django_cases.append(match)
        
        # 检查相似度（只检查非 Django）
        if repo != 'django/django' and match['similarity'] < SIMILARITY_THRESHOLD:
            low_similarity_cases.append(match)
    
    # 输出结果
    print("\n" + "=" * 80)
    print("📊 分析结果:")
    print(f"  - 总匹配记录: {len(all_matches)}")
    print(f"  - Django 实例: {len(django_cases)} （跳过检查）")
    print(f"  - 非 Django 实例: {len(non_django_cases)}")
    print(f"  - 低相似度案例（非 Django）: {len(low_similarity_cases)}")
    print("=" * 80)
    
    if low_similarity_cases:
        print(f"\n🔴 低相似度匹配案例（< {SIMILARITY_THRESHOLD}）：")
        print("=" * 80)
        
        # 按相似度排序
        low_similarity_cases.sort(key=lambda x: x['similarity'])
        
        for i, case in enumerate(low_similarity_cases, 1):
            print(f"\n{i}. {case['instance_id']}")
            print(f"   仓库: {case['repo']}")
            print(f"   预期标题: {case.get('expected_title', 'N/A')[:70]}")
            print(f"   匹配 Issue: #{case['matched_issue']}")
            print(f"   匹配标题: {case.get('matched_title', 'N/A')[:70]}")
            print(f"   相似度: {case['similarity']:.3f}")
        
        # 保存结果
        low_sim_ids = [case['instance_id'] for case in low_similarity_cases]
        
        with open('low_similarity_instance_ids.txt', 'w') as f:
            for instance_id in low_sim_ids:
                f.write(f"{instance_id}\n")
        
        print(f"\n✓ 低相似度 instance_id 已保存到: low_similarity_instance_ids.txt")
        
        with open('low_similarity_matches_from_logs.json', 'w', encoding='utf-8') as f:
            json.dump(low_similarity_cases, f, indent=2, ensure_ascii=False)
        
        print(f"✓ 详细信息已保存到: low_similarity_matches_from_logs.json")
        
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
    
    # 保存所有匹配信息（包括 Django）
    with open('all_matches_from_logs.json', 'w', encoding='utf-8') as f:
        json.dump(all_matches, f, indent=2, ensure_ascii=False)
    
    print(f"\n✓ 所有匹配信息已保存到: all_matches_from_logs.json")
    
    print("\n" + "=" * 80)
    print("完成！")

if __name__ == "__main__":
    main()


