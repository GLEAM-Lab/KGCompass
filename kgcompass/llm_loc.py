import json
import os
import sys
from datasets import load_dataset
import openai
from utils import get_commit_method_by_signature, extract_json_code
from config import (
    DATASET_NAME,
    LLM_MODELS,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_API_KEY,
    QWEN_API_KEY,
    QWEN_BASE_URL,
    CLAUDE_API_KEY,
    GITHUB_TOKEN,
    MAX_TOKENS,
    DIVERSE_TEMPERATURE,
    LLM_LOC_MAX,
    BAILIAN_API_KEY,
    BAILIAN_AGENT_KEY,
    MODEL_MAP,
    NEO4J_CONFIG,
    MAX_INPUT_LENGTH,
)
from concurrent.futures import ThreadPoolExecutor, as_completed
import neo4j
import http
import dashscope

class PreFaultLocalization:
    def __init__(self, instance_id, api_type, dataset_name: str | None = None):
        # Initialize API client
        if api_type == "openai":
            self.client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        elif api_type == "anthropic":
            self.client = openai.OpenAI(api_key=CLAUDE_API_KEY)
        elif api_type in "deepseek":
            self.client = openai.OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        elif api_type == "qwen":
            self.client = openai.OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
        elif api_type == "deepseek-r1":
            self.client = None
        
        self.api_type = api_type
        self.instance_id = instance_id
        
        # Allow overriding dataset name (e.g., Daoguang/Multi-SWE-bench)
        self.dataset_name = dataset_name or DATASET_NAME

        # Determine proper split based on dataset
        split_name = 'test'
        if 'multi-swe-bench' in self.dataset_name.lower():
            split_name = 'java_verified'

        ds = load_dataset(self.dataset_name)
        if split_name not in ds:
            # Fallback: first available split
            split_name = list(ds.keys())[0]

        self.dataset = {item['instance_id']: item for item in ds[split_name]}
        self.target_sample = self.dataset.get(self.instance_id)

        # Very simple language detection
        self.language = 'java' if 'multi-swe-bench' in self.dataset_name.lower() else 'python'

    def generate(self, prompt):
        """Unified interface for generating responses"""
        messages = [{"role": "user", "content": prompt}]
        
        if self.api_type in ['openai', 'deepseek', 'qwen']:
            response = self.client.chat.completions.create(
                model=LLM_MODELS[self.api_type],
                messages=messages,
                temperature=DIVERSE_TEMPERATURE,
            )
            return response.choices[0].message.content
        elif self.api_type == 'anthropic':
            response = self.client.messages.create(
                model=LLM_MODELS[self.api_type],
                max_tokens=MAX_TOKENS,
                messages=messages,
                temperature=DIVERSE_TEMPERATURE
            )
            return response.content[0].text

    def pre_locate(self, updated_description):
        """Preliminary fault localization"""
        if self.language == 'python':
            prompt = f"""Based on the following bug description, predict potential relevant code locations:

Description:
{updated_description}

Please provide a JSON array containing the predicted locations where the bug fix is needed. Each location should include the full file path and the full method name.

The method field should be one of these formats:
- `package.module.Class.method_name`           # For class methods
- `package.module.function_name`               # For standalone functions
- `package.module.Class.class_level_attribute` # For class-level attributes (defined outside of functions)
- `package.module.MODULE_LEVEL_VALUE`          # For module-level variables

Format:
```json
[
    {{
        "file_path": "package/submodule/file.py",
        "method": "package.module.Class.method_name"
    }},
    {{
        "file_path": "package/other/file.py",
        "method": "package.module.MODULE_LEVEL_VALUE"
    }}
]
```

Note:
- Consider code elements defined outside of functions:
  * Class-level attributes and members
  * Module-level variables and values
  * Function and method definitions
- Predict logical locations even if not explicitly mentioned
- Focus on core functionality rather than test files
- When names are not clear, provide multiple reasonable guesses based on common naming conventions
- List the most likely locations first (primary location should be the first item)
- Include both primary and related locations (up to 10 total)
"""
        else:
            # Java version (concise – follows same structure but Java-specific examples)
            prompt = f"""Based on the following bug description, predict potential relevant code locations:

Description:
{updated_description}

Please provide a JSON array containing the predicted locations where the bug fix is needed. Each location should include the full file path and the full method name.

The method field should be one of these formats for Java:
- `com.package.Class#methodName`           # For class methods
- `com.package.Class.FIELD_NAME`           # For static / constant fields
- `com.package.Class`                      # For entire class when unsure

Format:
```json
[
    {{
        "file_path": "src/main/java/com/example/MyClass.java",
        "method": "com.example.MyClass#myMethod"
    }}
]
```

Keep the rest of the instructions identical to the Python prompt (ordering, note section, limit {LLM_LOC_MAX}).
"""

        result = self.generate(prompt)
        return result

class LlmLoc:
    def __init__(self, api_type, num_workers):
        self.api_type = api_type
        self.num_workers = num_workers
        self.model = MODEL_MAP.get(self.api_type, self.api_type)
        if self.api_type in ["deepseek", "qwen", "yi"]:
            self.api_key = BAILIAN_API_KEY
            self.agent_key = BAILIAN_AGENT_KEY
        else:
            raise ValueError(f"Unsupported API type: {self.api_type}")
        self.MAX_INPUT_LENGTH = MAX_INPUT_LENGTH['bailian']

    def get_completion(self, prompt, retries=5, delay=10):
        if self.api_type in ["deepseek", "qwen", "yi"]:
            dashscope.api_key = self.api_key
            try:
                response = dashscope.Generation.call(
                    model=self.model,
                    prompt=prompt,
                    api_key=self.api_key,
                    agent_key=self.agent_key,
                )
                if response.status_code == http.HTTPStatus.OK:
                    return response.output['text']
                else:
                    print(f"Error: {response.code} - {response.message}")
                    return ""
            except Exception as e:
                print(f"An error occurred: {e}")
                return ""
        else:
            raise ValueError(f"Unsupported API type: {self.api_type}")

if __name__ == "__main__":
    # Support optional --no-kg flag to skip using kg_locations
    use_kg = '--no-kg' not in sys.argv

    # Remove flag for easier positional parsing
    argv_clean = [a for a in sys.argv[1:] if a != '--no-kg']

    if len(argv_clean) < 2:
        print("Usage: python llm_loc.py <api_type> [num_threads] <directory> [dataset_name] [--no-kg]")
        sys.exit(1)
    
    api_type = argv_clean[0]

    # Determine if second arg is num_threads (int) or directory
    arg2 = argv_clean[1]
    if arg2.isdigit():
        num_threads = int(arg2)
        directory_arg_index = 2
    else:
        num_threads = 1
        directory_arg_index = 1

    # directory path
    directory = argv_clean[directory_arg_index]

    dataset_name_cli = argv_clean[directory_arg_index + 1] if len(argv_clean) > directory_arg_index + 1 else DATASET_NAME
    
    from concurrent.futures import ThreadPoolExecutor
    from tqdm import tqdm
    
    # Load dataset once to get all instance IDs for progress bar
    ds_main = load_dataset(dataset_name_cli)
    main_split = 'test'
    if 'multi-swe-bench' in dataset_name_cli.lower():
        main_split = 'java_verified'
    if main_split not in ds_main:
        main_split = list(ds_main.keys())[0]

    instance_ids = sorted(ds_main[main_split]['instance_id']) if isinstance(ds_main[main_split], list) else sorted([item['instance_id'] for item in ds_main[main_split]])

    def process_instance(instance_id):
        # Determine the output path based on use_kg
        if not use_kg:
            output_file_path = os.path.join(directory, f"{instance_id}-llm_loc.json")
        else:
            # This is the file that llm_loc.py generates as its final output in the KG path
            output_file_path = os.path.join(directory, f"{instance_id}-result.json")

        # Check if the determined output file already exists
        if os.path.exists(output_file_path):
            message = f"Skipping {instance_id}: Output file {output_file_path} already exists."
            return message

        print(f"Processing {instance_id}")
        pre_fl = PreFaultLocalization(instance_id, api_type, dataset_name_cli)
        if pre_fl.target_sample is None:
            return f"Error: Could not find instance {instance_id} in dataset"

        # If not using KG results, directly call LLM and save predictions
        if not use_kg:
            problem_statement = pre_fl.target_sample.get('problem_statement', '') or pre_fl.target_sample.get('text', '')
            raw_llm_output = pre_fl.pre_locate(problem_statement)
            
            print(f"DEBUG: Raw LLM output for {instance_id} (--no-kg) PRE-EXTRACTION:\\n{raw_llm_output}")
            json_string_extracted = extract_json_code(raw_llm_output)
            print(f"DEBUG: Extracted JSON string for {instance_id} (--no-kg) POST-EXTRACTION:\\n{json_string_extracted}")

            llm_predictions_list = []
            try:
                llm_predictions_list = json.loads(json_string_extracted)
                if not isinstance(llm_predictions_list, list): # Ensure it's a list as expected
                    print(f"Warning: LLM output for {instance_id} (--no-kg) was not a list after parsing. Got: {type(llm_predictions_list)}")
                    llm_predictions_list = [] # Default to empty list to avoid iteration errors
            except json.JSONDecodeError as e:
                print(f"Error: Failed to parse JSON from LLM output for {instance_id} (--no-kg). Error: {e}")
                # Save an error structure 
                error_output = {
                    "error": "Failed to parse JSON from LLM output.",
                    "json_decode_error_details": str(e),
                    "extracted_json_string": json_string_extracted,
                    "raw_llm_output": raw_llm_output,
                    "instance_id": pre_fl.instance_id,
                    "processed_with_no_kg": True,
                    "llm_api_type": pre_fl.api_type,
                }
                with open(output_file_path, 'w') as f_out:
                    json.dump(error_output, f_out, indent=2)
                return f"Saved error log for {instance_id} due to JSON parsing failure."

            # Initialize GitHub connection (similar to KG path)
            g = Github(GITHUB_TOKEN)
            github_repo = None
            commit = None
            if pre_fl.target_sample and 'repo' in pre_fl.target_sample and 'base_commit' in pre_fl.target_sample:
                try:
                    github_repo = g.get_repo(pre_fl.target_sample['repo'])
                    commit = github_repo.get_commit(pre_fl.target_sample['base_commit'])
                except Exception as e:
                    print(f"Warning: Could not get GitHub repo/commit for {instance_id}: {e}")
            
            final_result_no_kg = {
                "instance_id": pre_fl.instance_id,
                "repo": pre_fl.target_sample.get('repo'),
                "base_commit": pre_fl.target_sample.get('base_commit'),
                "problem_statement_used": problem_statement,
                "processed_with_no_kg": True,
                "llm_api_type": pre_fl.api_type,
                "related_entities": {
                    "methods": [],
                    "issues": [],
                    "pull_requests": [],
                    "commits": [],
                    "source_files": []
                }
            }

            cnt = 0
            if isinstance(llm_predictions_list, list): # Double check it's a list
                for item in llm_predictions_list:
                    if not isinstance(item, dict) or 'file_path' not in item or 'method' not in item:
                        print(f"Warning: Skipping invalid item in LLM prediction list for {instance_id}: {item}")
                        continue

                    method_signature_from_llm = item['method']
                    file_path_from_llm = item['file_path']
                    
                    method_detail_from_github = None
                    if pre_fl.language == 'python' and github_repo and commit:
                        try:
                            method_detail_from_github = get_commit_method_by_signature(github_repo, commit, file_path_from_llm, method_signature_from_llm)
                        except Exception as e:
                            print(f"Warning: get_commit_method_by_signature failed for {method_signature_from_llm} in {file_path_from_llm}: {e}")
                            method_detail_from_github = None
                    
                    method_entry = {
                        "original_signature": method_signature_from_llm,
                        "file_path": file_path_from_llm, # Retain LLM's file_path reference
                        "type": "method",
                        "similarity": 1.0 # Default similarity for direct LLM prediction
                    }

                    if method_detail_from_github:
                        method_entry.update(method_detail_from_github) # Adds name, start_line, end_line, code_snippet etc.
                        method_entry["path"] = [{
                            "start_node": "root",
                            "description": "points to method",
                            "type": "INFERENCE",
                            "end_node": method_detail_from_github.get('name', method_signature_from_llm) # Use GitHub name if available
                        }]
                    else:
                        # Fallback if GitHub details couldn't be fetched
                        method_entry["name"] = method_signature_from_llm
                        method_entry["start_line"] = None
                        method_entry["end_line"] = None
                        method_entry["code_snippet"] = None
                        method_entry["path"] = [{
                            "start_node": "root",
                            "description": "points to method",
                            "type": "INFERENCE",
                            "end_node": method_signature_from_llm
                        }]
                    
                    final_result_no_kg['related_entities']['methods'].append(method_entry)
                    cnt += 1
                    if cnt >= LLM_LOC_MAX:
                        break
            
            with open(output_file_path, 'w') as f_out:
                json.dump(final_result_no_kg, f_out, indent=2)
            return f"Saved structured predictions without KG for {instance_id}"

        # --- original KG-dependent workflow ---
        if not os.path.exists('kg_locations/' + instance_id + '-result.json'):
            print('Location file does not exist')
            return f"Skip {instance_id}"
        locate_result = json.load(open('kg_locations/' + instance_id + '-result.json', 'r'))
        
        # Check for existing llm_hint.txt
        llm_hint_path = f'swe_bench_samples/{instance_id}/llm_hint.txt'
        if os.path.exists(llm_hint_path):
            print(f"Loading existing llm_hint.txt for {instance_id}")
            with open(llm_hint_path, 'r') as f:
                result = f.read()
                
            # Try parsing JSON, regenerate if fails
            try:
                json_str = extract_json_code(result)
                llm_hint = json.loads(json_str)
            except:
                print(f"Failed to parse existing llm_hint.txt, regenerating...")
                hint = pre_fl.target_sample['problem_statement']
                
                if locate_result['related_entities'].get('issues'):
                    sorted_issues = sorted(
                        locate_result['related_entities']['issues'],
                        key=lambda x: x['similarity'],
                        reverse=True
                    )
                    hint = f"\n### {sorted_issues[0]['title']}\n{sorted_issues[0]['content']}\n\n## Related Issues"
                    for issue in sorted_issues[1:3]:
                        hint += f"\n### {issue['title']}\n{issue['content']}"
                else:
                    hint = pre_fl.target_sample['problem_statement']
                print(hint)
                result = pre_fl.pre_locate(hint)
                print(result)
                json_str = extract_json_code(result)
                llm_hint = json.loads(json_str)
        else:
            hint = pre_fl.target_sample['problem_statement']
            
            # If there are related issues, add descriptions of top 3 most similar issues
            if locate_result['related_entities'].get('issues'):
                sorted_issues = sorted(
                    locate_result['related_entities']['issues'],
                    key=lambda x: x['similarity'],
                    reverse=True
                )
                hint = f"\n### {sorted_issues[0]['title']}\n{sorted_issues[0]['content']}\n\n## Related Issues"
                for issue in sorted_issues[1:3]:
                    hint += f"\n### {issue['title']}\n{issue['content']}"
            else:
                hint = pre_fl.target_sample['problem_statement']
            print(hint)
            result = pre_fl.pre_locate(hint)
            print(result)
            json_str = extract_json_code(result)
            llm_hint = json.loads(json_str)
                
        # Get repository information
        repo = pre_fl.target_sample['repo']
        commit_id = pre_fl.target_sample['base_commit']
        g = Github(GITHUB_TOKEN)
        github_repo = g.get_repo(repo)
        commit = github_repo.get_commit(commit_id)
        
        # Get detailed information for each method and add to locate_result
        cnt = 0
        for item in llm_hint:
            method_signature = item['method']
            file_path = item['file_path']
            # get_commit_method_by_signature 目前仅支持 Python
            if pre_fl.language != 'python':
                method = None
            else:
                try:
                    method = get_commit_method_by_signature(github_repo, commit, file_path, method_signature)
                except Exception:
                    method = None
            if method is not None:
                cnt += 1
                if cnt > LLM_LOC_MAX:
                    break
                method['path'] = [{
                    "start_node": "root",
                    "description": "points to method",
                    "type": "INFERENCE",
                    "end_node": method['name']
                }]
                method['type'] = 'method'
                method['similarity'] = 1.0
                locate_result['related_entities']['methods'].append(method)
        
        # Save updated locate_result
        with open(output_file_path, 'w') as f:
            json.dump(locate_result, f, indent=2)
        
        return f"Successfully processed {instance_id}"
    
    # Use thread pool to process instances
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        results = list(tqdm(
            executor.map(process_instance, instance_ids),
            total=len(instance_ids),
            desc="Processing instances"
        ))
    
    # Print result summary
    for result in results:
        print(result)
