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
import re
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
from typing import Optional, Tuple
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
DEFAULT_COMPLETION_MAX_TOKENS = 4096
DEFAULT_REQUEST_TIMEOUT = 240


def load_instance_from_dataset(instance_id, benchmark_type="multi-swe-bench"):
    """从数据集加载实例信息，获取repo和commit信息"""
    try:
        local_file = os.getenv("SWE_BENCH_LOCAL_FILE")
        if local_file and os.path.exists(local_file):
            try:
                with open(local_file, "r", encoding="utf-8") as f:
                    for line in f:
                        item = json.loads(line.strip())
                        if item.get("instance_id") == instance_id:
                            repo_name = item.get("repo", "")
                            commit_id = item.get("base_commit", "")
                            return {
                                "repo_name": repo_name,
                                "commit_id": commit_id,
                                "data": item,
                            }
            except Exception as e:
                print(f"Error reading local dataset file {local_file}: {e}")

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

Below are code segments from several relevant files. The bug and the fix may span multiple files, so treat them as a joint repair context.
--- BEGIN FILE ---
```
{content}
```
--- END FILE ---

Please directly generate the complete *SEARCH/REPLACE* edits needed to fix the issue. The fix may require changes in one file or multiple files.

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
8. If the fix spans multiple files, output edits for every required file.
9. Output only the final *SEARCH/REPLACE* edits. Do not include analysis, discussion, bullet points, or prose before or after the code blocks.
10. Start directly with the first ```{code_block_lang}``` block and end immediately after the last edit block.
11. Do not provide multiple alternative fixes; provide exactly one final patch set.
12. If the fix spans multiple files, you may emit multiple code blocks or one combined code block, but include every required file edit exactly once.
13. Prefer shorter exact SEARCH blocks copied verbatim from the provided context instead of broad rewrites that may not match the file exactly.
14. If a public wrapper delegates to internal helper functions, prefer fixing the smallest helper that computes the faulty behavior instead of editing the wrapper unless the wrapper itself is clearly wrong.

Please note that the *SEARCH/REPLACE* edit REQUIRES PROPER INDENTATION. If you would like to add a line like '        print(x)' ({language_name}), you must fully write that out, with all those spaces before the code!
Wrap the *SEARCH/REPLACE* edit in blocks ```{code_block_lang}...```.
"""

OPEN_MODEL_SYSTEM_PROMPT = (
    "You are a repository repair agent. "
    "Use only the provided base-commit code context. "
    "Return exactly one fenced code block containing the final SEARCH/REPLACE edits. "
    "Your first non-whitespace output characters must be the fenced code block opener. "
    "Do not output analysis, plans, prose, alternatives, unchanged edits, or metadata lines. "
    "If the correct fix spans multiple files or functions shown in context, include every required edit in the same final patch set."
)

OPEN_MODEL_PROMPT_TEMPLATE = """
Issue:
{problem_statement}

Relevant files and candidate code regions:
```text
{content}
```

Generate exactly one final patch set using SEARCH/REPLACE edits.

Rules:
- The fix may span multiple functions and multiple files.
- If the correct repair requires coordinated changes across multiple shown files, include all of them in this one final answer.
- Use only file paths that appear in the provided context.
- The provided source excerpts are the authoritative base-commit code. SEARCH blocks must be copied from that provided context, not from memory or another version.
- Do not say that the context is insufficient or ask for more files. Use the provided files to produce one concrete patch.
- Edit only code that is shown in the provided source excerpts. Do not invent file headers, imports, helper methods, or docstrings that are not shown.
- The patch must directly address the concrete failing behavior described in the issue. Avoid cleanup, refactoring, or style-only edits that do not change that behavior.
- SEARCH blocks must match the existing code exactly, including indentation.
- Do not copy metadata lines such as "- start_line", "- end_line", "- similarity", or "- source_mode" into the patch.
- Prefer the smallest exact contiguous SEARCH block that can be safely replaced.
- Every REPLACE block must differ from its SEARCH block in at least one actual code token or character.
- If a hunk would leave SEARCH and REPLACE identical, omit that hunk instead of outputting a no-op edit.
- A patch that contains only unchanged SEARCH/REPLACE pairs is invalid. If your first candidate is unchanged, choose a smaller buggy statement from the provided context and make one real behavioral code change.
- For the same file, output the final edit(s) only once; do not emit draft and revised versions of the same file.
- Do not repeat the same file path in multiple alternative code blocks unless the file truly needs multiple distinct SEARCH/REPLACE hunks.
- If you include multiple hunks for the same file, each hunk must change different lines and every hunk must be non-empty.
- If a wrapper or top-level API function simply delegates to internal helpers, prefer editing the helper that performs the faulty computation rather than the wrapper, unless the wrapper itself is clearly wrong.
- Do not stop after the first plausible file if another shown file also needs an accompanying change for the fix to work.
- If the issue describes an interaction between logic shown in multiple files, patch both sides of that interaction instead of changing only the first plausible file.
- Before finishing, remove speculative edits that are not needed for the reported failure.
- Output exactly one fenced ```{code_block_lang}``` block containing the final edits.
- The first line of the response must be ```{code_block_lang}```.
- The last line of the response must be ```.
- Do not include any prose before, between, or after the code blocks.

Format example:
{code_example}
"""


class CodeRepair:
    def __init__(
        self,
        language="python",
        api_type="deepseek",
        temperature=0.3,
        model_name_override=None,
        base_url_override=None,
        api_key_env=None,
        extra_body_json=None,
    ):
        self.temperature = temperature
        self.top_p = TOP_P
        self.api_type = api_type
        self.MAX_INPUT_LENGTH = MAX_INPUT_LENGTH_CONFIG.get(api_type, MAX_INPUT_LENGTH)
        self.last_completion_error = None
        self.extra_body = {}
        if extra_body_json:
            try:
                self.extra_body = json.loads(extra_body_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON for --extra-body-json: {e}") from e
        
        # Initialize API client based on type
        if api_type == "openai":
            self.client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            self.model = model_name_override or LLM_MODELS['openai']
        elif api_type == "anthropic":
            self.client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
            self.model = model_name_override or LLM_MODELS['anthropic']
        elif api_type == "deepseek":
            self.client = openai.OpenAI(
                api_key=os.getenv(api_key_env or "DEEPSEEK_API_KEY") or DEEPSEEK_API_KEY,
                base_url=base_url_override or DEEPSEEK_BASE_URL,
            )
            self.model = model_name_override or LLM_MODELS['deepseek']
        elif api_type == "qwen":
            self.client = openai.OpenAI(
                api_key=os.getenv(api_key_env or "QWEN_API_KEY") or QWEN_API_KEY,
                base_url=base_url_override or QWEN_BASE_URL,
            )
            self.model = model_name_override or LLM_MODELS['qwen']
        elif api_type == "openai_compat":
            resolved_key_env = api_key_env or "OPENAI_API_KEY"
            self.client = openai.OpenAI(
                api_key=os.getenv(resolved_key_env),
                base_url=base_url_override,
            )
            self.model = model_name_override or MODEL_NAME
        else:
            # Default to deepseek
            self.client = openai.OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
            self.model = model_name_override or LLM_MODELS['deepseek']
        
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
### pkg/parser.py
<<<<<<< SEARCH
def normalize_name(name):
    return name.strip()
=======
def normalize_name(name):
    return name.strip().lower()
>>>>>>> REPLACE
### pkg/service.py
<<<<<<< SEARCH
def build_user_record(name):
    return {"name": normalize_name(name), "active": True}
=======
def build_user_record(name):
    normalized = normalize_name(name)
    return {"name": normalized, "slug": normalized, "active": True}
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

    def _build_error_summary(self, result):
        messages = []
        if result.get("error_summary"):
            messages.append(result["error_summary"])
        for item in result.get("failed_files", []):
            err = (item or {}).get("error")
            file_path = (item or {}).get("file")
            if err and file_path:
                messages.append(f"{file_path}: {err}")
            elif err:
                messages.append(err)
        deduped = []
        seen = set()
        for msg in messages:
            if msg not in seen:
                deduped.append(msg)
                seen.add(msg)
        return " | ".join(deduped[:8])

    def _write_diagnostic_file(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def _persist_failure_artifacts(self, result, output_file):
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            return
        summary = self._build_error_summary(result) or "No raw output captured."
        diagnostic_text = result.get("raw_patch_content", "") or f"[ERROR]\n{summary}\n"
        self._write_diagnostic_file(output_file, diagnostic_text)
        result["raw_output_file"] = output_file
        result["error_summary"] = summary
    
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

    def _sanitize_patch_block_text(self, block_text: str) -> str:
        text = (block_text or "").strip()
        if not text:
            return ""

        lines = text.splitlines()
        cleaned_lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(cleaned_lines).strip()
        if not text:
            return ""

        first_search = text.find("<<<<<<< SEARCH")
        if first_search == -1:
            return text

        last_file_marker = text.rfind("\n### ", 0, first_search)
        if text.startswith("### "):
            last_file_marker = 0
        elif last_file_marker != -1:
            last_file_marker += 1

        if last_file_marker != -1:
            return text[last_file_marker:].strip()
        return text[first_search:].strip()

    def count_tokens(self, text):
        """计算不同 API 的 token 数量"""
        result = 0
        if self.api_type in ["openai", "openai_compat"]:
            # Use tiktoken to calculate token count for GPT models
            encoding = tiktoken.encoding_for_model(LLM_MODELS['openai'])
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
        
        elif self.api_type in ['qwen', 'deepseek', 'openai_compat']:
            # Deepseek and Qwen use GPT-like tokenizer with adjustment
            encoding = tiktoken.encoding_for_model(LLM_MODELS['openai'])
            result = int(len(encoding.encode(text)) * 1.3)
        
        return result

    def _method_identity(self, item):
        return (
            item.get("file_path", ""),
            item.get("signature", ""),
            item.get("start_line"),
            item.get("end_line"),
        )

    def _is_repair_candidate_method(self, item):
        signature = (item.get("signature") or "").strip()
        source = (item.get("source_code") or "").lstrip()
        if not signature:
            return False
        if "__all__" in signature or ": list" in signature:
            return False
        if self.language == "python":
            return "(" in signature and (source.startswith("def ") or source.startswith("class "))
        return True

    def _diverse_method_order(self, methods):
        sorted_methods = [
            item
            for _, item in sorted(
                enumerate(methods),
                key=lambda x: (-x[1].get("similarity", 0), x[0]),
            )
        ]
        file_order = []
        file_first = {}
        for item in sorted_methods:
            file_path = item.get("file_path", "")
            if file_path not in file_first:
                file_order.append(file_path)
                file_first[file_path] = item

        if len(sorted_methods) >= 20:
            diversity_target = 6
        elif len(sorted_methods) >= 10:
            diversity_target = 3
        else:
            diversity_target = 1
        diversity_target = min(diversity_target, len(file_order))

        ordered = []
        seen = set()
        selected_files = file_order[:diversity_target]
        buckets = {fp: [] for fp in selected_files}
        fallback = []
        for item in sorted_methods:
            file_path = item.get("file_path", "")
            if file_path in buckets:
                buckets[file_path].append(item)
            else:
                fallback.append(item)

        for file_path in selected_files:
            item = file_first[file_path]
            ident = self._method_identity(item)
            if ident in seen:
                continue
            seen.add(ident)
            ordered.append(item)

        round_robin_pending = True
        while round_robin_pending:
            round_robin_pending = False
            for file_path in selected_files:
                while buckets[file_path]:
                    item = buckets[file_path].pop(0)
                    ident = self._method_identity(item)
                    if ident in seen:
                        continue
                    seen.add(ident)
                    ordered.append(item)
                    round_robin_pending = True
                    break

        for item in fallback:
            ident = self._method_identity(item)
            if ident in seen:
                continue
            seen.add(ident)
            ordered.append(item)
        return ordered

    def _render_method_context(self, methods):
        if not methods:
            return ""
        grouped = {}
        for item in methods:
            grouped.setdefault(item.get("file_path", ""), []).append(item)

        file_order = []
        seen_files = set()
        for item in methods:
            file_path = item.get("file_path", "")
            if file_path not in seen_files:
                seen_files.add(file_path)
                file_order.append(file_path)

        sections = ["## Candidate Files", *[f"- {fp}" for fp in file_order], "", "## Relevant Methods By File"]
        for file_path in file_order:
            sections.append(f"\n### FILE: {file_path}")
            for idx, item in enumerate(grouped[file_path]):
                mode_override = item.get("_prompt_mode")
                if mode_override:
                    mode = mode_override
                elif idx == 0:
                    mode = "primary"
                elif idx == 1:
                    mode = "secondary"
                else:
                    mode = "metadata"
                sections.append(self._render_single_method_context(item, mode=mode))
        return "\n".join(sections).strip() + "\n"

    def _build_file_diverse_items(self, methods, max_files, mode_plan):
        ordered_methods = self._diverse_method_order(methods)
        selected = []
        seen_files = set()
        for item in ordered_methods:
            file_path = item.get("file_path", "")
            if not file_path or file_path in seen_files:
                continue
            seen_files.add(file_path)
            mode_idx = min(len(selected), len(mode_plan) - 1)
            item_copy = dict(item)
            item_copy["_prompt_mode"] = mode_plan[mode_idx]
            selected.append(item_copy)
            if len(selected) >= max_files:
                break
        return selected

    def _get_prompt_token_limit(self):
        base_limit = int(self.MAX_INPUT_LENGTH * 0.9)
        model_name = (self.model or "").lower()
        if "qwen3-coder-480b-a35b-instruct" in model_name:
            return min(base_limit, 3200)
        if "glm-5" in model_name:
            return min(base_limit, 4200)
        if "kimi" in model_name:
            return min(base_limit, 3200)
        if self.api_type == "openai_compat":
            return min(base_limit, 5000)
        return min(base_limit, 8000)

    def _get_completion_max_tokens(self):
        model_name = (self.model or "").lower()
        if "qwen3-coder-30b" in model_name:
            return 1024
        if "deepseek-coder-v2-lite" in model_name:
            return 1536
        if "qwen3-coder-480b-a35b-instruct" in model_name:
            return 1024
        if "glm-5" in model_name:
            return 2048
        if "kimi" in model_name:
            return 1536
        return DEFAULT_COMPLETION_MAX_TOKENS

    def _get_request_timeout(self):
        model_name = (self.model or "").lower()
        if "qwen3-coder-30b" in model_name or "deepseek-coder-v2-lite" in model_name:
            return 180
        if "glm-5" in model_name:
            return 180
        if "qwen3-coder-480b-a35b-instruct" in model_name:
            return 90
        if "kimi" in model_name:
            return 120
        return DEFAULT_REQUEST_TIMEOUT

    def _prefer_compact_first(self):
        model_name = (self.model or "").lower()
        return (
            "qwen3-coder" in model_name
            or "deepseek-coder-v2" in model_name
            or "kimi" in model_name
        )

    def _prefer_ultra_compact_first(self):
        model_name = (self.model or "").lower()
        return "qwen3-coder" in model_name or "deepseek-coder-v2" in model_name

    def _use_streaming(self):
        model_name = (self.model or "").lower()
        if "qwen3-coder" in model_name:
            return False
        if "deepseek-coder-v2" in model_name:
            return False
        if "glm-5" in model_name:
            return False
        return True

    @staticmethod
    def _normalize_generated_text(text):
        return (
            (text or "")
            .replace("\u0120", " ")
            .replace("\u010a", "\n")
            .replace("\u0109", "\t")
        )

    def _get_response_prefill(self):
        model_name = (self.model or "").lower()
        if "qwen3-coder" in model_name:
            return f"```{self.code_block_lang}\n"
        if "deepseek-coder-v2" in model_name:
            return f"```{self.code_block_lang}\n"
        if "glm-5" in model_name:
            return f"```{self.code_block_lang}\n"
        return ""

    def _get_prompt_template(self):
        if self.api_type in ["openai_compat", "qwen", "deepseek", "openai"]:
            return OPEN_MODEL_PROMPT_TEMPLATE
        return BASE_PROMPT_TEMPLATE

    def _truncate_source_preserve_ends(self, text, token_limit):
        text = (text or "").rstrip()
        if not text:
            return ""
        if self.count_tokens(text) <= token_limit:
            return text

        lines = text.splitlines()
        if len(lines) <= 12:
            return self._truncate_text_to_token_limit(text, token_limit)

        marker = "\n...\n# [middle truncated]\n...\n"
        head_count = max(4, len(lines) // 4)
        tail_count = max(4, len(lines) // 4)
        best = self._truncate_text_to_token_limit(text, token_limit)

        while head_count + tail_count < len(lines):
            candidate = "\n".join(lines[:head_count]) + marker + "\n".join(lines[-tail_count:])
            if self.count_tokens(candidate) <= token_limit:
                best = candidate
                break
            if head_count > tail_count:
                head_count = max(4, head_count - 2)
            else:
                tail_count = max(4, tail_count - 2)
            if head_count == 4 and tail_count == 4:
                break
        return best

    def _get_method_source_token_limit(self, is_primary):
        model_name = (self.model or "").lower()
        if "qwen3-coder-480b-a35b-instruct" in model_name:
            return 500 if is_primary else 180
        if "glm-5" in model_name:
            return 700 if is_primary else 260
        if "kimi" in model_name:
            return 500 if is_primary else 180
        return 1000 if is_primary else 400

    def _render_single_method_context(self, item, mode="primary"):
        include_source = mode != "metadata"
        source = (item.get("source_code") or "").rstrip()
        rendered_source = ""
        if include_source:
            source_limit = self._get_method_source_token_limit(mode == "primary")
            rendered_source = self._truncate_source_preserve_ends(source, source_limit)
        similarity = item.get("similarity")
        parts = [
            f"- signature : {item.get('signature', '')}",
            f"- start_line : {item.get('start_line')}",
            f"- end_line : {item.get('end_line')}",
        ]
        if similarity is not None:
            parts.append(f"- similarity : {similarity:.4f}")
        if item.get("_selection_role"):
            parts.append(f"- selection_role : {item.get('_selection_role')}")
        if item.get("_kg_distance") is not None:
            parts.append(f"- kg_distance : {item.get('_kg_distance')}")
        if item.get("_kg_grounding"):
            parts.append(f"- kg_grounding : {item.get('_kg_grounding')}")
        if mode == "primary":
            parts.append("- source_mode : primary")
        elif mode == "secondary":
            parts.append("- source_mode : compressed-secondary")
        else:
            parts.append("- source_mode : metadata-only")
        if include_source:
            parts.append("- source_authority : authoritative-base-commit")
            parts.append(f"```{self.code_block_lang}")
            parts.append(rendered_source)
            parts.append("```")
        return "\n".join(parts)

    def _truncate_text_to_token_limit(self, text, token_limit):
        text = (text or "").strip()
        if not text:
            return ""
        if self.count_tokens(text) <= token_limit:
            return text
        lo, hi = 0, len(text)
        best = text[: max(1, min(len(text), 2000))]
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = text[:mid].rstrip()
            if self.count_tokens(candidate) <= token_limit:
                best = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        if len(best) < len(text):
            best = best.rstrip() + "\n\n[truncated for brevity]"
        return best

    def _select_problem_statement(self, locate_result, dataset_info=None):
        dataset_problem = ""
        if dataset_info and isinstance(dataset_info.get("data"), dict):
            dataset_problem = (dataset_info["data"].get("problem_statement") or "").strip()

        locate_issue = (locate_result.get("issue") or "").strip() if locate_result else ""
        if locate_issue:
            return self._truncate_text_to_token_limit(locate_issue, 1200)
        if dataset_problem:
            return self._truncate_text_to_token_limit(dataset_problem, 1200)

        related_issues = []
        if locate_result and locate_result.get("related_entities"):
            related_issues = locate_result["related_entities"].get("issues") or []
        if related_issues:
            sorted_issues = sorted(related_issues, key=lambda x: x.get("similarity", 0), reverse=True)
            issue = sorted_issues[0]
            text = f"### {issue.get('title', '').strip()}\n{(issue.get('content') or '').strip()}".strip()
            return self._truncate_text_to_token_limit(text, 1200)

        return "No issue description provided."

    def _build_issue_context(self, locate_result, dataset_info=None):
        main_issue = self._select_problem_statement(locate_result, dataset_info).strip()
        related_issues = []
        repair_guidance = {}
        if locate_result and locate_result.get("related_entities"):
            related_issues = locate_result["related_entities"].get("issues") or []
        if locate_result:
            repair_guidance = ((locate_result.get("artifact_stats") or {}).get("repair_guidance") or {})

        sections = []
        if main_issue:
            sections.append(f"Primary issue description:\n{main_issue}")

        if related_issues:
            sorted_issues = sorted(
                related_issues,
                key=lambda x: x.get("similarity", 0),
                reverse=True,
            )
            related = sorted_issues[0]
            title = (related.get("title") or "").strip()
            content = (related.get("content") or "").strip()
            related_text = f"{title}\n{content}".strip()
            if related_text and not (title and title in main_issue):
                sections.append(f"Most related historical issue:\n{related_text}")

        if repair_guidance:
            primary_indexes = repair_guidance.get("primary_indexes") or []
            focus = (repair_guidance.get("repair_focus") or "").strip()
            multi = repair_guidance.get("multi_file")
            guidance_lines = []
            if primary_indexes:
                guidance_lines.append("likely buggy candidate indexes: " + ", ".join(str(x) for x in primary_indexes))
            if focus:
                guidance_lines.append("repair focus: " + focus)
            if multi:
                guidance_lines.append("coordinate across multiple files if required by the shown code")
            if guidance_lines:
                sections.append("Model-guided repair focus:\n- " + "\n- ".join(guidance_lines))

        combined = "\n\n".join(s for s in sections if s).strip()
        return self._truncate_text_to_token_limit(combined or main_issue, 1400)

    def _enrich_methods_with_file_context(self, methods, repo_path, commit_id, max_files=6):
        if not methods or not repo_path:
            return methods or []

        enriched = list(methods)
        files_with_source = {
            (m.get("file_path") or "").replace("\\", "/")
            for m in methods
            if (m.get("source_code") or "").strip()
        }
        injected_files = set()

        sorted_methods = [
            item
            for _, item in sorted(
                enumerate(methods),
                key=lambda x: (-x[1].get("similarity", 0), x[0]),
            )
        ]

        for item in sorted_methods:
            file_path = (item.get("file_path") or "").replace("\\", "/").strip()
            if not file_path or file_path in files_with_source or file_path in injected_files:
                continue
            content, _ = self._load_original_file_content(repo_path, file_path, commit_id)
            if not content:
                continue

            item_copy = dict(item)
            item_copy["source_code"] = content
            item_copy["start_line"] = item_copy.get("start_line") or 1
            item_copy["end_line"] = item_copy.get("end_line") or len(content.splitlines())
            if not (item_copy.get("signature") or "").strip():
                item_copy["signature"] = f"{file_path} [file context]"
            else:
                item_copy["signature"] = f"{item_copy['signature']} [file context]"
            enriched.append(item_copy)
            injected_files.add(file_path)
            if len(injected_files) >= max_files:
                break

        return enriched

    def _build_repair_context(self, problem_statement, methods):
        if not methods:
            return ""

        methods = [m for m in methods if (m.get("source_code") or "").strip()]
        if not methods:
            return ""

        ordered_methods = self._diverse_method_order(methods)
        prompt_limit = self._get_prompt_token_limit()
        selected = []

        for item in ordered_methods:
            candidate = selected + [item]
            candidate_content = self._render_method_context(candidate)
            candidate_prompt = self._get_prompt_template().format(
                problem_statement=problem_statement,
                content=candidate_content,
                file_path_example=self.file_path_example,
                language_name=self.language_name,
                code_example=self.code_example,
                code_block_lang=self.code_block_lang,
            )
            if self.count_tokens(candidate_prompt) <= prompt_limit or not selected:
                selected = candidate

        return self._render_method_context(selected)

    def _render_agentless_style_context(self, methods):
        if not methods:
            return ""

        grouped = {}
        file_order = []
        for item in methods:
            file_path = (item.get("file_path") or "").replace("\\", "/").strip()
            source = (item.get("source_code") or "").rstrip()
            if not file_path or not source:
                continue
            if file_path not in grouped:
                grouped[file_path] = []
                file_order.append(file_path)
            source_limit = self._get_method_source_token_limit(len(grouped[file_path]) == 0)
            rendered_source = self._truncate_source_preserve_ends(source, source_limit)
            if rendered_source and rendered_source not in grouped[file_path]:
                grouped[file_path].append(rendered_source)

        if not file_order:
            return ""

        sections = []
        for idx, file_path in enumerate(file_order):
            merged = "\n\n# --- candidate region ---\n\n".join(grouped[file_path]).strip()
            if not merged:
                continue
            role = "primary suspect file" if idx == 0 else "secondary suspect file"
            sections.append(f"### {file_path} [{role}]")
            sections.append(f"```{self.code_block_lang}")
            sections.append(merged)
            sections.append("```")
        return "\n".join(sections).strip()

    def _build_agentless_style_repair_context(self, problem_statement, methods):
        methods = [m for m in (methods or []) if (m.get("source_code") or "").strip()]
        if not methods:
            return ""

        ordered_methods = self._diverse_method_order(methods)
        selected = []
        seen_files = set()
        for item in ordered_methods:
            file_path = (item.get("file_path") or "").replace("\\", "/").strip()
            if not file_path:
                continue
            if file_path in seen_files:
                continue
            seen_files.add(file_path)
            selected.append(item)
            if len(selected) >= 3:
                break

        if not selected:
            return ""

        prompt_limit = self._get_prompt_token_limit()
        chosen = []
        for item in selected:
            candidate = chosen + [item]
            candidate_content = self._render_agentless_style_context(candidate)
            candidate_prompt = self._get_prompt_template().format(
                problem_statement=problem_statement,
                content=candidate_content,
                file_path_example=self.file_path_example,
                language_name=self.language_name,
                code_example=self.code_example,
                code_block_lang=self.code_block_lang,
            )
            if self.count_tokens(candidate_prompt) <= prompt_limit or not chosen:
                chosen = candidate

        return self._render_agentless_style_context(chosen)

    def _build_compact_repair_context(self, problem_statement, methods):
        methods = [m for m in (methods or []) if (m.get("source_code") or "").strip()]
        if not methods:
            return ""

        selected = self._build_file_diverse_items(
            methods,
            max_files=5,
            mode_plan=["primary", "secondary", "secondary", "metadata", "metadata"],
        )

        if not selected:
            return ""

        prompt_limit = max(1200, int(self._get_prompt_token_limit() * 0.7))
        while selected:
            candidate_content = self._render_method_context(selected)
            candidate_prompt = self._get_prompt_template().format(
                problem_statement=problem_statement,
                content=candidate_content,
                file_path_example=self.file_path_example,
                language_name=self.language_name,
                code_example=self.code_example,
                code_block_lang=self.code_block_lang,
            )
            if self.count_tokens(candidate_prompt) <= prompt_limit:
                return candidate_content
            selected = selected[:-1]

        return ""

    def _build_breadth_repair_context(self, problem_statement, methods):
        methods = [m for m in (methods or []) if (m.get("source_code") or "").strip()]
        if not methods:
            return ""

        selected = self._build_file_diverse_items(
            methods,
            max_files=6,
            mode_plan=["primary", "secondary", "secondary", "secondary", "metadata", "metadata"],
        )
        if not selected:
            return ""

        prompt_limit = max(1600, int(self._get_prompt_token_limit() * 0.85))
        while selected:
            candidate_content = self._render_method_context(selected)
            candidate_prompt = self._get_prompt_template().format(
                problem_statement=problem_statement,
                content=candidate_content,
                file_path_example=self.file_path_example,
                language_name=self.language_name,
                code_example=self.code_example,
                code_block_lang=self.code_block_lang,
            )
            if self.count_tokens(candidate_prompt) <= prompt_limit:
                return candidate_content
            selected = selected[:-1]
        return ""

    def _build_ultra_compact_repair_context(self, problem_statement, methods):
        methods = [m for m in (methods or []) if (m.get("source_code") or "").strip()]
        if not methods:
            return ""

        ordered_methods = self._diverse_method_order(methods)
        primary_file = ordered_methods[0].get("file_path", "") if ordered_methods else ""
        primary_methods = [
            m for m in ordered_methods
            if m.get("file_path", "") == primary_file and self._is_repair_candidate_method(m)
        ]
        if not primary_methods:
            primary_methods = [m for m in ordered_methods if m.get("file_path", "") == primary_file]
        secondary_file = None
        for item in ordered_methods:
            file_path = item.get("file_path", "")
            if file_path and file_path != primary_file:
                secondary_file = file_path
                break

        candidate_order = []
        candidate_order.extend(primary_methods[:4])
        if secondary_file:
            for item in ordered_methods:
                if item.get("file_path", "") == secondary_file:
                    candidate_order.append(item)
                    break

        selected = []
        seen = set()
        for item in candidate_order:
            ident = self._method_identity(item)
            if ident in seen:
                continue
            seen.add(ident)
            selected.append(item)

        if not selected:
            return ""

        prompt_limit = 1100
        chosen = []
        for item in selected:
            candidate = chosen + [item]
            candidate_content = self._render_method_context(candidate)
            candidate_prompt = self._get_prompt_template().format(
                problem_statement=problem_statement,
                content=candidate_content,
                file_path_example=self.file_path_example,
                language_name=self.language_name,
                code_example=self.code_example,
                code_block_lang=self.code_block_lang,
            )
            if self.count_tokens(candidate_prompt) <= prompt_limit:
                chosen = candidate

        if chosen:
            return self._render_method_context(chosen)

        return ""

    def _build_retry_problem_statement(self, problem_statement, failure_reason, no_op_failure=False, refusal_failure=False):
        retry_note = [
            "\n\nRetry requirements:",
            f"- Previous attempt failed because: {failure_reason}.",
            "- Do not repeat unchanged code.",
            "- Do not output analysis.",
            "- Return only the final non-empty SEARCH/REPLACE patch set.",
            "- Do not say that more context or more files are needed; choose the best concrete fix from the provided files.",
        ]
        if no_op_failure:
            retry_note.extend(
                [
                    "- The previous patch was a no-op or had no effective code change.",
                    "- SEARCH and REPLACE must differ in executable code, not only comments, docstrings, or blank lines.",
                    "- If your first choice would be unchanged, choose a different code region from the provided context and make one minimal behavioral code change.",
                    "- Change at least one operator, branch condition, argument, return value, or called helper in the final patch.",
                ]
            )
        if refusal_failure:
            retry_note.extend(
                [
                    "- The necessary files are already included below.",
                    "- Do not claim that the context is insufficient, that source files are missing, or that you need more files.",
                    "- Choose the most plausible fix from the provided files and emit one concrete patch.",
                ]
            )
        retry_note = "\n".join(retry_note) + "\n"
        return self._truncate_text_to_token_limit((problem_statement or "").strip() + retry_note, 1400)

    def _extract_target_files_from_raw(self, raw_patch_content):
        if not raw_patch_content:
            return []
        matches = re.findall(r"^###\s+(.+?)\s*$", raw_patch_content, flags=re.MULTILINE)
        target_files = []
        seen = set()
        for match in matches:
            file_path = (match or "").strip()
            if not file_path or file_path in seen:
                continue
            seen.add(file_path)
            target_files.append(file_path)
        return target_files

    def _build_targeted_retry_context(self, methods, target_files):
        if not methods or not target_files:
            return ""
        target_set = set(target_files[:2])
        focused = [m for m in methods if (m.get("file_path") or "").strip() in target_set]
        if not focused:
            return ""
        chosen = []
        file_counts = {}
        for item in focused:
            file_path = (item.get("file_path") or "").strip()
            count = file_counts.get(file_path, 0)
            if count >= 3:
                continue
            file_counts[file_path] = count + 1
            chosen.append(item)
        if not chosen:
            return ""
        for idx, item in enumerate(chosen):
            if idx == 0:
                item["_prompt_mode"] = "primary"
            elif idx < 3:
                item["_prompt_mode"] = "secondary"
            else:
                item["_prompt_mode"] = "metadata"
        try:
            return self._build_compact_repair_context("", chosen)
        finally:
            for item in chosen:
                item.pop("_prompt_mode", None)

    def _is_noop_like_failure(self, attempt_result):
        if not attempt_result:
            return False
        if attempt_result.get("applied_files"):
            return False
        raw_content = attempt_result.get("raw_patch_content", "") or ""
        failed_files = attempt_result.get("failed_files", []) or []
        messages = []
        for item in failed_files:
            if isinstance(item, dict):
                msg = item.get("error")
                if msg:
                    messages.append(msg)
        combined = " | ".join(messages).lower()
        if "no effective edit commands" in combined:
            return True
        if "no changes were made" in combined:
            return True
        if "<<<<<<< search" in raw_content.lower() and not attempt_result.get("processed_patches"):
            return True
        return False

    def _needs_broader_context_failure(self, attempt_result):
        if not attempt_result:
            return False
        raw_content = (attempt_result.get("raw_patch_content", "") or "").lower()
        failed_files = attempt_result.get("failed_files", []) or []
        messages = []
        for item in failed_files:
            if isinstance(item, dict):
                msg = item.get("error")
                if msg:
                    messages.append(msg)
        combined = " | ".join(messages).lower()
        markers = [
            "need more context",
            "provided context only",
            "provided context alone",
            "cannot produce a valid patch",
            "no edit commands found",
        ]
        text = f"{raw_content}\n{combined}"
        return any(marker in text for marker in markers)

    def _is_refusal_like_failure(self, attempt_result):
        if not attempt_result:
            return False
        raw_content = (attempt_result.get("raw_patch_content", "") or "").lower()
        failed_files = attempt_result.get("failed_files", []) or []
        messages = []
        for item in failed_files:
            if isinstance(item, dict):
                msg = item.get("error")
                if msg:
                    messages.append(msg)
        combined = " | ".join(messages).lower()
        text = f"{raw_content}\n{combined}"
        markers = [
            "cannot provide a valid patch",
            "without access to the actual source files",
            "relevant source files",
            "the context is insufficient",
            "need more files",
            "need access to",
            "not included in the provided context",
        ]
        return any(marker in text for marker in markers)

    def _build_refusal_recovery_context(self, problem_statement, methods):
        methods = [m for m in (methods or []) if (m.get("source_code") or "").strip()]
        if not methods:
            return ""
        selected = self._build_file_diverse_items(
            methods,
            max_files=4,
            mode_plan=["primary", "secondary", "secondary", "secondary"],
        )
        if not selected:
            return ""
        prompt_limit = max(1400, int(self._get_prompt_token_limit() * 0.8))
        while selected:
            candidate_content = self._render_method_context(selected)
            candidate_prompt = self._get_prompt_template().format(
                problem_statement=problem_statement,
                content=candidate_content,
                file_path_example=self.file_path_example,
                language_name=self.language_name,
                code_example=self.code_example,
                code_block_lang=self.code_block_lang,
            )
            if self.count_tokens(candidate_prompt) <= prompt_limit:
                return candidate_content
            selected = selected[:-1]
        return ""

    def _generate_raw_patch(self, prompt, output_file):
        use_streaming = self._use_streaming()
        response = self.get_completion(prompt, stream=use_streaming)
        if not response:
            error = self.last_completion_error or "Failed to get LLM response"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(f"[ERROR]\n{error}\n")
            return "", error

        print(f"--- LLM raw output ---")
        raw_content = ""
        stream_error = None
        with open(output_file, 'w', encoding='utf-8') as f:
            try:
                if not use_streaming:
                    raw_content = response or ""
                    f.write(raw_content)
                    if raw_content:
                        print(raw_content, end='', flush=True)
                elif self.api_type == "anthropic":
                    for chunk in response:
                        if chunk.type == "content_block_delta":
                            content = chunk.delta.text
                            f.write(content)
                            raw_content += content
                            print(content, end='', flush=True)
                else:
                    for chunk in response:
                        content = chunk.choices[0].delta.content or ""
                        f.write(content)
                        raw_content += content
                        print(content, end='', flush=True)
            except Exception as e:
                stream_error = str(e)
                print(f"\nStreaming interrupted: {e}")

        print(f"\n--- End of LLM raw output ---")
        normalized_content = self._normalize_generated_text(raw_content)
        if normalized_content != raw_content:
            raw_preserve_path = f"{output_file}.raw"
            with open(raw_preserve_path, "w", encoding="utf-8") as f:
                f.write(raw_content)
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(normalized_content)
            print(f"Normalized tokenized text for patch parsing; preserved original raw output at {raw_preserve_path}")
            raw_content = normalized_content
        print(f"Successfully generated raw patch and saved to {output_file}")
        return raw_content, stream_error

    def _run_generation_attempt(self, instance_id, prompt, output_file, locations_dir, playground_dir, repo_identifier, repo_name, commit_id):
        attempt_result = {
            "raw_patch_content": "",
            "processed_patches": [],
            "applied_files": [],
            "failed_files": [],
            "status": "failed",
        }

        raw_content, error = self._generate_raw_patch(prompt, output_file)
        attempt_result["raw_patch_content"] = raw_content
        if error:
            attempt_result["failed_files"].append({"error": f"LLM stream error: {error}" if raw_content else error})

        if raw_content.strip():
            print("\n--- Post-processing and applying patch ---")
            try:
                patch_result = self.post_process_and_apply_patch(
                    instance_id, output_file, locations_dir, playground_dir, repo_identifier,
                    repo_name, commit_id
                )
            except Exception as e:
                patch_result = None
                attempt_result["failed_files"].append({"error": f"Post-processing failed: {e}"})

            if patch_result:
                attempt_result["processed_patches"] = patch_result["processed_patches"]
                attempt_result["applied_files"] = patch_result["applied_files"]
                attempt_result["failed_files"].extend(patch_result["failed_files"])
                if attempt_result["applied_files"]:
                    attempt_result["status"] = "success" if not attempt_result["failed_files"] else "partial"
                else:
                    attempt_result["status"] = "failed"
            else:
                attempt_result["status"] = "failed"

            print("--- Finished post-processing ---")
        else:
            attempt_result["failed_files"].append({"error": "Empty LLM output"})
            attempt_result["status"] = "failed"

        return attempt_result

    def get_completion(self, prompt, stream=False):
        """统一的 LLM 调用接口"""
        messages = [{'role': 'user', 'content': prompt}]
        response_prefill = ""
        if self.api_type in ['openai', 'deepseek', 'qwen', 'openai_compat']:
            response_prefill = self._get_response_prefill()
            messages = [
                {'role': 'system', 'content': OPEN_MODEL_SYSTEM_PROMPT},
                {'role': 'user', 'content': prompt},
            ]
            if response_prefill and not stream:
                messages.append({'role': 'assistant', 'content': response_prefill})
        self.last_completion_error = None
        try:
            if self.api_type in ['openai', 'deepseek', 'qwen', 'openai_compat']:
                request_kwargs = dict(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    max_tokens=self._get_completion_max_tokens(),
                    timeout=self._get_request_timeout(),
                    stream=stream,
                )
                if self.extra_body:
                    request_kwargs["extra_body"] = self.extra_body
                response = self.client.chat.completions.create(**request_kwargs)
                if stream:
                    return response
                else:
                    content = response.choices[0].message.content or ""
                    content_for_check = self._normalize_generated_text(content)
                    if response_prefill and content_for_check.lstrip().startswith("```"):
                        return content
                    if response_prefill:
                        return response_prefill + content
                    return content
                    
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
            self.last_completion_error = str(e)
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
        parsed = self._parse_search_replace_command(command.get('command', ''))
        if parsed is None:
            return None
        search_part, replace_part = parsed
        
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

    def _parse_search_replace_command(self, command_text: str) -> Optional[Tuple[str, str]]:
        if "<<<<<<< SEARCH" not in command_text or "\n=======\n" not in command_text or ">>>>>>> REPLACE" not in command_text:
            return None
        try:
            search_replace = command_text.split("\n=======\n", 1)
            if len(search_replace) != 2:
                return None
            search_prefix = search_replace[0].split("<<<<<<< SEARCH", 1)
            if len(search_prefix) != 2:
                return None
            search_part = search_prefix[1].strip("\n")
            replace_part = search_replace[1].split(">>>>>>> REPLACE", 1)[0].strip("\n")
            return search_part, replace_part
        except Exception:
            return None

    def _load_original_file_content(self, repo_path: str, edited_file: str, commit_id: Optional[str]):
        rel_path = edited_file.replace(os.sep, "/")
        if commit_id:
            result = subprocess.run(
                ["git", "-C", repo_path, "show", f"{commit_id}:{rel_path}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0:
                return result.stdout, None

        full_file_path = os.path.join(repo_path, edited_file)
        if os.path.exists(full_file_path):
            with open(full_file_path, 'r', encoding='utf-8') as f:
                return f.read(), None
        return None, full_file_path

    def _load_allowed_context_files(self, locations_dir: str):
        allowed = set()
        try:
            json_files = sorted(glob.glob(os.path.join(locations_dir, "*.json")))
            if not json_files:
                return allowed
            with open(json_files[0], "r", encoding="utf-8") as f:
                data = json.load(f)
            related = data.get("related_entities") or {}
            for method in related.get("methods") or []:
                file_path = (method.get("file_path") or "").replace("\\", "/").strip()
                if file_path:
                    allowed.add(file_path)
        except Exception:
            return allowed
        return allowed

    def _resolve_edited_file_path(self, repo_path: str, edited_file: str, commit_id: Optional[str], allowed_files):
        normalized = edited_file.replace("\\", "/")
        content, _ = self._load_original_file_content(repo_path, normalized, commit_id)
        if content is not None:
            return normalized, content

        candidate_pool = set(allowed_files or [])
        if commit_id:
            result = subprocess.run(
                ["git", "-C", repo_path, "ls-tree", "-r", "--name-only", commit_id],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line:
                        candidate_pool.add(line)
        if not candidate_pool:
            for dirpath, _, filenames in os.walk(repo_path):
                for filename in filenames:
                    rel = os.path.relpath(os.path.join(dirpath, filename), repo_path).replace("\\", "/")
                    candidate_pool.add(rel)

        if not candidate_pool:
            return normalized, None

        wanted_dir = os.path.dirname(normalized)
        wanted_name = os.path.basename(normalized)
        wanted_ext = os.path.splitext(wanted_name)[1]
        candidates = []
        for candidate in candidate_pool:
            if wanted_ext and os.path.splitext(candidate)[1] != wanted_ext:
                continue
            score = difflib.SequenceMatcher(None, normalized, candidate).ratio()
            if wanted_dir and os.path.dirname(candidate) == wanted_dir:
                score += 0.15
            if wanted_name and os.path.basename(candidate).startswith(os.path.splitext(wanted_name)[0]):
                score += 0.1
            candidates.append((score, candidate))

        for score, candidate in sorted(candidates, reverse=True):
            if score < 0.72:
                break
            candidate_content, _ = self._load_original_file_content(repo_path, candidate, commit_id)
            if candidate_content is not None:
                print(f"Resolved missing file {normalized} -> {candidate} (score={score:.2f})")
                return candidate, candidate_content
        return normalized, None

    def _shrink_command_to_changed_window(self, command, context_lines=3):
        parsed = self._parse_search_replace_command(command.get('command', ''))
        if parsed is None:
            return None
        search_part, replace_part = parsed
        search_lines = search_part.splitlines()
        replace_lines = replace_part.splitlines()
        if not search_lines or not replace_lines:
            return None

        prefix = 0
        while (
            prefix < len(search_lines)
            and prefix < len(replace_lines)
            and search_lines[prefix] == replace_lines[prefix]
        ):
            prefix += 1

        suffix = 0
        max_suffix = min(len(search_lines) - prefix, len(replace_lines) - prefix)
        while (
            suffix < max_suffix
            and search_lines[len(search_lines) - 1 - suffix] == replace_lines[len(replace_lines) - 1 - suffix]
        ):
            suffix += 1

        if prefix == len(search_lines) and prefix == len(replace_lines):
            return None

        start = max(0, prefix - context_lines)
        search_end = min(len(search_lines), len(search_lines) - suffix + context_lines)
        replace_end = min(len(replace_lines), len(replace_lines) - suffix + context_lines)
        shrunk_search = "\n".join(search_lines[start:search_end]).strip("\n")
        shrunk_replace = "\n".join(replace_lines[start:replace_end]).strip("\n")
        if not shrunk_search or not shrunk_replace or shrunk_search == shrunk_replace:
            return None

        return {
            'command': f"<<<<<<< SEARCH\n{shrunk_search}\n=======\n{shrunk_replace}\n>>>>>>> REPLACE",
            'start_line': command.get('start_line'),
            'end_line': command.get('end_line'),
        }

    def _split_command_into_changed_windows(self, command, context_lines=2, max_windows=4):
        parsed = self._parse_search_replace_command(command.get('command', ''))
        if parsed is None:
            return []
        search_part, replace_part = parsed
        search_lines = search_part.splitlines()
        replace_lines = replace_part.splitlines()
        if not search_lines or not replace_lines:
            return []

        matcher = difflib.SequenceMatcher(a=search_lines, b=replace_lines)
        windows = []
        seen = set()
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            s0 = max(0, i1 - context_lines)
            s1 = min(len(search_lines), i2 + context_lines)
            r0 = max(0, j1 - context_lines)
            r1 = min(len(replace_lines), j2 + context_lines)
            shrunk_search = "\n".join(search_lines[s0:s1]).strip("\n")
            shrunk_replace = "\n".join(replace_lines[r0:r1]).strip("\n")
            if not shrunk_search or not shrunk_replace or shrunk_search == shrunk_replace:
                continue
            key = (shrunk_search, shrunk_replace)
            if key in seen:
                continue
            seen.add(key)
            windows.append({
                'command': f"<<<<<<< SEARCH\n{shrunk_search}\n=======\n{shrunk_replace}\n>>>>>>> REPLACE",
                'start_line': command.get('start_line'),
                'end_line': command.get('end_line'),
            })
            if len(windows) >= max_windows:
                break
        return windows

    def _normalize_edit_commands(self, edit_commands):
        """
        Drop invalid / no-op commands and keep the last revision for the same search block.
        Open models often emit an unchanged draft first and a refined edit later in the same response.
        """
        last_by_search = {}
        for idx, cmd in enumerate(edit_commands):
            parsed = self._parse_search_replace_command(cmd.get('command', ''))
            if parsed is None:
                continue
            search_part, replace_part = parsed
            search_key = search_part.strip("\n")
            replace_key = replace_part.strip("\n")
            if not search_key or not replace_key:
                continue
            if search_key == replace_key:
                continue
            last_by_search[search_key] = (idx, cmd)
        return [cmd for _, cmd in sorted(last_by_search.values(), key=lambda x: x[0])]

    def _infer_commands_from_plain_code_blocks(self, blocks, locations_dir, instance_id):
        location_file = os.path.join(locations_dir, f"{instance_id}.json")
        if not os.path.exists(location_file):
            return {}
        try:
            with open(location_file, "r", encoding="utf-8") as f:
                locate_result = json.load(f)
        except Exception:
            return {}

        methods = locate_result.get("related_entities", {}).get("methods") or []
        candidates = []
        for item in methods:
            source = (item.get("source_code") or "").strip("\n")
            file_path = item.get("file_path") or ""
            if not source or not file_path:
                continue
            first_code_line = ""
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith(("def ", "async def ", "class ")):
                    first_code_line = stripped
                    break
            if first_code_line:
                candidates.append((file_path, source, first_code_line))

        file_to_commands = {}
        for raw_block in blocks:
            block = self._sanitize_patch_block_text(raw_block)
            if not block or "<<<<<<< SEARCH" in block:
                continue
            block = block.strip("\n")
            for file_path, source, first_code_line in candidates:
                if first_code_line not in block:
                    continue
                if block.strip() == source.strip():
                    continue
                file_key = repr(file_path)
                file_to_commands.setdefault(file_key, []).append({
                    "command": f"<<<<<<< SEARCH\n{source}\n=======\n{block}\n>>>>>>> REPLACE",
                    "start_line": None,
                    "end_line": None,
                })
                break
        if file_to_commands:
            print(f"Inferred {sum(len(v) for v in file_to_commands.values())} SEARCH/REPLACE edit(s) from plain code block output.")
        return file_to_commands

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
        blocks = [self._sanitize_patch_block_text(block) for block in blocks]
        blocks = [block for block in blocks if block.strip()]

        allowed_context_files = self._load_allowed_context_files(locations_dir)

        # Collect every valid edit block so multi-file outputs can be preserved.
        file_to_commands = {}
        seen_commands = set()
        for block in blocks:
            candidate_commands = split_edit_multifile_commands([block])
            if not candidate_commands:
                continue
            for file_path_str, commands in candidate_commands.items():
                merged = file_to_commands.setdefault(file_path_str, [])
                for cmd in commands:
                    dedupe_key = f"{file_path_str}\0{json.dumps(cmd, sort_keys=True, ensure_ascii=False)}"
                    if dedupe_key in seen_commands:
                        continue
                    seen_commands.add(dedupe_key)
                    merged.append(cmd)

        if not file_to_commands:
            fallback_block = self._sanitize_patch_block_text(raw_output_text)
            if fallback_block:
                candidate_commands = split_edit_multifile_commands([fallback_block])
                for file_path_str, commands in candidate_commands.items():
                    merged = file_to_commands.setdefault(file_path_str, [])
                    for cmd in commands:
                        dedupe_key = f"{file_path_str}\0{json.dumps(cmd, sort_keys=True, ensure_ascii=False)}"
                        if dedupe_key in seen_commands:
                            continue
                        seen_commands.add(dedupe_key)
                        merged.append(cmd)

        if not file_to_commands:
            inferred_commands = self._infer_commands_from_plain_code_blocks(
                blocks, locations_dir, instance_id
            )
            for file_path_str, commands in inferred_commands.items():
                merged = file_to_commands.setdefault(file_path_str, [])
                for cmd in commands:
                    dedupe_key = f"{file_path_str}\0{json.dumps(cmd, sort_keys=True, ensure_ascii=False)}"
                    if dedupe_key in seen_commands:
                        continue
                    seen_commands.add(dedupe_key)
                    merged.append(cmd)

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
            except Exception:
                print(f"Could not parse file path: {file_path_str}")
                failed_files.append({"file": file_path_str, "error": "Could not parse file path"})
                continue

            try:
                if edited_file.startswith('playground'):
                    edited_file = '/'.join(edited_file.split('/')[2:])

                edited_file, original_content = self._resolve_edited_file_path(
                    repo_path, edited_file, commit_id, allowed_context_files
                )
                missing_path = None if original_content is not None else os.path.join(repo_path, edited_file)
                if original_content is None:
                    print(f"File to be edited not found, skipping: {missing_path or edited_file}")
                    failed_files.append({"file": edited_file, "error": "File not found"})
                    continue
                
                active_commands = self._normalize_edit_commands(edit_commands)
                if not active_commands:
                    print(f"No effective edit commands found for {edited_file}. Skipping.")
                    failed_files.append({"file": edited_file, "error": "No effective edit commands"})
                    continue
                new_content = parse_diff_edit_commands_strict(active_commands, original_content)

                if new_content == original_content:
                    shrunk_commands = []
                    changed = False
                    for cmd in active_commands:
                        shrunk = self._shrink_command_to_changed_window(cmd)
                        if shrunk is not None:
                            shrunk_commands.append(shrunk)
                            changed = True
                        else:
                            shrunk_commands.append(cmd)
                    if changed:
                        shrunk_content = parse_diff_edit_commands_strict(shrunk_commands, original_content)
                        if shrunk_content != original_content:
                            active_commands = shrunk_commands
                            new_content = shrunk_content

                if new_content == original_content:
                    windowed_commands = []
                    for cmd in active_commands:
                        pieces = self._split_command_into_changed_windows(cmd)
                        if pieces:
                            windowed_commands.extend(pieces)
                    if windowed_commands:
                        windowed_content = parse_diff_edit_commands_strict(windowed_commands, original_content)
                        if windowed_content != original_content:
                            active_commands = windowed_commands
                            new_content = windowed_content
                
                # Indentation adjustment logic
                if new_content == original_content or not self._check_syntax(new_content, self.language):
                    indent_changes = [-4, 4, -8, 8]  # 对应 -1, +1, -2, +2 缩进级别
                    for indent_change in indent_changes:
                        adjusted_commands = []
                        for cmd in active_commands:
                            adjusted = self.adjust_command_indentation(cmd, indent_change)
                            if adjusted is not None:
                                adjusted_commands.append(adjusted)
                        if not adjusted_commands:
                            continue
                        adjusted_content = parse_diff_edit_commands_strict(adjusted_commands, original_content)
                        if adjusted_content != original_content and self._check_syntax(adjusted_content, self.language):
                            active_commands = adjusted_commands
                            new_content = adjusted_content
                            break
                
                # 如果第一次缩进调整失败，尝试only_one_replace模式
                if new_content == original_content or not self._check_syntax(new_content, self.language):
                    new_content = parse_diff_edit_commands_strict(active_commands, original_content, only_one_replace=True)
                    if new_content == original_content or not self._check_syntax(new_content, self.language):
                        indent_changes = [-4, 4, -8, 8]  # 对应 -1, +1, -2, +2 缩进级别
                        for indent_change in indent_changes:
                            adjusted_commands = []
                            for cmd in active_commands:
                                adjusted = self.adjust_command_indentation(cmd, indent_change)
                                if adjusted is not None:
                                    adjusted_commands.append(adjusted)
                            if not adjusted_commands:
                                continue
                            adjusted_content = parse_diff_edit_commands_strict(adjusted_commands, original_content, only_one_replace=True)
                            if adjusted_content != original_content and self._check_syntax(adjusted_content, self.language):
                                active_commands = adjusted_commands
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
                    is_applable = applable_patch(patch_content, repo_name, commit_id, repo_path=repo_path)
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
            except Exception as e:
                print(f"Error while post-processing {edited_file}: {e}")
                failed_files.append({"file": edited_file, "error": f"Post-processing exception: {e}"})
        
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
        os.makedirs(output_dir, exist_ok=True)
        
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
            benchmark_type = "multi-swe-bench" if self.language == "java" else "swe-bench"
            dataset_info = load_instance_from_dataset(instance_id, benchmark_type)
            if dataset_info:
                repo_name = dataset_info['repo_name']
                commit_id = dataset_info['commit_id']
                print(f"✅ Found repo: {repo_name}, commit: {commit_id}")
            else:
                print(f"⚠️ Could not load dataset info for {instance_id}")
                repo_name = repo_name or ''
                commit_id = commit_id or ''

        problem_statement = self._build_issue_context(locate_result, dataset_info)
        problem_statement = problem_statement.replace('\r', '')

        # Format related code entities, with file diversity and token-budgeted prompt assembly.
        methods = []
        if locate_result and 'related_entities' in locate_result:
            methods = locate_result['related_entities'].get('methods') or []
        resolved_playground_dir = playground_dir or os.path.join(os.path.dirname(locations_dir), "playground")
        resolved_repo_identifier = repo_identifier or instance_id.rsplit('-', 1)[0].replace('--', '__')
        resolved_repo_path = os.path.join(resolved_playground_dir, resolved_repo_identifier)
        methods = self._enrich_methods_with_file_context(methods, resolved_repo_path, commit_id)
        if self.api_type == "openai_compat" and not self._prefer_ultra_compact_first():
            content_all = self._build_agentless_style_repair_context(problem_statement, methods)
            if not content_all:
                content_all = self._build_compact_repair_context(problem_statement, methods)
            if not content_all:
                content_all = self._build_repair_context(problem_statement, methods)
        elif self._prefer_ultra_compact_first():
            content_all = self._build_ultra_compact_repair_context(problem_statement, methods)
            if not content_all:
                content_all = self._build_compact_repair_context(problem_statement, methods)
            if not content_all:
                content_all = self._build_repair_context(problem_statement, methods)
        elif self._prefer_compact_first():
            content_all = self._build_compact_repair_context(problem_statement, methods)
            if not content_all:
                content_all = self._build_repair_context(problem_statement, methods)
        else:
            content_all = self._build_repair_context(problem_statement, methods)

        # Build the final prompt
        current_prompt = self._get_prompt_template().format(
            problem_statement=problem_statement,
            content=content_all if content_all else "No related code snippets found.",
            file_path_example=self.file_path_example,
            language_name=self.language_name,
            code_example=self.code_example,
            code_block_lang=self.code_block_lang
        )
        
        print("Prompt constructed. Calling LLM to generate patch...")

        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{instance_id}.diff")
        result["raw_output_file"] = output_file
        if not os.path.exists(output_file):
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("")

        first_attempt = self._run_generation_attempt(
            instance_id, current_prompt, output_file, locations_dir, playground_dir,
            repo_identifier, repo_name, commit_id
        )

        result["raw_patch_content"] = first_attempt["raw_patch_content"]
        result["processed_patches"] = first_attempt["processed_patches"]
        result["applied_files"] = first_attempt["applied_files"]
        result["failed_files"] = first_attempt["failed_files"]
        result["status"] = first_attempt["status"]

        if result["status"] == "failed":
            failure_reason = "; ".join(
                item.get("error", "")
                for item in result["failed_files"]
                if isinstance(item, dict) and item.get("error")
            ) or "no valid patch was produced"
            compact_content = self._build_compact_repair_context(problem_statement, methods)
            ultra_compact_content = self._build_ultra_compact_repair_context(problem_statement, methods)
            breadth_content = self._build_breadth_repair_context(problem_statement, methods)
            retry_variants = []
            if self._is_noop_like_failure(result):
                targeted_files = self._extract_target_files_from_raw(result.get("raw_patch_content", ""))
                targeted_content = self._build_targeted_retry_context(methods, targeted_files)
                if targeted_content:
                    retry_variants.append(("anti-noop targeted repair context", targeted_content, True))
                if breadth_content:
                    retry_variants.append(("anti-noop breadth repair context", breadth_content, True))
                if compact_content:
                    retry_variants.append(("anti-noop compact repair context", compact_content, True))
                if content_all:
                    retry_variants.append(("anti-noop current repair context", content_all, True))
            if self._is_refusal_like_failure(result):
                refusal_content = self._build_refusal_recovery_context(problem_statement, methods)
                if refusal_content:
                    retry_variants.append(("refusal-recovery repair context", refusal_content, "refusal"))
            if self._needs_broader_context_failure(result):
                if breadth_content:
                    retry_variants.append(("breadth repair context", breadth_content, False))
                if content_all:
                    retry_variants.append(("current repair context", content_all, False))
            if self._prefer_ultra_compact_first():
                if compact_content:
                    retry_variants.append(("compact repair context", compact_content, False))
            else:
                if breadth_content:
                    retry_variants.append(("breadth repair context", breadth_content, False))
                if compact_content:
                    retry_variants.append(("compact repair context", compact_content, False))
                if ultra_compact_content:
                    retry_variants.append(("ultra-compact repair context", ultra_compact_content, False))

            seen_retry_contents = set()
            deduped_retry_variants = []
            for retry_label, retry_content, no_op_failure in retry_variants:
                if not retry_content:
                    continue
                key = (retry_content, no_op_failure)
                if key in seen_retry_contents:
                    continue
                seen_retry_contents.add(key)
                deduped_retry_variants.append((retry_label, retry_content, no_op_failure))
            if self._prefer_ultra_compact_first():
                deduped_retry_variants = deduped_retry_variants[:1]

            for retry_label, retry_content, no_op_failure in deduped_retry_variants:
                if not retry_content:
                    continue
                refusal_failure = no_op_failure == "refusal"
                retry_problem_statement = self._build_retry_problem_statement(
                    problem_statement,
                    failure_reason,
                    no_op_failure=(no_op_failure is True),
                    refusal_failure=refusal_failure,
                )
                retry_prompt = self._get_prompt_template().format(
                    problem_statement=retry_problem_statement,
                    content=retry_content,
                    file_path_example=self.file_path_example,
                    language_name=self.language_name,
                    code_example=self.code_example,
                    code_block_lang=self.code_block_lang,
                )
                print(f"\nRetrying with {retry_label}...")
                retry_attempt = self._run_generation_attempt(
                    instance_id, retry_prompt, output_file, locations_dir, playground_dir,
                    repo_identifier, repo_name, commit_id
                )
                if retry_attempt["status"] != "failed" or retry_attempt["raw_patch_content"].strip():
                    result["raw_patch_content"] = retry_attempt["raw_patch_content"]
                    result["processed_patches"] = retry_attempt["processed_patches"]
                    result["applied_files"] = retry_attempt["applied_files"]
                    result["failed_files"] = retry_attempt["failed_files"]
                    result["status"] = retry_attempt["status"]
                if result["status"] != "failed":
                    break

        if result["status"] != "success":
            self._persist_failure_artifacts(result, output_file)
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
    parser.add_argument("--api_type", type=str, default="deepseek", choices=["openai", "anthropic", "deepseek", "qwen", "openai_compat"], help="API type to use (default: deepseek)")
    parser.add_argument("--temperature", type=float, default=0.3, help="Temperature for LLM generation (default: 0.3)")
    parser.add_argument("--model", type=str, default=None, help="Override model name for the selected API")
    parser.add_argument("--base-url", type=str, default=None, help="Override base URL for OpenAI-compatible APIs")
    parser.add_argument("--api-key-env", type=str, default=None, help="Environment variable name that stores the API key")
    parser.add_argument("--extra-body-json", type=str, default=None, help="Extra JSON body for OpenAI-compatible APIs")
    
    args = parser.parse_args()

    # The output directory for patches will be inside the run directory
    patch_dir = os.path.join(os.path.dirname(args.final_locations_dir), "patches")

    # Initialize the repairer with language and API type parameters
    repairer = CodeRepair(
        language=args.language,
        api_type=args.api_type,
        temperature=args.temperature,
        model_name_override=args.model,
        base_url_override=args.base_url,
        api_key_env=args.api_key_env,
        extra_body_json=args.extra_body_json,
    )

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
