import json
import os
import argparse
from datasets import load_dataset
import openai
from utils import get_commit_method_by_signature, extract_json_code
from config import (
    DATASET_NAME,
    DEEPSEEK_BASE_URL,
    GITHUB_TOKEN,
    TEMPERATURE,
    TOP_P,
    LLM_LOC_MAX,
    BAILIAN_API_KEY,
    MODEL_NAME,
    CANDIDATE_LOCATIONS_MAX,
)
from utils import format_entity_content
from github import Github

class PreFaultLocalization:
    def __init__(self, instance_id: str):
        self.instance_id = instance_id
        self.dataset_name = DATASET_NAME
        self.target_sample = self._load_target_sample()
        if self.target_sample:
            self.language = self.target_sample.get('language', 'python').lower()
        
        self.model_name = MODEL_NAME
        # Create a client instance pointing to the OpenAI-compatible endpoint
        self.client = openai.OpenAI(api_key=BAILIAN_API_KEY, base_url=DEEPSEEK_BASE_URL)

    def _load_target_sample(self):
        split_name = 'test'
        if 'multi-swe-bench' in self.dataset_name.lower():
            split_name = 'java_verified'

        ds = load_dataset(self.dataset_name, split=split_name)
        self.dataset = {item['instance_id']: item for item in ds}
        return self.dataset.get(self.instance_id)

    def generate(self, prompt, stream=False):
        """Unified interface for generating responses via OpenAI-compatible endpoint"""
        messages = [{'role': 'user', 'content': prompt}]
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=TEMPERATURE,
                top_p=TOP_P,
                stream=stream
            )

            if stream:
                collected_content = ""
                for chunk in response:
                    content = chunk.choices[0].delta.content or ""
                    print(content, end='', flush=True)
                    collected_content += content
                print() # for a newline
                return collected_content
            else:
                return response.choices[0].message.content
        except Exception as e:
            print(f"An error occurred while calling the LLM API: {e}")
            return None

    def pre_locate(self, updated_description, stream=False):
        # This prompt is now universal and will be enhanced by KG context
        prompt_template = """Based on the following bug description and context from a Knowledge Graph, predict potential relevant code locations.
The Knowledge Graph has provided potentially related issues and functions. Use this information to improve your prediction.

Bug Description and Knowledge Graph Context:
{updated_description}

Please provide a JSON array containing the predicted locations where the bug fix is needed. Each location should include the full file path and the full method/function name.

The method field should be one of these formats:
- `package.module.Class.method_name`
- `package.module.function_name`

Format:
```json
[
    {{
        "file_path": "package/submodule/file.py",
        "method": "package.module.Class.method_name"
    }}
]
```

Note:
- Focus on core functionality rather than test files.
- List the most likely locations first.
- Include up to {LLM_LOC_MAX} primary and related locations.
- Use the provided context to make informed predictions about file paths and method names.
"""
        prompt = prompt_template.format(
            updated_description=updated_description,
            LLM_LOC_MAX=LLM_LOC_MAX
        )
        return self.generate(prompt, stream=stream)


def process_instance(directory, instance_id):
    """
    Reads a KG location file, uses it to prompt an LLM for more specific locations,
    and enriches the original KG file with the LLM's findings.
    """
    pre_fl = PreFaultLocalization(instance_id)
    if pre_fl.target_sample is None:
        return f"Error: Could not find instance {instance_id} in dataset"

    # --- KG-dependent workflow ---
    kg_location_file = os.path.join(os.path.dirname(directory), 'kg_locations', f"{instance_id}.json")
    if not os.path.exists(kg_location_file):
        print(f"Error: KG Location file does not exist at {kg_location_file}")
        return f"Skipping {instance_id}."
    
    with open(kg_location_file, 'r') as f:
        locate_result = json.load(f)
    
    # Build a hint for the LLM using the problem statement and related issues/methods from the KG
    hint_parts = []
    
    problem_statement = pre_fl.target_sample.get('problem_statement', '') or pre_fl.target_sample.get('text', '')
    if problem_statement:
        hint_parts.append(f"## Problem Statement\n{problem_statement}")

    # Add related issues from KG
    if locate_result.get('related_entities', {}).get('issues'):
        sorted_issues = sorted(
            locate_result['related_entities']['issues'],
            key=lambda x: x.get('similarity', 0),
            reverse=True
        )
        if sorted_issues:
            issue_texts = []
            # Add the top issue and up to 2 related issues
            for issue in sorted_issues[:3]:
                title = issue.get('title', 'N/A')
                content = issue.get('content', 'N/A')
                issue_texts.append(f"### Issue: {title}\n\n{content}")
            if issue_texts:
                hint_parts.append("## Potentially Related Issues from Knowledge Graph\n\n" + "\n\n".join(issue_texts))

    # Add related methods from KG
    if locate_result.get('related_entities', {}).get('methods'):
        method_texts = []
        # Sort methods by similarity if available, and take top 5
        sorted_methods = sorted(
            locate_result['related_entities']['methods'],
            key=lambda x: x.get('similarity', 0),
            reverse=True
        )[:CANDIDATE_LOCATIONS_MAX]
        
        methods_content = ""
        for method in sorted_methods:
            methods_content += format_entity_content(method)
        if methods_content:
            hint_parts.append("## Potentially Related Functions from Knowledge Graph\n\n" + methods_content)

    hint = "\n\n".join(hint_parts).replace('\\n', '\n')
    
    print("--- Sending hint to LLM ---")
    print(hint)
    print("--------------------------")

    print("--- LLM raw output ---")
    raw_llm_output = pre_fl.pre_locate(hint, stream=True)
    print("----------------------")

    if raw_llm_output is None:
        print(f"Error: Did not receive a valid response from the LLM for {instance_id}. Skipping.")
        # To avoid breaking the chain, we can create an empty/error JSON or just skip.
        # Skipping seems safer to not pollute results.
        return f"LLM call failed for {instance_id}, skipping file generation."

    json_str = extract_json_code(raw_llm_output)

    try:
        llm_hint_list = json.loads(json_str)
        if not isinstance(llm_hint_list, list):
            llm_hint_list = []
    except json.JSONDecodeError:
        print(f"Error: Failed to parse JSON from LLM output for {instance_id}.")
        llm_hint_list = []
    
    # Get repository information to fetch code snippets
    repo_name = pre_fl.target_sample.get('repo')
    commit_id = pre_fl.target_sample.get('base_commit')
    
    github_repo = None
    commit = None
    if repo_name and commit_id and GITHUB_TOKEN:
        try:
            g = Github(GITHUB_TOKEN)
            github_repo = g.get_repo(repo_name)
            commit = github_repo.get_commit(commit_id)
        except Exception as e:
            print(f"Warning: Could not get GitHub repo/commit for {instance_id}: {e}")

    # Add detailed information for each method identified by the LLM to the locate_result
    cnt = 0
    if isinstance(llm_hint_list, list):
        for item in llm_hint_list:
            if not isinstance(item, dict) or 'file_path' not in item or 'method' not in item:
                continue

            qualified_name_from_llm = item['method']
            file_path = item['file_path']
            
            method_details = None
            if pre_fl.language == 'python' and github_repo and commit:
                try:
                    method_details = get_commit_method_by_signature(github_repo, commit, file_path, qualified_name_from_llm)
                except Exception as e:
                    print(f"Warning: get_commit_method_by_signature failed for {qualified_name_from_llm} in {file_path}: {e}")
            
            if method_details is not None:
                cnt += 1
                if cnt > LLM_LOC_MAX:
                    break
                
                method_details['path'] = [{"start_node": "root", "description": "points to method", "type": "INFERENCE", "end_node": method_details['name']}]
                method_details['type'] = 'method'
                method_details['similarity'] = 1.0
                locate_result.setdefault('related_entities', {}).setdefault('methods', []).append(method_details)
    
    # Save the augmented locate_result object, overwriting the file in the llm_locations dir
    output_path = os.path.join(directory, f"{instance_id}.json")
    with open(output_path, 'w') as f:
        json.dump(locate_result, f, indent=4)
    
    return f"LLM location saved to {output_path}"


def main():
    parser = argparse.ArgumentParser(description="LLM-based Fault Localization using KG context.")
    parser.add_argument("directory", type=str, help="Directory to save the results")
    parser.add_argument("--instance_id", type=str, help="The instance_id to process.", required=True)
    args = parser.parse_args()

    # Create the directory if it doesn't exist
    if not os.path.exists(args.directory):
        os.makedirs(args.directory)

    print(f"Processing a single specified instance: {args.instance_id}")
    result = process_instance(args.directory, args.instance_id)
    print(result)


if __name__ == '__main__':
    main()
