"""
Code Repair Script with Multi-API Support

This script supports multiple LLM APIs including OpenAI, Anthropic Claude, DeepSeek, and Qwen.

Usage examples:
    # Using Claude
    python repair_claude.py final_locations --instance_id test-123 --api_type anthropic --temperature 0.5
    
    # Using OpenAI GPT-4
    python repair_claude.py final_locations --instance_id test-123 --api_type openai --temperature 0.3
    
    # Using DeepSeek (default)
    python repair_claude.py final_locations --instance_id test-123 --api_type deepseek
    
    # For Java projects
    python repair_claude.py final_locations --instance_id test-123 --language java --api_type anthropic

Environment variables needed:
    - CLAUDE_API_KEY: For Anthropic Claude API
    - OPENAI_API_KEY: For OpenAI API
    - DEEPSEEK_API_KEY or BAILIAN_API_KEY: For DeepSeek API
    - QWEN_API_KEY: For Qwen API
"""

import os
import json
import openai
import anthropic
import tiktoken
import difflib
import subprocess
from datetime import datetime
from config import (
    BAILIAN_API_KEY,
    MODEL_NAME,
    MAX_INPUT_LENGTH,
    TEMPERATURE,
    TOP_P,
    DEEPSEEK_BASE_URL,
)
import argparse
from utils import (
    format_entity_content,
    extract_python_blocks,
    split_edit_multifile_commands,
    parse_diff_edit_commands_strict,
    check_syntax,
    applable_patch,
)
from benchmark import create_benchmark_manager

# API Configuration
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") or BAILIAN_API_KEY
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

# Model Configuration
LLM_MODELS = {
    'openai': 'gpt-4o',
    'deepseek': 'deepseek-v3',
    'anthropic': 'claude-3-5-sonnet-20241022',
    'qwen': 'qwen-max-2025-01-25',
}

# Token limits
MAX_INPUT_LENGTH_CONFIG = {
    'openai': 120000,
    'anthropic': 190000,
    'deepseek': 60000,
    'qwen': 30000,
}

MAX_TOKENS = 8192


def load_instance_from_dataset(instance_id, benchmark_type="multi-swe-bench"):
    """从数据集加载实例信息，获取repo和commit信息"""
    try:
        # 对于Java项目，优先从本地加载
        if benchmark_type == "multi-swe-bench":
            from pathlib import Path
            local_data_dir = Path("swe-bench_java")
            
            if local_data_dir.exists():
                # 提取仓库名称
                repo_identifier = instance_id.rsplit('-', 1)[0]
                
                # 查找对应的 JSONL 文件
                for jsonl_file in local_data_dir.glob("*_dataset.jsonl"):
                    # 直接检查repo_identifier是否在文件名中
                    if repo_identifier in jsonl_file.name or repo_identifier.replace('__', '_') in jsonl_file.name:
                        try:
                            with open(jsonl_file, 'r', encoding='utf-8') as f:
                                for line in f:
                                    try:
                                        item = json.loads(line.strip())
                                        # 生成 instance_id（如果没有的话）
                                        if 'instance_id' not in item:
                                            org = item.get('org', '')
                                            repo = item.get('repo', '')
                                            number = item.get('number', '')
                                            item['instance_id'] = f"{org}__{repo}-{number}"
                                        
                                        if item.get('instance_id') == instance_id:
                                            # 构建完整的repo名称
                                            org = item.get('org', '')
                                            repo = item.get('repo', '')
                                            repo_name = f"{org}/{repo}" if org and repo else ''
                                            
                                            # 获取commit信息
                                            commit_id = ''
                                            if 'base' in item and isinstance(item['base'], dict):
                                                commit_id = item['base'].get('sha', '')
                                            
                                            return {
                                                'repo_name': repo_name,
                                                'commit_id': commit_id,
                                                'data': item
                                            }
                                    except json.JSONDecodeError:
                                        continue
                        except Exception as e:
                            print(f"Error reading {jsonl_file}: {e}")
                            continue
        
        print(f"Instance {instance_id} not found in dataset")
        return None
        
    except Exception as e:
        print(f"Error loading dataset: {e}")
        return None

BASE_PROMPT_TEMPLATE = """
We are currently solving the following issue within our repository. Here is the issue text:
--- BEGIN ISSUE ---
{problem_statement}
--- END ISSUE ---

Below are some code segments, each from a relevant file. One or more of these files may contain bugs.
--- BEGIN FILE ---
```
{content}
```
--- END FILE ---

Please first localize the bug based on the issue statement, and then generate *SEARCH/REPLACE* edits to fix the issue.

Every *SEARCH/REPLACE* edit must use this format:
1. The file path (e.g., {file_path_example})
2. The start of search block: <<<<<<< SEARCH
3. A contiguous chunk of lines to search for in the existing source code
4. The dividing line: =======
5. The lines to replace into the source code
6. The end of the replace block: >>>>>>> REPLACE
7. Line numbers start from 1 (not 0)

Here is an example for {language_name}:

{code_example}

IMPORTANT NOTES:
1. Line numbers start from 1 (not 0)
2. The SEARCH block must match the exact content and indentation from the original file.
3. The REPLACE block must maintain proper indentation relative to the surrounding code.
4. Only include the specific lines that need to be changed.
5. If modifying a method or function, include its entire definition in both SEARCH and REPLACE blocks if it helps clarity, or at least enough context.
6. Only generate edits when actual changes are needed.
7. Verify that the replacement code is actually different from the original.

Please note that the *SEARCH/REPLACE* edit REQUIRES PROPER INDENTATION. If you would like to add a line like '        print(x)' ({language_name}), you must fully write that out, with all those spaces before the code!
Wrap the *SEARCH/REPLACE* edit in blocks ```{code_block_lang}...```.
"""


class CodeRepair:
    def __init__(self, language="python", api_type="deepseek", temperature=0.3):
        self.temperature = temperature
        self.top_p = TOP_P
        self.api_type = api_type
        self.MAX_INPUT_LENGTH = MAX_INPUT_LENGTH_CONFIG.get(api_type, MAX_INPUT_LENGTH)
        
        # Initialize API client based on type
        if api_type == "openai":
            self.client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            self.model = LLM_MODELS['openai']
        elif api_type == "anthropic":
            self.client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
            self.model = LLM_MODELS['anthropic']
        elif api_type == "deepseek":
            self.client = openai.OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
            self.model = LLM_MODELS['deepseek']
        elif api_type == "qwen":
            self.client = openai.OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
            self.model = LLM_MODELS['qwen']
        else:
            # Default to deepseek
            self.client = openai.OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
            self.model = LLM_MODELS['deepseek']
        
        # 设置语言相关配置
        self.language = language.lower()
        self._setup_language_config()
    
    def _setup_language_config(self):
        """根据语言设置相关配置"""
        if self.language == "java":
            self.language_name = "Java"
            self.file_path_example = "com/example/MyClass.java"
            self.code_block_lang = "java"
            self.code_example = """```java
### com/example/utils/StringUtils.java
- start_line : 25
- end_line : 28
<<<<<<< SEARCH
    public static boolean isEmpty(String str) {
        return str == null || str.length() == 0;
    }
=======
    public static boolean isEmpty(String str) {
        return str == null || str.trim().length() == 0;
    }
>>>>>>> REPLACE
```"""
        elif self.language == "cpp":
            self.language_name = "C++"
            self.file_path_example = "src/module/my_class.cpp"
            self.code_block_lang = "cpp"
            self.code_example = """```cpp
### src/math/calculator.cpp
- start_line : 8
- end_line : 11
<<<<<<< SEARCH
int Calculator::add(int a, int b) {
    return a - b; // Incorrect logic
}
=======
int Calculator::add(int a, int b) {
    return a + b; // Corrected logic
}
>>>>>>> REPLACE
```"""
        else:  # 默认为 python
            self.language = "python"
            self.language_name = "Python"
            self.file_path_example = "my_package/my_module.py"
            self.code_block_lang = "python"
            self.code_example = """```python
### django/core/management/commands/migrate.py
- start_line : 15
- end_line : 17
<<<<<<< SEARCH
    def my_method(self):
        result = 1 + 1
        return result
=======
    def my_method(self):
        result = 1 + 2  # Fixed the calculation
        return result
>>>>>>> REPLACE
```"""
    
    def _save_result_to_jsonl(self, result, output_dir):
        """保存结果到JSONL文件"""
        jsonl_file = os.path.join(output_dir, "patch_results.jsonl")
        
        # 从instance_id解析org、repo、number
        instance_id = result.get("instance_id", "")
        org, repo, number = self._parse_instance_id(instance_id)
        
        # 只合并成功应用的diff patches为fix_patch
        fix_patch = self._combine_applied_patches(
            result.get("processed_patches", []), 
            result.get("applied_files", [])
        )
        # 注意：只有成功应用的patch才会被保存到fix_patch字段
        
        # 创建标准格式
        standard_result = {
            "org": org,
            "repo": repo,
            "number": number,
            "fix_patch": fix_patch + '\n'
        }
        
        # 总是保存JSONL文件，即使fix_patch为空
        with open(jsonl_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(standard_result, ensure_ascii=False) + '\n')
        
        if fix_patch.strip():
            applied_count = len(result.get("applied_files", []))
            print(f"💾 结果已保存到: {jsonl_file} (包含{applied_count}个成功应用的patch)")
        else:
            print(f"💾 结果已保存到: {jsonl_file} (无成功应用的patch)")
    
    def _parse_instance_id(self, instance_id):
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
    
    def _combine_applied_patches(self, processed_patches, applied_files):
        """合并所有成功应用的diff patches为单个patch"""
        if not processed_patches or not applied_files:
            return ""
        
        combined_diff = ""
        for patch_info in processed_patches:
            # 只包含成功应用的文件的patch
            if patch_info.get("file_path") in applied_files:
                diff_content = patch_info.get("diff_content", "")
                if diff_content:
                    combined_diff += diff_content + "\n"
        
        return combined_diff.strip()

    def _check_syntax(self, code: str, language: str = "python") -> bool:
        """语言感知的语法检查器。返回True表示语法看起来有效。"""
        if language == 'python':
            return check_syntax(code)
        # 对于非Python语言，我们暂时跳过严格的语法检查
        # 可以添加对Java等其他语言的语法检查
        return True

    def _extract_java_blocks(self, text):
        """提取Java代码块"""
        import re
        pattern = r"```java\n(.*?)\n```"
        matches = re.findall(pattern, text, re.DOTALL)
        if len(matches) == 0:
            return [text]
        return matches
    
    def _extract_cpp_blocks(self, text):
        """提取C++代码块"""
        import re
        pattern = r"```cpp\n(.*?)\n```"
        matches = re.findall(pattern, text, re.DOTALL)
        if len(matches) == 0:
            # 也尝试匹配 c++ 标记
            pattern = r"```c\+\+\n(.*?)\n```"
            matches = re.findall(pattern, text, re.DOTALL)
        if len(matches) == 0:
            return [text]
        return matches

    def count_tokens(self, text):
        """计算不同 API 的 token 数量"""
        result = 0
        if self.api_type == "openai":
            # Use tiktoken to calculate token count for GPT models
            encoding = tiktoken.encoding_for_model(LLM_MODELS[self.api_type])
            result = len(encoding.encode(text))
        
        elif self.api_type == "anthropic":
            # Use Anthropic's tool to calculate token count
            try:
                response = self.client.messages.count_tokens(
                    model=LLM_MODELS[self.api_type],
                    messages=[{'role': 'user', 'content': text}],
                )
                result = response.input_tokens
            except Exception as e:
                # Fallback to tiktoken estimation
                encoding = tiktoken.encoding_for_model(LLM_MODELS['openai'])
                result = len(encoding.encode(text))
        
        elif self.api_type in ['qwen', 'deepseek']:
            # Deepseek and Qwen use GPT-like tokenizer with adjustment
            encoding = tiktoken.encoding_for_model(LLM_MODELS['openai'])
            result = int(len(encoding.encode(text)) * 1.3)
        
        return result

    def get_completion(self, prompt, stream=False):
        """统一的 LLM 调用接口"""
        messages = [{'role': 'user', 'content': prompt}]
        try:
            if self.api_type in ['openai', 'deepseek', 'qwen']:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    stream=stream,
                )
                if stream:
                    return response
                else:
                    return response.choices[0].message.content
                    
            elif self.api_type == "anthropic":
                if stream:
                    # Anthropic streaming
                    response = self.client.messages.create(
                        model=self.model,
                        max_tokens=MAX_TOKENS,
                        messages=messages,
                        temperature=self.temperature,
                        stream=True
                    )
                    return response
                else:
                    response = self.client.messages.create(
                        model=self.model,
                        max_tokens=MAX_TOKENS,
                        messages=messages,
                        temperature=self.temperature
                    )
                    return response.content[0].text
                    
        except Exception as e:
            print(f"An error occurred while calling the LLM API: {e}")
            print('Token count:', self.count_tokens(prompt))
            return None

    def adjust_command_indentation(self, command, indent_change):
        """
        统一调整编辑命令中所有行的缩进
        
        Args:
            command (dict): 包含 'command', 'start_line', 'end_line' 的编辑命令
            indent_change (int): 缩进调整量（正数增加缩进，负数减少缩进）
        """
        search_replace = command['command'].split('\n=======\n')
        search_part = search_replace[0].split('<<<<<<< SEARCH')[1].strip('\n')
        replace_part = search_replace[1].split('>>>>>>> REPLACE')[0].strip('\n')
        
        def adjust_lines(text):
            lines = text.splitlines()
            if indent_change < 0:
                # 减少缩进
                return '\n'.join(
                    line[abs(indent_change):] if line.startswith(' ' * abs(indent_change)) else line 
                    for line in lines
                )
            else:
                # 增加缩进
                return '\n'.join(' ' * indent_change + line for line in lines)
        
        adjusted_search = adjust_lines(search_part)
        adjusted_replace = adjust_lines(replace_part)
        
        return {
            'command': f"<<<<<<< SEARCH\n{adjusted_search}\n=======\n{adjusted_replace}\n>>>>>>> REPLACE",
            'start_line': command['start_line'],
            'end_line': command['end_line']
        }

    def post_process_and_apply_patch(self, instance_id, raw_output_path, locations_dir, playground_dir=None, repo_identifier=None, repo_name=None, commit_id=None):
        """
        后处理并应用patch
        """
        # 初始化处理结果
        processed_patches = []
        applied_files = []
        failed_files = []
        
        # Determine playground directory (default to sibling of locations_dir)
        if playground_dir is None:
            playground_dir = os.path.join(os.path.dirname(locations_dir), "playground")
        # Determine repository slug
        if repo_identifier is None:
            # Derive repo_identifier similarly to run_repair.sh logic
            repo_identifier = instance_id.rsplit('-', 1)[0]  # Remove trailing -<bug_id>
            repo_identifier = repo_identifier.replace('--', '__')
        repo_path = os.path.join(playground_dir, repo_identifier)

        if not os.path.isdir(repo_path):
            print(f"Error: Repository path not found at {repo_path}. Cannot apply patch.")
            failed_files.append({"error": f"Repository path not found: {repo_path}"})
            return {
                "processed_patches": processed_patches,
                "applied_files": applied_files, 
                "failed_files": failed_files
            }
        
        with open(raw_output_path, 'r', encoding='utf-8') as f:
            raw_output_text = f.read()

        # 根据语言提取不同的代码块
        if self.language == "java":
            blocks = self._extract_java_blocks(raw_output_text)
        elif self.language == "cpp":
            blocks = self._extract_cpp_blocks(raw_output_text)
        else:
            blocks = extract_python_blocks(raw_output_text)
        
        file_to_commands = split_edit_multifile_commands(blocks)

        if not file_to_commands:
            print("No edit commands found in LLM output.")
            failed_files.append({"error": "No edit commands found in LLM output"})
            return {
                "processed_patches": processed_patches,
                "applied_files": applied_files,
                "failed_files": failed_files
            }

        for file_path_str, edit_commands in file_to_commands.items():
            try:
                edited_file = eval(file_path_str)
            except:
                print(f"Could not parse file path: {file_path_str}")
                failed_files.append({"file": file_path_str, "error": "Could not parse file path"})
                continue

            if edited_file.startswith('playground'):
                edited_file = '/'.join(edited_file.split('/')[2:])
            
            full_file_path = os.path.join(repo_path, edited_file)

            if not os.path.exists(full_file_path):
                print(f"File to be edited not found, skipping: {full_file_path}")
                failed_files.append({"file": edited_file, "error": "File not found"})
                continue

            with open(full_file_path, 'r', encoding='utf-8') as f:
                original_content = f.read()
            
            new_content = parse_diff_edit_commands_strict(edit_commands, original_content)
            
            # Indentation adjustment logic
            if new_content == original_content or not self._check_syntax(new_content, self.language):
                indent_changes = [-4, 4, -8, 8]  # 对应 -1, +1, -2, +2 缩进级别
                for indent_change in indent_changes:
                    adjusted_commands = [
                        self.adjust_command_indentation(cmd, indent_change) 
                        for cmd in edit_commands
                    ]
                    adjusted_content = parse_diff_edit_commands_strict(adjusted_commands, original_content)
                    if adjusted_content != original_content and self._check_syntax(adjusted_content, self.language):
                        new_content = adjusted_content
                        break
            
            # 如果第一次缩进调整失败，尝试only_one_replace模式
            if new_content == original_content or not self._check_syntax(new_content, self.language):
                new_content = parse_diff_edit_commands_strict(edit_commands, original_content, only_one_replace=True)
                if new_content == original_content or not self._check_syntax(new_content, self.language):
                    indent_changes = [-4, 4, -8, 8]  # 对应 -1, +1, -2, +2 缩进级别
                    for indent_change in indent_changes:
                        adjusted_commands = [
                            self.adjust_command_indentation(cmd, indent_change) 
                            for cmd in edit_commands
                        ]
                        adjusted_content = parse_diff_edit_commands_strict(adjusted_commands, original_content, only_one_replace=True)
                        if adjusted_content != original_content and self._check_syntax(adjusted_content, self.language):
                            new_content = adjusted_content
                            break

            if new_content != original_content and self._check_syntax(new_content, self.language):
                # Using difflib to create a patch
                diff = difflib.unified_diff(
                    original_content.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile=f"a/{edited_file}",
                    tofile=f"b/{edited_file}",
                )
                patch_content = "".join(diff)

                diff_patch_dir = os.path.join(os.path.dirname(raw_output_path), "diff_patches")
                os.makedirs(diff_patch_dir, exist_ok=True)
                sanitized_file_path = edited_file.replace('/', '_')
                diff_file_path = os.path.join(diff_patch_dir, f"{instance_id}_{sanitized_file_path}.diff")
                abs_diff_file_path = os.path.abspath(diff_file_path)
                
                with open(abs_diff_file_path, 'w', encoding='utf-8') as f:
                    f.write(patch_content)
                
                print(f"Generated git diff patch for {edited_file} and saved to {abs_diff_file_path}")

                # 记录处理后的patch信息
                patch_info = {
                    "file_path": edited_file,
                    "diff_file": abs_diff_file_path,
                    "diff_content": patch_content,
                    "size": len(patch_content)
                }
                processed_patches.append(patch_info)

                # 使用 applable_patch 函数验证patch是否能应用
                is_applable = applable_patch(patch_content, repo_name, commit_id)
                if is_applable:
                    print(f"✅ Patch for {edited_file} is applable")
                    applied_files.append(edited_file)
                else:
                    print(f"❌ Patch for {edited_file} is not applable")
                    failed_files.append({
                        "file": edited_file, 
                        "error": "Patch validation failed using applable_patch"
                    })
            else:
                print(f"Failed to generate a valid patch for {edited_file}. Skipping.")
                failed_files.append({"file": edited_file, "error": "Failed to generate valid patch"})
        
        # 返回处理结果
        return {
            "processed_patches": processed_patches,
            "applied_files": applied_files,
            "failed_files": failed_files
        }

    def process_instance(self, instance_id, locations_dir, output_dir, playground_dir=None, repo_identifier=None, repo_name=None, commit_id=None, save_to_jsonl=True):
        """
        Processes a single instance to generate a patch.
        """
        print(f"Processing instance: {instance_id}")
        
        # 初始化结果对象
        result = {
            "instance_id": instance_id,
            "timestamp": datetime.now().isoformat(),
            "raw_patch_content": "",
            "processed_patches": [],
            "applied_files": [],
            "failed_files": [],
            "status": "pending"
        }
        
        # Construct the path to the location file
        location_file = os.path.join(locations_dir, f"{instance_id}.json")
        if not os.path.exists(location_file):
            print(f"Error: Location file not found at {location_file}")
            result["status"] = "failed"
            result["failed_files"].append({"error": f"Location file not found: {location_file}"})
            if save_to_jsonl:
                self._save_result_to_jsonl(result, output_dir)
            return

        with open(location_file, 'r') as f:
            locate_result = json.load(f)
        
        # repo信息和commit信息应该从数据集获取，而不是从locate_result获取
        if not repo_name or not commit_id:
            print(f"🔍 Loading dataset information for {instance_id}...")
            dataset_info = load_instance_from_dataset(instance_id, "multi-swe-bench")
            if dataset_info:
                repo_name = dataset_info['repo_name']
                commit_id = dataset_info['commit_id']
                print(f"✅ Found repo: {repo_name}, commit: {commit_id}")
            else:
                print(f"⚠️ Could not load dataset info for {instance_id}")
                repo_name = repo_name or ''
                commit_id = commit_id or ''

        # Build a more detailed problem statement from related issues
        problem_statement = ""
        if locate_result and 'related_entities' in locate_result and locate_result['related_entities'].get('issues'):
            sorted_issues = sorted(locate_result['related_entities']['issues'],
                                   key=lambda x: x.get('similarity', 0), reverse=True)
            if sorted_issues:
                problem_statement += f"### {sorted_issues[0]['title']}\n{sorted_issues[0]['content']}"
                if len(sorted_issues) > 1 and sorted_issues[1].get('similarity', 0) > 0.1:
                    problem_statement += f"\n\n### {sorted_issues[1]['title']}\n{sorted_issues[1]['content']}"

        if not problem_statement:
            problem_statement = locate_result.get('issue', 'No issue description provided.')
        
        problem_statement = problem_statement.replace('\r', '')

        # Format related code entities, ensuring only code-related types are included
        content_all = ""
        if locate_result and 'related_entities' in locate_result:
            # Explicitly define code entity types to include, as issues are
            # already part of the problem_statement.
            code_entity_types = ['methods']
            for entity_type in code_entity_types:
                entities = locate_result['related_entities'].get(entity_type)
                if not entities:
                    continue
                
                # Sort entities by similarity score if available
                sorted_entities = sorted(entities, key=lambda x: x.get('similarity', 0), reverse=True)
                
                content_all += f"## Relevant {entity_type.capitalize()}\n"
                for item in sorted_entities:
                    content_all += format_entity_content(item)

        # Build the final prompt
        current_prompt = BASE_PROMPT_TEMPLATE.format(
            problem_statement=problem_statement,
            content=content_all if content_all else "No related code snippets found.",
            file_path_example=self.file_path_example,
            language_name=self.language_name,
            code_example=self.code_example,
            code_block_lang=self.code_block_lang
        )
        
        print("Prompt constructed. Calling LLM to generate patch...")
        
        # Get completion from LLM
        stream = self.get_completion(current_prompt, stream=True)

        if stream:
            os.makedirs(output_dir, exist_ok=True)
            output_file = os.path.join(output_dir, f"{instance_id}.patch")
            
            print(f"--- LLM raw output ---")
            raw_content = ""
            with open(output_file, 'w', encoding='utf-8') as f:
                if self.api_type == "anthropic":
                    # Handle Anthropic streaming
                    for chunk in stream:
                        if chunk.type == "content_block_delta":
                            content = chunk.delta.text
                            f.write(content)
                            raw_content += content
                            print(content, end='', flush=True)
                else:
                    # Handle OpenAI-compatible streaming
                    for chunk in stream:
                        content = chunk.choices[0].delta.content or ""
                        f.write(content)
                        raw_content += content
                        print(content, end='', flush=True)
            
            print(f"\n--- End of LLM raw output ---")
            print(f"Successfully generated raw patch and saved to {output_file}")
            
            # 保存原始patch内容
            result["raw_patch_content"] = raw_content
            
            print("\n--- Post-processing and applying patch ---")
            patch_result = self.post_process_and_apply_patch(
                instance_id, output_file, locations_dir, playground_dir, repo_identifier, 
                repo_name, commit_id
            )
            
            if patch_result:
                result["processed_patches"] = patch_result["processed_patches"]
                result["applied_files"] = patch_result["applied_files"]
                result["failed_files"] = patch_result["failed_files"]
                
                # 确定处理状态
                if result["applied_files"]:
                    if result["failed_files"]:
                        result["status"] = "partial"
                    else:
                        result["status"] = "success"
                else:
                    result["status"] = "failed"
            else:
                result["status"] = "failed"
                result["failed_files"].append({"error": "Post-processing failed"})
            
            print("--- Finished post-processing ---")
            
            # 保存结果到JSONL
            if save_to_jsonl:
                self._save_result_to_jsonl(result, output_dir)
                
        else:
            print("Failed to get a valid response from the model.")
            result["status"] = "failed"
            result["failed_files"].append({"error": "Failed to get LLM response"})
            if save_to_jsonl:
                self._save_result_to_jsonl(result, output_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Code Repair Script")
    parser.add_argument("final_locations_dir", type=str, help="Directory containing the final location files.")
    parser.add_argument("--instance_id", required=True, type=str, help="The specific instance ID to process.")
    parser.add_argument("--playground_dir", type=str, default=None, help="Root directory where repositories are located (default: sibling 'playground' of final_locations_dir).")
    parser.add_argument("--repo_identifier", type=str, default=None, help="Repository directory name inside playground (e.g., 'astropy__astropy'). If omitted, it will be derived from instance_id.")
    parser.add_argument("--save-jsonl", action="store_true", default=True, help="Save results to JSONL file (default: True)")
    parser.add_argument("--no-jsonl", action="store_true", help="Disable JSONL output")
    parser.add_argument("--language", type=str, default="python", choices=["python", "java", "cpp"], help="Programming language for the code (default: python)")
    parser.add_argument("--api_type", type=str, default="deepseek", choices=["openai", "anthropic", "deepseek", "qwen"], help="API type to use (default: deepseek)")
    parser.add_argument("--temperature", type=float, default=0.3, help="Temperature for LLM generation (default: 0.3)")
    
    args = parser.parse_args()

    # The output directory for patches will be inside the run directory
    patch_dir = os.path.join(os.path.dirname(args.final_locations_dir), "patches")

    # Initialize the repairer with language and API type parameters
    repairer = CodeRepair(language=args.language, api_type=args.api_type, temperature=args.temperature)

    # Determine whether to save to JSONL
    save_to_jsonl = args.save_jsonl and not args.no_jsonl

    # Process the single instance
    repairer.process_instance(
        instance_id=args.instance_id,
        locations_dir=args.final_locations_dir,
        output_dir=patch_dir,
        playground_dir=args.playground_dir,
        repo_identifier=args.repo_identifier,
        repo_name=None,  # 将从数据集加载
        commit_id=None,  # 将从数据集加载
        save_to_jsonl=save_to_jsonl
    )

