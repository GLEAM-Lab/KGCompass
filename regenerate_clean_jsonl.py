#!/usr/bin/env python3
"""重新生成干净的patch JSONL文件，只包含org/repo/number/fix_patch字段"""

import os
import json
import glob

def parse_instance_id(instance_id):
    """从instance_id解析org、repo、number"""
    try:
        # 格式: org__repo-number 例如: google__gson-1787
        if '__' in instance_id and '-' in instance_id:
            org_repo, number = instance_id.rsplit('-', 1)
            org, repo = org_repo.split('__', 1)
            return org, repo, number
        else:
            # 回退处理
            parts = instance_id.replace('__', '_').split('-')
            if len(parts) >= 2:
                return parts[0], parts[1] if len(parts) > 2 else "", parts[-1]
            else:
                return "", "", instance_id
    except Exception:
        return "", "", instance_id

def combine_diff_patches(processed_patches):
    """合并所有diff patches为单个patch"""
    if not processed_patches:
        return ""
    
    combined_diff = ""
    for patch_info in processed_patches:
        diff_content = patch_info.get("diff_content", "")
        if diff_content:
            combined_diff += diff_content + "\n"
    
    return combined_diff.strip()

def process_jsonl_files():
    """处理所有现有的patch_results.jsonl文件"""
    clean_results = []
    
    # 查找所有patch_results.jsonl文件
    jsonl_files = glob.glob("tests_java/*/patches/patch_results.jsonl")
    
    print(f"📁 找到 {len(jsonl_files)} 个JSONL文件")
    
    for jsonl_file in jsonl_files:
        print(f"🔄 处理: {jsonl_file}")
        
        try:
            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line.strip())
                        
                        # 解析字段
                        instance_id = data.get("instance_id", "")
                        org, repo, number = parse_instance_id(instance_id)
                        
                        # 合并diff patches
                        processed_patches = data.get("processed_patches", [])
                        fix_patch = combine_diff_patches(processed_patches)
                        
                        # 只保存有实际patch内容的结果
                        if fix_patch.strip():
                            clean_result = {
                                "org": org,
                                "repo": repo,
                                "number": number,
                                "fix_patch": fix_patch
                            }
                            clean_results.append(clean_result)
                            print(f"✅ 提取成功: {org}__{repo}-{number}")
                        else:
                            print(f"⚠️  无patch内容: {instance_id}")
                            
        except Exception as e:
            print(f"❌ 处理失败 {jsonl_file}: {e}")
    
    return clean_results

def update_individual_files(clean_results):
    """更新各个目录中的patch_results.jsonl文件为干净格式"""
    result_by_instance = {}
    for result in clean_results:
        instance_id = f"{result['org']}__{result['repo']}-{result['number']}"
        result_by_instance[instance_id] = result
    
    jsonl_files = glob.glob("tests_java/*/patches/patch_results.jsonl")
    
    for jsonl_file in jsonl_files:
        # 从路径提取instance_id
        dir_name = os.path.basename(os.path.dirname(os.path.dirname(jsonl_file)))
        instance_id = dir_name.replace('_deepseek', '')
        
        if instance_id in result_by_instance:
            clean_result = result_by_instance[instance_id]
            
            # 重写文件为干净格式
            with open(jsonl_file, 'w', encoding='utf-8') as f:
                f.write(json.dumps(clean_result, ensure_ascii=False) + '\n')
            
            print(f"🔄 更新: {jsonl_file}")

def main():
    print("=== 重新生成干净的Patch JSONL文件 ===\n")
    
    # 处理现有文件
    clean_results = process_jsonl_files()
    
    print(f"\n📊 统计信息:")
    print(f"   总处理: {len(clean_results)} 个有效patch")
    
    if clean_results:
        # 更新各个目录中的文件
        update_individual_files(clean_results)
        
        print(f"\n✅ 完成！所有JSONL文件已更新为标准格式")
        print(f"   格式: {{\"org\": \"...\", \"repo\": \"...\", \"number\": \"...\", \"fix_patch\": \"...\"}}")
    else:
        print("\n⚠️  未找到有效的patch内容")

if __name__ == "__main__":
    main() 