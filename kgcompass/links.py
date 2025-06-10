import os
import re
import hashlib
import traceback
from github import Github
import requests
import tempfile
from utils import get_classes_from_file, get_global_methods_from_file

class PatchLinkExpander:
    def __init__(self, github_token, repo_name):
        self.github = Github(github_token)
        self.repo = self.github.get_repo(repo_name)

    def fetch_commit_diff(self, match):
        commit_url = match.group(1)
        diff_id = match.group(2)
        target_old_line = int(match.group(3))
        target_new_line = int(match.group(4))
        parts = commit_url.split('/')
        owner = parts[3]
        repo = parts[4]
        commit_hash = parts[6]

        try:
            repo = self.github.get_repo(f"{owner}/{repo}")
            commit = repo.get_commit(commit_hash)
            for file in commit.files:
                hunks = []
                if file.patch:
                    current_hunk = None
                    old_line_map = {}
                    new_line_map = {}
                    current_old_line = 0
                    current_new_line = 0
                    
                    for line in file.patch.split('\n'):
                        if line.startswith('@@'):
                            hunk_header = line.split('@@')[1].strip()
                            old_range, new_range = hunk_header.split(' ')[:2]
                            current_old_line = int(old_range.split(',')[0][1:])
                            current_new_line = int(new_range.split(',')[0][1:])
                            
                            current_hunk = {
                                'old_start': current_old_line,
                                'old_count': int(old_range.split(',')[1]),
                                'new_start': current_new_line,
                                'new_count': int(new_range.split(',')[1]),
                                'header': hunk_header,
                                'changes': []
                            }
                            hunks.append(current_hunk)
                        elif line.startswith('-'):
                            old_line_map[current_old_line] = None
                            current_old_line += 1
                        elif line.startswith('+'):
                            new_line_map[current_new_line] = current_old_line - 1
                            current_new_line += 1
                        else:
                            old_line_map[current_old_line] = current_new_line
                            new_line_map[current_new_line] = current_old_line
                            current_old_line += 1
                            current_new_line += 1
                    
                    if target_old_line in old_line_map or target_new_line in new_line_map:
                        try:
                            old_content = repo.get_contents(file.filename, ref=commit.parents[0].sha).decoded_content.decode('utf-8')
                            new_content = repo.get_contents(file.filename, ref=commit.sha).decoded_content.decode('utf-8')
                            
                            module_path = file.filename.replace('/', '.').replace('.py', '')
                            
                            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as old_file:
                                old_file.write(old_content)
                                old_file_path = old_file.name
                            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as new_file:
                                new_file.write(new_content)
                                new_file_path = new_file.name
                            
                            try:
                                old_classes = get_classes_from_file(old_file_path, repo.name)
                                old_methods = get_global_methods_from_file(old_file_path, repo.name)
                                old_location = self._find_code_location(old_classes, old_methods, target_old_line, module_path)
                                
                                new_classes = get_classes_from_file(new_file_path, repo.name)
                                new_methods = get_global_methods_from_file(new_file_path, repo.name)
                                new_location = self._find_code_location(new_classes, new_methods, target_new_line, module_path)
                                
                                relevant_changes = self._extract_changes(file.patch, target_old_line, target_new_line)
                                
                                location_info = f"位置: {old_location} -> {new_location}" if old_location != new_location else f"位置: {new_location}"
                                return f"\n文件: {file.filename}\n{location_info}\n行号: {target_old_line}->{target_new_line}\n```\n{relevant_changes}\n```\n"
                            
                            finally:
                                os.unlink(old_file_path)
                                os.unlink(new_file_path)
                                
                        except Exception as e:
                            print(f"Error getting file content: {e}")
                            continue
            
            print(f"Not found matching changes")
            return match.group(0)
            
        except Exception as e:
            print(f"Error processing commit diff: {e}")
            print(traceback.format_exc())
            return match.group(0)

    def _find_code_location(self, classes, methods, line_number, module_path):
        for class_info in classes:
            if class_info['start_line'] <= line_number <= class_info['end_line']:
                class_name = class_info['name'].split('.')[-1]
                full_class_name = f"{module_path}.{class_name}"
                for method in class_info['methods']:
                    if method['start_line'] <= line_number <= method['end_line']:
                        method_name = method['name'].split('.')[-1]
                        return f"{full_class_name}.{method_name}"
                return full_class_name
        
        for method in methods:
            if method['start_line'] <= line_number <= method['end_line']:
                method_name = method['name'].split('.')[-1]
                return f"{module_path}.{method_name}"
        
        return None
    
    def _extract_changes(self, patch, old_line, new_line):
        relevant_changes = []
        current_old_line = 0
        current_new_line = 0
        
        for line in patch.split('\n'):
            if line.startswith('@@'):
                hunk_header = line.split('@@')[1].strip()
                old_range, new_range = hunk_header.split(' ')[:2]
                current_old_line = int(old_range.split(',')[0][1:])
                current_new_line = int(new_range.split(',')[0][1:])
            elif line.startswith('-'):
                if current_old_line == old_line:
                    relevant_changes.append(f"- {line[1:]}")
                current_old_line += 1
            elif line.startswith('+'):
                if current_new_line == new_line:
                    relevant_changes.append(f"+ {line[1:]}")
                current_new_line += 1
            else:  # context
                if current_old_line == old_line or current_new_line == new_line:
                    relevant_changes.append(f"  {line}")
                current_old_line += 1
                current_new_line += 1
        
        return '\n'.join(relevant_changes)

    def extract_structure_changes_from_patch(self, patch):
        """
            Analyze the following format of patch, and use _extract_change method
            @@ -325,8 +325,7 @@ def _repr_failure_py(
                truncate_locals = True

            try:
    -            os.getcwd()
    -            abspath = False
    +            abspath = os.getcwd() != str(self.config.invocation_dir)
            except OSError:
                abspath = True
        """
        changes = []
        current_old_line = 0
        current_new_line = 0
        current_hunk = None
        
        for line in patch.split('\n'):
            if line.startswith('@@'):
                hunk_header = line.split('@@')[1].strip()
                old_range, new_range = hunk_header.split(' ')[:2]
                current_old_line = int(old_range.split(',')[0][1:])
                current_new_line = int(new_range.split(',')[0][1:])
                current_hunk = {
                    'header': hunk_header,
                    'changes': []
                }
                changes.append(current_hunk)
            elif line.startswith('-'):
                current_hunk['changes'].append({
                    'type': 'delete',
                    'old_line': current_old_line,
                    'content': line[1:].strip()
                })
                current_old_line += 1
            elif line.startswith('+'):
                current_hunk['changes'].append({
                    'type': 'add',
                    'new_line': current_new_line,
                    'content': line[1:].strip()
                })
                current_new_line += 1
            else:  # context line
                current_hunk['changes'].append({
                    'type': 'context',
                    'old_line': current_old_line,
                    'new_line': current_new_line,
                    'content': line.strip()
                })
                current_old_line += 1
                current_new_line += 1
        
        return changes

    def _expand_patch_links(self, text):
        if not text:
            return text
            
        cache_dir = os.path.join(os.path.dirname(__file__), 'downloads')
        os.makedirs(cache_dir, exist_ok=True)
            
        patch_pattern = r'\[([^\]]+\.patch)\]\((https://[^)]+)\)'
        commit_diff_pattern = r'(https://github\.com/[^/]+/[^/]+/commit/[^#]+)#(diff-[a-f0-9]+)L(\d+)-R(\d+)'

        def fetch_patch_content(match):
            file_name = match.group(1)
            patch_url = match.group(2)
            print(patch_url)
            
            url_hash = hashlib.sha256(patch_url.encode()).hexdigest()[:16]
            cache_file = os.path.join(cache_dir, f"{url_hash}")
            
            try:
                if os.path.exists(cache_file):
                    print(f"using cached file for {file_name}: {url_hash}")
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                else:
                    print(f"downloading {file_name} from {patch_url}")
                    response = requests.get(patch_url)
                    if response.status_code == 200:
                        content = response.text
                        with open(cache_file, 'w', encoding='utf-8') as f:
                            f.write(content)
                        with open(os.path.join(cache_dir, f"{url_hash}.meta"), 'w', encoding='utf-8') as f:
                            f.write(f"{file_name}\n{patch_url}")
                    else:
                        print(f"download failed: {response.status_code}")
                        return match.group(0)
                        
                return f"\n{file_name}:\n```\n{content}\n```\n"
                
            except Exception as e:
                print(f"download/cache operation failed: {e}")
                return match.group(0)
        
        text = re.sub(commit_diff_pattern, self.fetch_commit_diff, text)
        text = re.sub(patch_pattern, fetch_patch_content, text)

        text = self.replace_commit_hash_within_text(text)
        return text
    
    def expand_github_commit_hash(self, hashid):
        """
        Analyze commit hash and return corresponding commit information
        
        Args:
            hashid (str): commit hash
            
        Returns:
            str: formatted text containing commit information
        """
        try:
            repo = self.repo
            commit = repo.get_commit(hashid)
            
            commit_info = []
            commit_info.append(f"Commit: {hashid}")
            commit_info.append(f"Author: {commit.commit.author.name}")
            commit_info.append(f"Date: {commit.commit.author.date}")
            commit_info.append(f"\nMessage:\n{commit.commit.message}")
            
            commit_info.append("\nModified files:")
            for file in commit.files:
                status = {
                    'added': 'Added',
                    'removed': 'Removed',
                    'modified': 'Modified',
                    'renamed': 'Renamed'
                }.get(file.status, file.status)
                
                commit_info.append(f"- {status}: {file.filename}")
                if file.additions:
                    commit_info.append(f"   Added: {file.additions} lines")
                if file.deletions:
                    commit_info.append(f"   Removed: {file.deletions} lines")
                
            return '\n' + "\n".join(commit_info) + '\n'
            
        except Exception as e:
            print(f"Error getting commit information: {e}")
            return f"Cannot get information of commit {hashid}"

    def replace_commit_hash_within_text(self, text):
        """Find commit hash in text and replace it with corresponding commit information"""
        commit_pattern = r'([a-f0-9]{40})'
        return re.sub(commit_pattern, lambda m: self.expand_github_commit_hash(m.group(1)), text)
