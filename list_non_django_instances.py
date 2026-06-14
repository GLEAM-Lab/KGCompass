#!/usr/bin/env python3
"""
简单脚本：列出所有非 Django 的 SWE-bench Verified 实例
这些实例才需要检查 issue 匹配质量（Django 用的是本地 CSV，不需要检查）
"""

import json
from pathlib import Path
from datasets import load_dataset

def main():
    print("=" * 80)
    print("查找所有非 Django 的 SWE-bench Verified 实例")
    print("=" * 80)
    
    # 加载数据集
    print("\n加载 SWE-bench Verified 数据集...")
    try:
        ds = load_dataset("princeton-nlp/SWE-bench_Verified", split='test')
        print(f"✓ 加载成功，共 {len(ds)} 个实例\n")
    except Exception as e:
        print(f"✗ 加载失败: {e}")
        return
    
    # 查找有结果文件的实例
    results_base_dir = Path("runs/kg_verified")
    if not results_base_dir.exists():
        print(f"✗ 结果目录不存在: {results_base_dir}")
        return
    
    # 收集所有有结果的实例
    result_instances = {}
    for repo_dir in results_base_dir.iterdir():
        if repo_dir.is_dir():
            for json_file in repo_dir.glob("*.json"):
                instance_id = json_file.stem
                result_instances[instance_id] = {
                    'repo': repo_dir.name.replace('__', '/'),
                    'path': str(json_file)
                }
    
    print(f"找到 {len(result_instances)} 个结果文件\n")
    
    # 分类
    django_instances = []
    non_django_instances = []
    
    for item in ds:
        instance_id = item['instance_id']
        repo_name = item['repo']
        
        # 只处理有结果文件的实例
        if instance_id not in result_instances:
            continue
        
        problem_statement = item.get('problem_statement', '')
        title = problem_statement.split('\n')[0].strip()
        
        instance_info = {
            'instance_id': instance_id,
            'repo': repo_name,
            'title': title
        }
        
        if repo_name == 'django/django':
            django_instances.append(instance_info)
        else:
            non_django_instances.append(instance_info)
    
    # 输出统计
    print("=" * 80)
    print(f"📊 统计结果:")
    print(f"  - Django 实例: {len(django_instances)} 个（使用本地 CSV，无需检查）")
    print(f"  - 非 Django 实例: {len(non_django_instances)} 个（需要检查 issue 匹配质量）")
    print("=" * 80)
    
    # 按仓库统计非 Django 实例
    if non_django_instances:
        repo_stats = {}
        for inst in non_django_instances:
            repo = inst['repo']
            repo_stats[repo] = repo_stats.get(repo, 0) + 1
        
        print(f"\n📦 非 Django 实例按仓库分布:")
        for repo, count in sorted(repo_stats.items(), key=lambda x: -x[1]):
            print(f"  - {repo}: {count} 个")
        
        # 保存非 Django 实例列表
        non_django_ids = [inst['instance_id'] for inst in non_django_instances]
        
        with open('non_django_instance_ids.txt', 'w') as f:
            for instance_id in non_django_ids:
                f.write(f"{instance_id}\n")
        
        print(f"\n✓ 非 Django instance_id 已保存到: non_django_instance_ids.txt")
        
        # 保存详细信息
        with open('non_django_instances_detail.json', 'w', encoding='utf-8') as f:
            json.dump(non_django_instances, f, indent=2, ensure_ascii=False)
        
        print(f"✓ 详细信息已保存到: non_django_instances_detail.json")
        
        # 显示示例
        print(f"\n📋 非 Django 实例示例（前 10 个）:")
        for i, inst in enumerate(non_django_instances[:10], 1):
            print(f"{i:2d}. {inst['instance_id']}")
            print(f"    仓库: {inst['repo']}")
            print(f"    标题: {inst['title'][:70]}")
            print()
        
        if len(non_django_instances) > 10:
            print(f"... 还有 {len(non_django_instances) - 10} 个")
    
    print("\n" + "=" * 80)
    print("完成！")
    print("\n💡 下一步:")
    print("1. 这些非 Django 实例需要检查 issue 匹配质量")
    print("2. 从运行日志中提取实际匹配的 issue 信息")
    print("3. 比较 benchmark 标题与匹配的 issue 标题的相似度")

if __name__ == "__main__":
    main()


