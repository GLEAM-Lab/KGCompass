import os
import json
import openai
import difflib
import subprocess
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
)

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
1. The file path
2. The start of search block: <<<<<<< SEARCH
3. A contiguous chunk of lines to search for in the existing source code
4. The dividing line: =======
5. The lines to replace into the source code
6. The end of the replace block: >>>>>>> REPLACE

Here is an example for python:

```python
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
```

IMPORTANT NOTES:
1. Line numbers start from 1 (not 0)
2. The SEARCH block must match the exact content and indentation from the original file
3. The REPLACE block must maintain proper indentation relative to the surrounding code
4. Only include the specific lines that need to be changed
5. If modifying a method, include its entire definition in both blocks if it helps clarity
6. Only generate edits when actual changes are needed
7. Verify that the replacement code is actually different from the original

Please note that the *SEARCH/REPLACE* edit REQUIRES PROPER INDENTATION. If you would like to add a line like '        print(x)', you must fully write that out, with all those spaces before the code!
Wrap the *SEARCH/REPLACE* edit in blocks ```python...```.
"""


class CodeRepair:
    def __init__(self):
        self.temperature = TEMPERATURE
        self.top_p = TOP_P
        self.model = MODEL_NAME # From config
        self.MAX_INPUT_LENGTH = MAX_INPUT_LENGTH
        # Create a client instance pointing to the OpenAI-compatible endpoint
        self.client = openai.OpenAI(api_key=BAILIAN_API_KEY, base_url=DEEPSEEK_BASE_URL)

    def get_completion(self, prompt, stream=False):
        messages = [{'role': 'user', 'content': prompt}]
        try:
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
        except Exception as e:
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

    def post_process_and_apply_patch(self, instance_id, raw_output_path, locations_dir, playground_dir=None, repo_identifier=None):
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
            return
        
        with open(raw_output_path, 'r', encoding='utf-8') as f:
            raw_output_text = f.read()

        blocks = extract_python_blocks(raw_output_text)
        file_to_commands = split_edit_multifile_commands(blocks)

        if not file_to_commands:
            print("No edit commands found in LLM output.")
            return

        for file_path_str, edit_commands in file_to_commands.items():
            try:
                edited_file = eval(file_path_str)
            except:
                print(f"Could not parse file path: {file_path_str}")
                continue

            if edited_file.startswith('..'):
                edited_file = '/'.join(edited_file.split('/')[2:])
            
            full_file_path = os.path.join(repo_path, edited_file)

            if not os.path.exists(full_file_path):
                print(f"File to be edited not found, skipping: {full_file_path}")
                continue

            with open(full_file_path, 'r', encoding='utf-8') as f:
                original_content = f.read()
            
            new_content = parse_diff_edit_commands_strict(edit_commands, original_content)
            
            # Indentation adjustment logic from user snippet
            if new_content == original_content or not check_syntax(new_content):
                indent_changes = [-4, 4, -8, 8]
                for indent_change in indent_changes:
                    adjusted_commands = [
                        self.adjust_command_indentation(cmd, indent_change) 
                        for cmd in edit_commands
                    ]
                    adjusted_content = parse_diff_edit_commands_strict(adjusted_commands, original_content)
                    if adjusted_content != original_content and check_syntax(adjusted_content):
                        new_content = adjusted_content
                        break
            
            if new_content == original_content or not check_syntax(new_content):
                new_content = parse_diff_edit_commands_strict(edit_commands, original_content, only_one_replace=True)
                if new_content == original_content or not check_syntax(new_content):
                    indent_changes = [-4, 4, -8, 8]
                    for indent_change in indent_changes:
                        adjusted_commands = [
                            self.adjust_command_indentation(cmd, indent_change) 
                            for cmd in edit_commands
                        ]
                        adjusted_content = parse_diff_edit_commands_strict(adjusted_commands, original_content, only_one_replace=True)
                        if adjusted_content != original_content and check_syntax(adjusted_content):
                            new_content = adjusted_content
                            break

            if new_content != original_content and check_syntax(new_content):
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

                # Apply the patch using `git apply`
                proc = subprocess.run(
                    ['git', 'apply', '--ignore-whitespace', abs_diff_file_path],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    encoding='utf-8'
                )
                if proc.returncode == 0:
                    print(f"Successfully applied patch for {edited_file} to {repo_path}")
                else:
                    print(f"Failed to apply patch for {edited_file} to {repo_path}.")
                    print(f"Stderr: {proc.stderr}")
                    # Try to apply with 3-way merge
                    print("Trying to apply with 3-way merge...")
                    proc_3way = subprocess.run(
                        ['git', 'apply', '--3way', abs_diff_file_path],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        encoding='utf-8'
                    )
                    if proc_3way.returncode == 0:
                        print(f"Successfully applied patch for {edited_file} with 3-way merge.")
                    else:
                        print(f"Failed to apply patch for {edited_file} with 3-way merge.")
                        print(f"Stderr: {proc_3way.stderr}")

            else:
                print(f"Failed to generate a valid patch for {edited_file}. Skipping.")

    def process_instance(self, instance_id, locations_dir, output_dir, playground_dir=None, repo_identifier=None):
        """
        Processes a single instance to generate a patch.
        """
        print(f"Processing instance: {instance_id}")
        
        # Construct the path to the location file
        location_file = os.path.join(locations_dir, f"{instance_id}.json")
        if not os.path.exists(location_file):
            print(f"Error: Location file not found at {location_file}")
            return

        with open(location_file, 'r') as f:
            locate_result = json.load(f)

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
            content=content_all if content_all else "No related code snippets found."
        )
        
        print("Prompt constructed. Calling LLM to generate patch...")
        
        # Get completion from LLM
        stream = self.get_completion(current_prompt, stream=True)

        if stream:
            os.makedirs(output_dir, exist_ok=True)
            output_file = os.path.join(output_dir, f"{instance_id}.patch")
            
            print(f"--- LLM raw output ---")
            with open(output_file, 'w', encoding='utf-8') as f:
                for chunk in stream:
                    content = chunk.choices[0].delta.content or ""
                    f.write(content)
                    print(content, end='', flush=True)
            
            print(f"\n--- End of LLM raw output ---")
            print(f"Successfully generated raw patch and saved to {output_file}")
            
            print("\n--- Post-processing and applying patch ---")
            self.post_process_and_apply_patch(instance_id, output_file, locations_dir, playground_dir, repo_identifier)
            print("--- Finished post-processing ---")
        else:
            print("Failed to get a valid response from the model.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Code Repair Script")
    parser.add_argument("final_locations_dir", type=str, help="Directory containing the final location files.")
    parser.add_argument("--instance_id", required=True, type=str, help="The specific instance ID to process.")
    parser.add_argument("--playground_dir", type=str, default=None, help="Root directory where repositories are located (default: sibling 'playground' of final_locations_dir).")
    parser.add_argument("--repo_identifier", type=str, default=None, help="Repository directory name inside playground (e.g., 'astropy__astropy'). If omitted, it will be derived from instance_id.")
    
    args = parser.parse_args()

    # The output directory for patches will be inside the run directory
    patch_dir = os.path.join(os.path.dirname(args.final_locations_dir), "patches")

    # Initialize the repairer
    repairer = CodeRepair()

    # Process the single instance
    repairer.process_instance(
        instance_id=args.instance_id,
        locations_dir=args.final_locations_dir,
        output_dir=patch_dir,
        playground_dir=args.playground_dir,
        repo_identifier=args.repo_identifier
    )

