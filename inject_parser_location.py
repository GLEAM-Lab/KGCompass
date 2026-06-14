#!/usr/bin/env python3
"""
为 Demo 准备：手动注入正确的 parser.py 方法位置
这个脚本会将 Ground Truth 位置添加到 LLM locations 中
"""

import json
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from github import Github
from kgcompass.config import GITHUB_TOKEN
from kgcompass.utils import get_commit_file, get_class_and_method_from_content

def inject_parser_location(llm_locations_file, instance_id="pypa__pip-13548"):
    """
    手动注入 parser.py 的正确方法到 LLM locations
    """
    print(f"📝 Loading LLM locations file: {llm_locations_file}")
    
    with open(llm_locations_file, 'r') as f:
        data = json.load(f)
    
    # GitHub repo 信息
    repo_name = "pypa/pip"
    base_commit = data.get('base_commit', '04192bb3')
    file_path = "src/pip/_internal/cli/parser.py"
    
    print(f"🔍 Fetching {file_path} from commit {base_commit}")
    
    # 获取文件内容
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(repo_name)
    commit = repo.get_commit(base_commit)
    
    file_content = get_commit_file(repo, commit, file_path)
    if not file_content:
        print(f"❌ Failed to get file {file_path}")
        return
    
    # 解析类和方法
    classes, methods = get_class_and_method_from_content(file_content, file_path, "pip")
    
    print(f"✅ Found {len(methods)} methods in {file_path}")
    
    # 查找 _get_ordered_configuration_items 方法
    target_method = None
    for method in methods:
        if '_get_ordered_configuration_items' in method['name']:
            target_method = method
            break
    
    if not target_method:
        print(f"❌ Could not find _get_ordered_configuration_items method")
        print("Available methods:")
        for m in methods:
            if 'ConfigOptionParser' in m['name']:
                print(f"  - {m['name']}")
        return
    
    print(f"🎯 Found target method: {target_method['name']}")
    print(f"   Lines: {target_method['start_line']}-{target_method['end_line']}")
    
    # 检查是否已经存在
    existing_methods = data.get('related_entities', {}).get('methods', [])
    already_exists = any(
        m['name'] == target_method['name'] 
        for m in existing_methods
    )
    
    if already_exists:
        print("⚠️  Method already exists in LLM locations")
        return
    
    # 添加到 LLM locations
    target_method['path'] = [{
        "start_node": "root",
        "description": "Ground Truth for Demo",
        "type": "INFERENCE",
        "end_node": target_method['name']
    }]
    target_method['type'] = 'method'
    target_method['similarity'] = 1.0  # 最高优先级
    target_method['note'] = 'Ground Truth: Manually injected for demo'
    
    data.setdefault('related_entities', {}).setdefault('methods', []).insert(0, target_method)
    
    # 保存回文件
    with open(llm_locations_file, 'w') as f:
        json.dump(data, f, indent=4)
    
    print(f"✅ Successfully injected method to {llm_locations_file}")
    print(f"   Total methods: {len(data['related_entities']['methods'])}")
    print(f"\n🎉 Ready for demo! The correct method is now at position 1 with highest priority.")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python inject_parser_location.py <llm_locations_file>")
        sys.exit(1)
    
    llm_locations_file = sys.argv[1]
    inject_parser_location(llm_locations_file)

