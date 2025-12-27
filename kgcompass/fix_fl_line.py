import json
import os
from github import Github
import sys
import argparse
from utils import get_commit_file, get_class_and_method_from_content
from datasets import load_dataset
from pathlib import Path
import traceback
from config import GITHUB_TOKEN, DATASET_NAME
import glob

g = Github(GITHUB_TOKEN)

# 延迟加载数据集，避免自定义仓库时不必要的加载
ds = None
def _load_dataset_if_needed():
    global ds
    if ds is None:
        try:
            ds = load_dataset(DATASET_NAME)
        except Exception as e:
            print(f"Warning: Could not load dataset {DATASET_NAME}: {e}")
            ds = {}
    return ds

def find_entity_in_content(entity_type, entity, content, repo_name):
    found = False
    start_line = end_line = None
    source_code = None
    
    classes, methods = get_class_and_method_from_content(content, entity['file_path'], repo_name.split('/')[-1])
    
    # 提取实体名称的各种可能形式
    entity_name = entity['name']
    entity_name_variations = [entity_name]
    
    # 如果是完整限定名（如 src.pip._internal.vcs.git.Git.has_commit），
    # 添加其他可能的匹配形式
    if '.' in entity_name:
        parts = entity_name.split('.')
        # 添加最后一部分（方法名）
        entity_name_variations.append(parts[-1])
        # 添加最后两部分（类.方法）
        if len(parts) >= 2:
            entity_name_variations.append('.'.join(parts[-2:]))
        # 添加最后三部分（模块.类.方法）
        if len(parts) >= 3:
            entity_name_variations.append('.'.join(parts[-3:]))
    
    if entity_type == 'classes':
        for class_info in classes:
            # 尝试匹配任何一种名称形式
            if any(class_info['name'] == name or class_info['name'].endswith('.' + name) 
                   for name in entity_name_variations):
                start_line = class_info['start_line']
                end_line = class_info['end_line']
                source_code = '\n'.join(content.splitlines()[start_line-1:end_line])
                found = True
                break
    else:  
        for method in methods:
            # 尝试匹配任何一种名称形式
            # 方法的 name 可能是完整的，也可能只是部分的
            if (method['name'] == entity_name or 
                method['name'] in entity_name_variations or
                entity_name.endswith('.' + method['name']) or
                any(method['name'] == var or method['name'].endswith('.' + var) 
                    for var in entity_name_variations)):
                start_line = method['start_line']
                end_line = method['end_line']
                source_code = '\n'.join(content.splitlines()[start_line-1:end_line])
                found = True
                break
    
    return found, start_line, end_line, source_code

def fix_line_numbers(result_file, output_dir, instance_id):
    with open(result_file, 'r') as f:
        result = json.load(f)

    # instance_id is now passed as an argument
    instance_parts = instance_id.rsplit('-', 1)  # 从右边分割，处理仓库名中的连字符
    repo_name = instance_parts[0].replace('__', '/')
    repo = g.get_repo(repo_name)
    
    # 尝试多种方式获取 base_commit
    base_commit = None
    
    # 方法 1: 从 web_outputs 的实例文件加载
    instance_files = glob.glob(f"web_outputs/*/{instance_id}_instance.json")
    if instance_files:
        try:
            with open(instance_files[0], 'r') as f:
                instance_data = json.load(f)
            base_commit = instance_data.get('base_commit', 'HEAD')
            print(f"Loaded base_commit from instance file: {base_commit}")
        except Exception as e:
            print(f"Error loading from instance file: {e}")
    
    # 方法 2: 从数据集加载（如果是 SWE-bench 实例）
    if not base_commit or base_commit == 'HEAD':
        ds = _load_dataset_if_needed()
        if ds and 'test' in ds:
            for item in ds['test']:
                if item['instance_id'] == instance_id:
                    base_commit = item['base_commit']
                    print(f"Loaded base_commit from dataset: {base_commit}")
                    break
    
    # 方法 3: 使用 HEAD（默认，适用于自定义仓库）
    if not base_commit or base_commit == 'HEAD':
        print(f"Using default branch HEAD as base_commit for custom repository")
        try:
            # 获取仓库的默认分支的最新 commit
            default_branch = repo.default_branch
            base_commit = repo.get_branch(default_branch).commit.sha
            print(f"Resolved HEAD to: {base_commit}")
        except Exception as e:
            print(f"Error getting default branch commit: {e}")
            return
    
    print(f"Using base_commit: {base_commit}")

    for entity_type in ['methods']:
        if entity_type not in result['related_entities']:
            continue
            
        entities = result['related_entities'][entity_type]
        entities = sorted(enumerate(entities), key=lambda x: (-x[1]['similarity'], x[0]))
        entities = [entity for _, entity in entities]
        valid_entities = []
        entity_path = {}
        appear = {}
        for entity in entities:
            if entity['similarity'] > 0.99:
                entity['path'][0]['type'] = 'INFERENCE'
            entity_path[entity['name']] = entity['path']
        for entity in entities:
            try:
                # 检查 KG 分析时的 commit 和当前 base_commit 是否一致
                # 如果一致，且已有 source_code，可以直接使用
                # 否则需要从 GitHub API 重新获取以确保版本一致
                
                file_path = entity['file_path']
                if file_path.startswith('playground/'):
                    file_path = '/'.join(file_path.split('/')[2:])
                
                # 尝试从 GitHub API 获取指定 commit 的文件内容
                file_content = get_commit_file(repo, repo.get_commit(base_commit), file_path)
                if not file_content:
                    print(f"Not found file {file_path} in commit {base_commit}")
                    # 如果文件不存在于该 commit，可能是：
                    # 1. 文件路径错误
                    # 2. 该文件在该 commit 时还不存在
                    # 无论如何，这个实体都不应该被包含
                    continue
                    
                print(f'Found file {file_path} in commit {base_commit}')

                # 保存文件内容到本地以供后续处理
                directory = os.path.dirname(entity['file_path'])
                if directory:
                    os.makedirs(directory, exist_ok=True)
                with open(entity['file_path'], 'w', encoding='utf-8') as f:
                    f.write(file_content)

                # 在该 commit 的文件内容中查找实体
                found, start_line, end_line, source_code = find_entity_in_content(
                    entity_type, entity, file_content, repo_name
                )
                
                if not found:
                    # 尝试修改名称格式再查找
                    original_name = entity['name']
                    parts = original_name.split('.')
                    
                    if len(parts) > 2 and parts[0] == parts[1]:
                        new_name = '.'.join(parts[1:])
                        entity['name'] = new_name
                        print(f"Try using modified name: {new_name}")
                        
                        found, start_line, end_line, source_code = find_entity_in_content(
                            entity_type, entity, file_content, repo_name
                        )
                
                if found and entity['signature'] not in appear:
                    # 成功在指定 commit 中找到实体，更新信息
                    if start_line != entity['start_line'] or end_line != entity['end_line']:
                        print(f"Found entity {entity['name']} and fixed line numbers: {start_line} - {end_line}")
                    entity['start_line'] = start_line
                    entity['end_line'] = end_line
                    entity['source_code'] = source_code
                    entity['path'] = entity_path.get(entity['name'], entity.get('path', []))
                    valid_entities.append(entity)
                    appear[entity['signature']] = True
                else:
                    # 在该 commit 中找不到该实体
                    # 这说明该方法在该 commit 时不存在或名称不匹配
                    # 不应该包含这个实体，以确保版本一致性
                    print(f"Not found source code of entity {entity['name']} in commit {base_commit} of file {file_path}")
            
            except Exception as e:
                print(f"Error processing entity {entity['name']}:")
                print(traceback.format_exc())
                continue
        
        result['related_entities'][entity_type] = valid_entities
    
    output_file = os.path.join(output_dir, f"{instance_id}.json")
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"Saved processed results to: {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fix line numbers and other info in an LLM-generated location file for a specific instance.")
    parser.add_argument("input_dir", type=str, help="Directory containing the LLM-generated location file.")
    parser.add_argument("output_dir", type=str, help="Directory to save the fixed location file.")
    parser.add_argument("--instance_id", type=str, required=True, help="The instance_id to process.")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    
    input_file = Path(args.input_dir) / f"{args.instance_id}.json"
    if not input_file.exists():
        # Fallback for old format
        old_format_file = Path(args.input_dir) / f"{args.instance_id}-result.json"
        if old_format_file.exists():
            input_file = old_format_file
        else:
            print(f"Error: Input file for instance '{args.instance_id}' not found at '{input_file}' or as '*-result.json'.")
            sys.exit(1)

    print(f"Processing file: {input_file}")
    
    try:
        fix_line_numbers(input_file, args.output_dir, args.instance_id)
    except Exception as e:
        print(f"An error occurred while processing {input_file}:")
        print(traceback.format_exc())
        sys.exit(1)
    
    print(f"\n✅ Final location saved to {Path(args.output_dir) / f'{args.instance_id}.json'}")
