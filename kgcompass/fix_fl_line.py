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
from benchmark import create_benchmark_manager

g = Github(GITHUB_TOKEN)

def load_dataset_for_instance(instance_id, benchmark_type="swe-bench"):
    """使用 benchmark 管理器加载数据集"""
    try:
        benchmark_manager = create_benchmark_manager(benchmark_type)
        instances = benchmark_manager.load_dataset_instances()
        
        for instance in instances:
            if instance.get('instance_id') == instance_id:
                print(f"Found instance {instance_id} using benchmark manager")
                return {'test': [instance]}
        
        print(f"Instance {instance_id} not found in benchmark dataset")
        return None
        
    except Exception as e:
        print(f"Error loading dataset using benchmark manager: {e}")
        
        # 回退到原有逻辑
        # 首先尝试从本地 swe-bench_java 目录加载（针对 Java 实例）
        local_data_dir = Path("swe-bench_java")
        
        if local_data_dir.exists() and instance_id:
            # 提取仓库名称
            repo_name = instance_id.rsplit('-', 1)[0]
            
            # 查找对应的 JSONL 文件
            for jsonl_file in local_data_dir.glob("*.jsonl"):
                if repo_name in jsonl_file.name:
                    print(f"Loading from local JSONL file: {jsonl_file}")
                    try:
                        with open(jsonl_file, 'r') as f:
                            for line in f:
                                item = json.loads(line.strip())
                                if item.get('instance_id') == instance_id:
                                    print(f"Found instance {instance_id} in local file")
                                    return {'test': [item]}
                    except Exception as e:
                        print(f"Error reading local file {jsonl_file}: {e}")
                        continue
        
        # 如果本地没找到，尝试从 Hugging Face 加载
        try:
            return load_dataset(DATASET_NAME)
        except Exception as e:
            print(f"Error loading from Hugging Face: {e}")
            return None

def find_entity_in_content(entity_type, entity, content, repo_name):
    found = False
    start_line = end_line = None
    source_code = None
    
    # 对于Java文件，直接使用已有的位置信息，不重新解析
    if entity['file_path'].endswith('.java'):
        print(f"🔧 Using existing location info for Java file: {entity['file_path']}")
        # 验证行号是否在文件范围内
        content_lines = content.splitlines()
        if (entity.get('start_line', 1) > 0 and 
            entity.get('end_line', 1) <= len(content_lines) and
            entity.get('start_line', 1) <= entity.get('end_line', 1)):
            start_line = entity['start_line']
            end_line = entity['end_line']
            source_code = '\n'.join(content_lines[start_line-1:end_line])
            found = True
            print(f"✅ Validated Java entity {entity['name']} at lines {start_line}-{end_line}")
        else:
            print(f"⚠️ Invalid line numbers for {entity['name']}: {entity.get('start_line')}-{entity.get('end_line')} (file has {len(content_lines)} lines)")
        return found, start_line, end_line, source_code
    
    # 对于非Java文件，使用原有的AST解析逻辑
    classes, methods = get_class_and_method_from_content(content, entity['file_path'], repo_name.split('/')[-1])
    
    if entity_type == 'classes':
        for class_info in classes:
            if class_info['name'] == entity['name']:
                start_line = class_info['start_line']
                end_line = class_info['end_line']
                source_code = '\n'.join(content.splitlines()[start_line-1:end_line])
                found = True
                break
    else:  
        for method in methods:
            if method['name'] == entity['name']:
                start_line = method['start_line']
                end_line = method['end_line']
                source_code = '\n'.join(content.splitlines()[start_line-1:end_line])
                found = True
                break
    return found, start_line, end_line, source_code

def fix_line_numbers(result_file, output_dir, instance_id, benchmark_type="swe-bench"):
    with open(result_file, 'r') as f:
        result = json.load(f)

    # instance_id is now passed as an argument
    instance_parts = instance_id.split('-')
    repo_name = '-'.join(instance_parts[:-1]).replace('__', '/')
    repo = g.get_repo(repo_name)
    
    # 加载数据集来获取 base_commit
    ds = load_dataset_for_instance(instance_id, benchmark_type)
    if not ds:
        print(f"Could not load dataset for instance {instance_id}")
        return
        
    base_commit = None
    for item in ds['test']:
        if item['instance_id'] == instance_id:
            # 支持不同的字段名格式
            if 'base_commit' in item:
                base_commit = item['base_commit']
            elif 'base' in item and isinstance(item['base'], dict) and 'sha' in item['base']:
                base_commit = item['base']['sha']
            break
    if not base_commit:
        print(f"Not found base_commit of instance {instance_id}")
        return
    print(f"Found base_commit: {base_commit}")

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
                file_path = entity['file_path']
                if file_path.startswith('playground/'):
                    file_path = '/'.join(file_path.split('/')[2:])
                
                file_content = get_commit_file(repo, repo.get_commit(base_commit), file_path)
                if not file_content:
                    print(f"Not found file {file_path} in commit {base_commit}")
                    continue
                print(f'Found file {file_path} in commit {base_commit}')

                directory = os.path.dirname(entity['file_path'])
                if directory:
                    os.makedirs(directory, exist_ok=True)
                with open(entity['file_path'], 'w', encoding='utf-8') as f:
                    f.write(file_content)

                found, start_line, end_line, source_code = find_entity_in_content(
                    entity_type, entity, file_content, repo_name
                )
                
                if not found:
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
                    if start_line != entity['start_line'] or end_line != entity['end_line']:
                        print(f"Found entity {entity['name']} and fixed line numbers: {start_line} - {end_line}")
                    entity['start_line'] = start_line
                    entity['end_line'] = end_line
                    entity['source_code'] = source_code
                    entity['path'] = entity_path[entity['name']]
                    valid_entities.append(entity)
                    appear[entity['signature']] = True
                else:
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
    parser.add_argument("--benchmark", type=str, default="swe-bench", 
                        help="Benchmark type (swe-bench or multi-swe-bench)")
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
    print(f"Using benchmark: {args.benchmark}")
    
    try:
        fix_line_numbers(input_file, args.output_dir, args.instance_id, args.benchmark)
    except Exception as e:
        print(f"An error occurred while processing {input_file}:")
        print(traceback.format_exc())
        sys.exit(1)
    
    print(f"\n✅ Final location saved to {Path(args.output_dir) / f'{args.instance_id}.json'}")
