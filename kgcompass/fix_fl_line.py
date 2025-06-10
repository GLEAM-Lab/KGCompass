import json
import os
from github import Github
import sys
from utils import get_commit_file, get_class_and_method_from_content
from datasets import load_dataset
from pathlib import Path
import traceback
from config import GITHUB_TOKEN, DATASET_NAME

g = Github(GITHUB_TOKEN)
ds = load_dataset(DATASET_NAME)

def find_entity_in_content(entity_type, entity, content, repo_name):
    found = False
    start_line = end_line = None
    source_code = None
    
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

def fix_line_numbers(result_file, output_dir):
    with open(result_file, 'r') as f:
        result = json.load(f)
    instance_id = os.path.basename(result_file).replace('-result.json', '')
    instance_parts = instance_id.split('-')
    repo_name = '-'.join(instance_parts[:-1]).replace('__', '/')
    repo = g.get_repo(repo_name)
    base_commit = None
    for item in ds['test']:
        if item['instance_id'] == instance_id:
            base_commit = item['base_commit']
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
                if file_path.startswith('../'):
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
    
    output_file = os.path.join(output_dir, os.path.basename(result_file))
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"Saved processed results to: {output_file}")

def process_all_results():
    input_dir = sys.argv[1]
    output_dir = sys.argv[2]
    os.makedirs(output_dir, exist_ok=True)
    result_files = list(Path(input_dir).glob('*-result.json'))
    unprocessed_files = [
        f for f in result_files 
        if not os.path.exists(os.path.join(output_dir, os.path.basename(f)))
    ]
    total_files = len(unprocessed_files)
    print(f"Found {len(result_files)} result files, of which {total_files} need to be processed")

    instance_ids = set([item['instance_id'] for item in ds['test']])
    print(f"Found {len(instance_ids)} instances")
    
    for i, result_file in enumerate(unprocessed_files, 1):
        instance_id = str(result_file).split('/')[1][:-12]
        if instance_id not in instance_ids:
            continue
        print(f"\n[{i}/{total_files}] Processing file: {result_file}")
        try:
            fix_line_numbers(str(result_file), output_dir)
        except Exception as e:
            print(f"Error processing file {result_file}:")
            print(traceback.format_exc())
            continue
    
    print("\nAll files processed!")

if __name__ == "__main__":
    process_all_results()
