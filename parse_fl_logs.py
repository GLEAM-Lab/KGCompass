#!/usr/bin/env python3
"""
从 fl.py 运行日志中解析 issue 匹配信息
用法: python parse_fl_logs.py <log_file>
"""

import re
import sys
import json

def parse_log_file(log_path):
    """解析日志文件，提取 issue 匹配信息"""
    
    matches = []
    current_instance = None
    current_expected_title = None
    
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
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
                
                # 下一行应该包含标题
                matches.append({
                    'instance_id': current_instance,
                    'expected_title': current_expected_title,
                    'matched_issue': issue_num,
                    'similarity': similarity,
                    'pending_title': True  # 标记等待下一行的标题
                })
                continue
            
            # 匹配 issue 标题（通常在 "Found best match" 的下一行）
            if matches and matches[-1].get('pending_title'):
                # 去除前导空格和特殊字符
                title_line = line.strip()
                if title_line and not title_line.startswith('['):
                    matches[-1]['matched_title'] = title_line
                    matches[-1].pop('pending_title')
    
    return matches

def main():
    if len(sys.argv) < 2:
        print("用法: python parse_fl_logs.py <log_file>")
        print("\n示例:")
        print("  # 运行并记录日志:")
        print("  python kgcompass/fl.py instance_id repo_path output_dir 2>&1 | tee run.log")
        print("  # 解析日志:")
        print("  python parse_fl_logs.py run.log")
        sys.exit(1)
    
    log_file = sys.argv[1]
    
    print(f"解析日志文件: {log_file}")
    matches = parse_log_file(log_file)
    
    print(f"\n找到 {len(matches)} 个 issue 匹配记录\n")
    
    # 按相似度排序
    matches.sort(key=lambda x: x['similarity'])
    
    # 设置相似度阈值
    THRESHOLD = 0.5
    low_similarity = [m for m in matches if m['similarity'] < THRESHOLD]
    
    if low_similarity:
        print(f"低相似度匹配（< {THRESHOLD}）：{len(low_similarity)} 个\n")
        print("=" * 100)
        
        for i, match in enumerate(low_similarity, 1):
            print(f"\n{i}. {match['instance_id']}")
            print(f"   预期标题: {match.get('expected_title', 'N/A')}")
            print(f"   匹配 Issue: #{match['matched_issue']}")
            print(f"   匹配标题: {match.get('matched_title', 'N/A')}")
            print(f"   相似度: {match['similarity']:.3f}")
    else:
        print(f"所有匹配的相似度都 >= {THRESHOLD}")
    
    # 保存结果
    output_file = "parsed_issue_matches.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(matches, f, indent=2, ensure_ascii=False)
    print(f"\n完整结果已保存到: {output_file}")
    
    # 统计信息
    print(f"\n统计信息:")
    print(f"  总匹配数: {len(matches)}")
    print(f"  低相似度 (< {THRESHOLD}): {len(low_similarity)}")
    if matches:
        avg_similarity = sum(m['similarity'] for m in matches) / len(matches)
        print(f"  平均相似度: {avg_similarity:.3f}")
        print(f"  最低相似度: {min(m['similarity'] for m in matches):.3f}")
        print(f"  最高相似度: {max(m['similarity'] for m in matches):.3f}")

if __name__ == "__main__":
    main()


