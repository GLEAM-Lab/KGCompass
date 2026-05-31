import os
import json
import openai
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

Please note that the *SEARCH/REPLACE* edit REQUIRES PROPER INDENTATION. If you would like to add a line like '        print(x)' ({language_name}), you must fully write that out, with all those spaces before the code!
Wrap the *SEARCH/REPLACE* edit in blocks ```{code_block_lang}...```.
"""

OPEN_MODEL_SYSTEM_PROMPT = (
    "You are a repository repair agent for SWE-bench-style tasks. "
    "Return only the final SEARCH/REPLACE edit blocks inside fenced code blocks. "
    "Do not output analysis, plans, bullet points, or natural-language explanations."
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
- Use only file paths that appear in the provided context.
- SEARCH blocks must match the existing code exactly, including indentation.
- SEARCH blocks should usually be the smallest exact contiguous snippet that can be safely replaced, ideally about 3-15 lines.
- Do not rewrite an entire function or method unless the whole function is clearly required and copied exactly from the provided context.
- Prefer small exact SEARCH blocks copied verbatim from the context.
- Every REPLACE block must differ from its SEARCH block in at least one actual code token or character.
- Output only fenced ```{code_block_lang}``` blocks containing the final edits.
- Do not include any prose before, between, or after the code blocks.

Format example:
```{code_block_lang}
### {file_path_example}
<<<<<<< SEARCH
old code
=======
new code
>>>>>>> REPLACE
```
"""


class CodeRepair:
    def __init__(self, language="python"):
        self.temperature = TEMPERATURE
        self.top_p = TOP_P
        self.model = MODEL_NAME # From config
        self.MAX_INPUT_LENGTH = MAX_INPUT_LENGTH
        self.last_completion_error = None
        # Create a client instance pointing to the OpenAI-compatible endpoint
        self.client = openai.OpenAI(api_key=BAILIAN_API_KEY, base_url=DEEPSEEK_BASE_URL)
        
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
        if os.path.exists(output_file):
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

    def _method_identity(self, item):
        return (
            item.get("file_path", ""),
            item.get("signature", ""),
            item.get("start_line"),
            item.get("end_line"),
        )

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
                sections.append(self._render_single_method_context(item, is_primary=(idx < 2)))
        return "\n".join(sections).strip() + "\n"

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
        if "qwen3-coder-480b-a35b-instruct" in model_name:
            return 3072
        if "glm-5" in model_name:
            return 4096
        if "kimi" in model_name:
            return 3072
        return 4096

    def _get_request_timeout(self):
        model_name = (self.model or "").lower()
        if "glm-5" in model_name:
            return 480
        if "qwen3-coder-480b-a35b-instruct" in model_name:
            return 300
        if "kimi" in model_name:
            return 300
        return 240

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
            return 700 if is_primary else 280
        if "glm-5" in model_name:
            return 900 if is_primary else 360
        if "kimi" in model_name:
            return 700 if is_primary else 280
        return 1000 if is_primary else 400

    def _render_single_method_context(self, item, is_primary=True):
        source = (item.get("source_code") or "").rstrip()
        source_limit = self._get_method_source_token_limit(is_primary)
        rendered_source = self._truncate_source_preserve_ends(source, source_limit)
        similarity = item.get("similarity")
        parts = [
            f"- signature : {item.get('signature', '')}",
            f"- start_line : {item.get('start_line')}",
            f"- end_line : {item.get('end_line')}",
        ]
        if similarity is not None:
            parts.append(f"- similarity : {similarity:.4f}")
        parts.append(f"- source_mode : {'full-or-primary' if is_primary else 'compressed-secondary'}")
        parts.append(f"```{self.code_block_lang}")
        parts.append(rendered_source)
        parts.append("```")
        return "\n".join(parts)

    def _load_original_file_content(self, repo_path: str, edited_file: str, commit_id):
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

    def get_completion(self, prompt, stream=False):
        messages = [{'role': 'user', 'content': prompt}]
        if self.api_type in ["openai_compat", "qwen", "deepseek", "openai"]:
            messages = [
                {'role': 'system', 'content': OPEN_MODEL_SYSTEM_PROMPT},
                {'role': 'user', 'content': prompt},
            ]
        self.last_completion_error = None
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                top_p=self.top_p,
                max_tokens=self._get_completion_max_tokens(),
                timeout=self._get_request_timeout(),
                stream=stream,
            )
            if stream:
                return response
            else:
                return response.choices[0].message.content
        except Exception as e:
            self.last_completion_error = str(e)
            print(f"An error occurred while calling the LLM API: {e}")
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
            
            original_content, missing_path = self._load_original_file_content(repo_path, edited_file, commit_id)

            if original_content is None:
                print(f"File to be edited not found, skipping: {missing_path or edited_file}")
                failed_files.append({"file": edited_file, "error": "File not found"})
                continue
            
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

        problem_statement = self._select_problem_statement(locate_result, dataset_info)
        problem_statement = problem_statement.replace('\r', '')

        # Format related code entities, with file diversity and token-budgeted prompt assembly.
        methods = []
        if locate_result and 'related_entities' in locate_result:
            methods = locate_result['related_entities'].get('methods') or []
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
        
        # Get completion from LLM
        try:
            os.makedirs(output_dir, mode=0o755, exist_ok=True)
        except PermissionError as e:
            print(f"❌ 无法创建输出目录 {output_dir}: {e}")
            print(f"   请检查目录权限或使用 sudo 运行")
            raise
        output_file = os.path.join(output_dir, f"{instance_id}.diff")
        result["raw_output_file"] = output_file
        if not os.path.exists(output_file):
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("")
        stream = self.get_completion(current_prompt, stream=True)

        if stream:
            print(f"--- LLM raw output ---")
            raw_content = ""
            stream_error = None
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    for chunk in stream:
                        content = chunk.choices[0].delta.content or ""
                        f.write(content)
                        raw_content += content
                        print(content, end='', flush=True)
            except PermissionError as e:
                print(f"\n❌ 无法写入补丁文件 {output_file}: {e}")
                print(f"   请检查文件权限或目录权限")
                print(f"   尝试运行: chmod -R 755 {os.path.dirname(output_file)}")
                raise
            except Exception as e:
                stream_error = str(e)
                print(f"\nStreaming interrupted: {e}")
            
            print(f"\n--- End of LLM raw output ---")
            print(f"Successfully generated raw patch and saved to {output_file}")
            
            # 保存原始patch内容
            result["raw_patch_content"] = raw_content
            if stream_error:
                result["failed_files"].append({"error": f"LLM stream error: {stream_error}"})
                result["error_summary"] = f"LLM stream error: {stream_error}"
            
            if raw_content.strip():
                print("\n--- Post-processing and applying patch ---")
                try:
                    patch_result = self.post_process_and_apply_patch(
                        instance_id, output_file, locations_dir, playground_dir, repo_identifier, 
                        repo_name, commit_id
                    )
                except Exception as e:
                    patch_result = None
                    result["failed_files"].append({"error": f"Post-processing failed: {e}"})
                
                if patch_result:
                    result["processed_patches"] = patch_result["processed_patches"]
                    result["applied_files"] = patch_result["applied_files"]
                    result["failed_files"].extend(patch_result["failed_files"])
                    
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
            else:
                result["status"] = "failed"
                result["failed_files"].append({"error": "Empty LLM output"})
                result["error_summary"] = "Empty LLM output"
            
            if raw_content.strip():
                print("--- Finished post-processing ---")

            if result["status"] != "success":
                self._persist_failure_artifacts(result, output_file)
            
            # 保存结果到JSONL
            if save_to_jsonl:
                self._save_result_to_jsonl(result, output_dir)
                
        else:
            print("Failed to get a valid response from the model.")
            result["status"] = "failed"
            api_error = self.last_completion_error or "Failed to get LLM response"
            result["failed_files"].append({"error": api_error})
            result["error_summary"] = api_error
            result["raw_patch_content"] = ""
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
    
    args = parser.parse_args()

    # The output directory for patches will be inside the run directory
    patch_dir = os.path.join(os.path.dirname(args.final_locations_dir), "patches")

    # Initialize the repairer with language parameter
    repairer = CodeRepair(language=args.language)

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
