import ast
import json
import os
import traceback
import chardet
import re
from collections import defaultdict, OrderedDict
from github import Github
import tokenize
from io import BytesIO
import tempfile
import shutil
import uuid
from unidiff import PatchSet
import threading
from collections import defaultdict
import subprocess
import io
import tokenize

WEAK_CONNECTION = 1.00
NORMAL_CONNECTION = 0.50
STRONG_CONNECTION = 0.25
MAX_LIMIT = 50
repo_locks = defaultdict(threading.Lock)

class TextAnalyzer:
    def __init__(self, github_token):
        self.g = Github(github_token)
        self.cache = defaultdict(dict)
        self.patterns = {
            'issue_numbers': r'#(\d+)',
            'github_files': r'(?:blob|tree)/[^/\s]+/[^/\s]+',
            'github_links': r'https://github\.com\S+',
            'django_links': r'https://code\.djangoproject\.com\S+',
            'python_files': self._get_python_file_pattern()
        }
        self.pattern_counts = defaultdict(int)

    def _get_python_file_pattern(self):
        python_file_patterns = [
            r'[_\w-]+\.py\b',
            r'(?:\.{0,2}/)?(?:[\w-]+/)*[\w-]+\.py\b',
            r'(?:tests?|src|lib|apps?|modules?|examples?|scripts?)/(?:[_\w-]+/)*[\w-]+\.py\b',
            r'__\w+__\.py\b'
        ]
        return '|'.join(f'({p})' for p in python_file_patterns)

    def extract_matches(self, text, repo_name):
        matches = {}
        
        for pattern_name, pattern in self.patterns.items():
            found = re.findall(pattern, text, re.IGNORECASE)
            if found:
                if pattern_name == 'python_files':
                    found = [v for tup in found for v in tup if v.strip()]
                if found:
                    matches[pattern_name] = found
                    self.pattern_counts[pattern_name] += 1
        
        return matches

    def _get_repo(self, repo_name):
        if repo_name not in self.cache:
            self.cache[repo_name] = self.g.get_repo(repo_name)
        return self.cache[repo_name]

    def get_statistics(self):
        return dict(self.pattern_counts)

def get_pr_file_line_belongs(pull_request, repo_root, file_path, start_line, end_line, parser=None):
    belongs_to = {
        'classes': [],
        'methods': []
    }
    if '/tests/' in file_path:
        return belongs_to
    try:
        commit = pull_request.head.sha
        repo = pull_request.base.repo
        relative_path = os.path.relpath(file_path, repo_root)
        file_content = repo.get_contents(relative_path, ref=commit).decoded_content.decode('utf-8')
        temp_dir = tempfile.mkdtemp()
        temp_file = os.path.join(temp_dir, os.path.basename(file_path))
        try:
            try:
                ast.parse(file_content)
            except SyntaxError as e:
                print("Detected Python 2 code, trying to handle...")
                patterns = [
                    (r'(?m)^(\s*)print\s+([^(].*?)$', r'\1print(\2)'),
                    (r'(?m)^(\s*)print\s*$', r'\1print()'),
                    (r'(?m)^(\s*)print\s+"([^"]*?)"\s*%\s*(.+?)$', r'\1print("\2" % \3)'),
                    (r"(?m)^(\s*)print\s+'([^']*?)'\s*%\s*(.+?)$", r"\1print('\2' % \3)"),
                    (r'(?m)^(\s*)print\s+([^(].*?),\s*$', r'\1print(\2, end=" ")'),
                    (r'(?m)^(\s*)print\s+([^("].*?),\s*(.*?)$', r'\1print(\2, \3)'),
                    (r'`([^`]+)`', r'str(\1)'),
                    (r'\s*<>\s*', ' != '),
                    (r'(\w+)\.has_key\((.*?)\)', r'\1 in \2'),
                ]
                for pattern, replacement in patterns:
                    file_content = re.sub(pattern, replacement, file_content)
                file_content = re.sub(
                    r'(?m)^(\s*)print\s+(["\'].*?["\'])\s*%\s*(.+?)$',
                    r'\1print(\2 % \3)',
                    file_content
                )
                file_content = re.sub(
                    r'assert\s+([^,]+),\s*`([^`]+)`',
                    r'assert \1, str(\2)',
                    file_content
                )
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(file_content)
            if parser is not None:
                classes = parser.extract_classes(temp_file)
                methods = parser.get_global_methods(temp_file, repo.name.split('/')[-1])
                methods.extend(parser.get_global_variables(temp_file, repo.name.split('/')[-1]))
            else:
                classes = get_classes_from_file(temp_file, repo.name.split('/')[-1])
                methods = get_global_methods_from_file(temp_file, repo.name.split('/')[-1])
                methods.extend(get_global_variables_from_file(temp_file, repo.name.split('/')[-1]))
            module_path = f"{relative_path.replace('/', '.').replace('.py', '')}"
            print(f"Module path: {module_path}")            
            for class_info in classes:
                if (class_info['start_line'] <= end_line and 
                    class_info['end_line'] >= start_line):
                    class_name = f"{module_path}.{class_info['name'].split('.')[-1]}"
                    belongs_to['classes'].append({
                        'name': class_name,
                        'file_path': file_path,
                        'start_line': class_info['start_line'],
                        'end_line': class_info['end_line'],
                        'source_code': class_info['source_code'],
                        'doc_string': class_info['doc_string'],
                    })
                    for method in class_info['methods']:
                        if (method['start_line'] <= end_line and 
                            method['end_line'] >= start_line):
                            method_name = f"{class_name}.{method['name'].split('.')[-1]}"
                            belongs_to['methods'].append({
                                'name': method_name,
                                'file_path': file_path,
                                'signature': method['signature'].replace(method['name'], method_name),
                                'start_line': method['start_line'],
                                'end_line': method['end_line'],
                                'source_code': method['source_code'],
                                'doc_string': method['doc_string'],
                            })
            for method in methods:
                if (method['start_line'] <= end_line and 
                    method['end_line'] >= start_line):
                    method_name = f"{module_path}.{method['name'].split('.')[-1]}"
                    belongs_to['methods'].append({
                        'name': method_name,
                        'file_path': file_path,
                        'signature': method['signature'].replace(method['name'], method_name),
                        'start_line': method['start_line'],
                        'end_line': method['end_line'],
                        'source_code': method['source_code'],
                        'doc_string': method['doc_string'],
                    })
            
            return belongs_to
            
        finally:
            shutil.rmtree(temp_dir)
            
    except Exception as e:
        print(f"获取文件行归属时出错: {e}")
        print(traceback.format_exc())
        return belongs_to

_commit_file_cache = {}

def get_commit_file(repo, commit, file_path):
    cache_key = f"{commit.sha}:{file_path}"
    if cache_key in _commit_file_cache:
        return _commit_file_cache[cache_key]    
    file_content = repo.get_contents(file_path, ref=commit.sha)
    content = file_content.decoded_content.decode('utf-8')
    _commit_file_cache[cache_key] = content
    return content

def get_encoding(file):
    with open(file, 'rb') as f:
        tmp = chardet.detect(f.read())
        return tmp['encoding']

def read_file(file_name):
    try:
        ec = get_encoding(file_name)
        f = open(file_name, 'r', encoding=ec, errors='ignore')
        codes = ''.join(f.readlines())
        return codes
    except Exception as e:
        print(file_name)
        print(e)
        raise Exception

def get_source_files_by_extensions(directory, extensions):
    source_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if any(file.endswith(ext) for ext in extensions):
                source_files.append(os.path.join(root, file))
    return source_files

def get_python_files_from_content(repo_path, content, repo_name):
    python_files = re.findall(r'`?([a-zA-Z0-9_/\\]+\.py)`?', content)
    related_files = set()
    for file_name in python_files:
        file_parts = file_name.split('/')
        possible_paths = []
        possible_paths.append(os.path.join(repo_path, file_name))
        possible_paths.append(os.path.join(repo_path, repo_name, file_name))
        find_times = 0
        find_full_path = []
        for i in range(min(3, len(file_parts)), 0, -1):
            partial_parts = file_parts[-i:]
            for root, _, files in os.walk(repo_path):
                if partial_parts[-1] in files:
                    full_path = os.path.join(root, partial_parts[-1])
                    rel_path = os.path.relpath(full_path, repo_path)
                    rel_parts = rel_path.split(os.sep)
                    if (len(rel_parts) >= len(partial_parts) and 
                        rel_parts[-len(partial_parts):] == partial_parts):
                        if find_times == 0 or ('test' in find_full_path and 'test' not in full_path) or ('docs' in find_full_path and 'docs' not in full_path):
                            find_full_path.append(full_path)
                        find_times += 1
        if len(find_full_path) > 0:
            start_index = 0
            if len(find_full_path) > 1 and 'test' in find_full_path[0] and 'docs' in find_full_path[0]:
                start_index = 1
            for i in range(start_index, len(find_full_path)):
                possible_paths.append(find_full_path[i])
        if os.path.isabs(file_name):
            possible_paths.append(file_name)
        possible_paths = list(set(possible_paths))
        for possible_path in possible_paths:
            if os.path.exists(possible_path):
                related_files.add(possible_path)
    return list(related_files)[:MAX_LIMIT]

def get_global_methods_from_file(file_path, repo_name):
    content = read_file(file_path)
    tree = ast.parse(content)
    path_parts = file_path.split(os.sep)
    try:
        repo_root_index = len(path_parts) - 1 - path_parts[::-1].index(repo_name)
        module_path = '.'.join(path_parts[repo_root_index:]).replace('.py', '')
    except ValueError:
        module_path = os.path.relpath(file_path).replace('/', '.').replace('\\', '.').replace('.py', '')
    methods = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            method_name = node.name
            params = [a.arg for a in node.args.args]
            method_signature = f"{module_path}.{method_name}({', '.join(params)})"
            doc_string = ast.get_docstring(node) or ''
            methods.append({
                "name": f"{module_path}.{method_name}",
                "signature": method_signature,
                'file_path': file_path,
                "start_line": node.lineno,
                "source_code": ast.get_source_segment(content, node),
                "end_line": node.end_lineno if hasattr(node, 'end_lineno') else None,
                "doc_string": doc_string,
            })
    return methods

def get_global_variables_from_file(file_path, repo_name):
    content = read_file(file_path)
    tree = ast.parse(content)
    path_parts = file_path.split(os.sep)
    try:
        repo_root_index = len(path_parts) - 1 - path_parts[::-1].index(repo_name)
        module_path = '.'.join(path_parts[repo_root_index:]).replace('.py', '')
    except ValueError:
        module_path = os.path.relpath(file_path).replace('/', '.').replace('\\', '.').replace('.py', '')
    variables = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        value = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        value = ast.get_source_segment(content, node.value)
                    variables.append({
                        "name": f"{module_path}.{target.id}",
                        "signature": f"{module_path}.{target.id} = {value}",
                        "file_path": file_path,
                        "start_line": node.lineno,
                        "end_line": node.end_lineno if hasattr(node, 'end_lineno') else None,
                        "source_code": ast.get_source_segment(content, node),
                        "doc_string": "",
                    })
    return variables

def get_class_and_method_from_content(content, file_path, repo_name):
    repo_name = repo_name.split('/')[-1]
    temp_file = f'../{repo_name}/{file_path}'
    if not os.path.exists(temp_file):
        os.makedirs(os.path.dirname(temp_file), exist_ok=True)
    with open(temp_file, 'w') as f:
        f.write(content)
    classes = get_classes_from_file(temp_file, repo_name)
    methods = []
    for class_info in classes:
        for method in class_info['methods']:
            methods.append(method)
        class_info['methods'] = []

    methods.extend(get_global_methods_from_file(temp_file, repo_name))
    methods.extend(get_global_variables_from_file(temp_file, repo_name))
    return [classes, methods]

def get_classes_from_file(file_path, repo_name):
    try:
        content = read_file(file_path)
        comments_map = {}
        current_comments = []
        tokens = tokenize.tokenize(BytesIO(content.encode('utf-8')).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT:
                comment_text = token.string[1:].strip()
                if current_comments and token.start[0] > current_comments[-1][0] + 1:
                    current_comments = []
                current_comments.append((token.start[0], comment_text))
            elif token.type == tokenize.NL or token.type == tokenize.NEWLINE:
                if current_comments:
                    merged_comment = ' '.join(comment[1] for comment in current_comments)
                    comments_map[current_comments[0][0]] = merged_comment
                    comments_map[current_comments[-1][0] + 1] = merged_comment
                    current_comments = []
            else:
                current_comments = []
        
        path_parts = file_path.split(os.sep)
        try:
            repo_root_index = len(path_parts) - 1 - path_parts[::-1].index(repo_name)
            module_path = '.'.join(path_parts[repo_root_index:]).replace('.py', '')
        except ValueError:
            module_path = os.path.relpath(file_path).replace('/', '.').replace('\\', '.').replace('.py', '')

        tree = ast.parse(content)
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                full_class_name = f"{module_path}.{node.name}"
                class_doc = ast.get_docstring(node) or ''
                if not class_doc:
                    class_doc = comments_map.get(node.lineno, '') or comments_map.get(node.lineno - 1, '')
                class_source_code = ast.get_source_segment(content, node)
                methods = []
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        method_doc = ''
                        doc_node = ast.get_docstring(item)
                        if doc_node:
                            method_doc = doc_node
                        if not method_doc:
                            method_doc = comments_map.get(item.lineno, '')
                        function_source_code = ast.get_source_segment(content, item)
                        full_method_name = f"{full_class_name}.{item.name}"
                        method_info = {
                            'name': full_method_name,
                            'file_path': file_path,
                            'start_line': item.lineno,
                            'end_line': item.end_lineno,
                            'source_code': function_source_code,
                            'signature': f"{full_method_name}({', '.join(arg.arg for arg in item.args.args)})",
                            'doc_string': method_doc,
                        }
                        methods.append(method_info)
                    elif isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                try:
                                    value = ast.literal_eval(item.value)
                                except (ValueError, SyntaxError):
                                    value = ast.get_source_segment(content, item.value)
                                full_var_name = f"{full_class_name}.{target.id}"
                                var_info = {
                                    'name': full_var_name,
                                    'file_path': file_path,
                                    'start_line': item.lineno,
                                    'end_line': item.end_lineno if hasattr(item, 'end_lineno') else None,
                                    'source_code': ast.get_source_segment(content, item),
                                    'signature': f"{full_var_name} = {value}",
                                    'doc_string': comments_map.get(item.lineno, '') or comments_map.get(item.lineno - 1, ''),
                                }
                                methods.append(var_info)
                class_info = {
                    'name': full_class_name,
                    'start_line': node.lineno,
                    'end_line': node.end_lineno,
                    'doc_string': class_doc,
                    'source_code': class_source_code,
                    'methods': methods,
                }
                classes.append(class_info)
        
        return classes
    except Exception as e:
        print(f"Error while parsing file {file_path}: {e}")
        return []

def get_method_signature(node):
    args = []
    for arg in node.args.args:
        args.append(arg.arg)
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")
    return f"{node.name}({', '.join(args)})"

def extract_code_blocks(markdown_text):
    codes = []
    now_code = None
    for lines in markdown_text.split('\n'):
        if lines.startswith('```'):
            if now_code is not None:
                codes.append(now_code)
                now_code = None
            else:
                now_code = ''
        elif now_code is not None:
            now_code += lines + '\n'
    return codes

def get_reference_functions_from_text(repo_name, text, parser, exclude_set=set()):
    code_references = []
    # Extract code blocks (language-agnostic part)
    # Markdown code blocks might specify a language, e.g., ```python ... ``` or ```cpp ... ```
    # For now, we assume all code blocks are of the configured language if not specified otherwise,
    # or that the parser's analyze_snippet_for_references can handle/ignore other languages.
    extracted_blocks = extract_code_blocks(text)
    
    for code_block in extracted_blocks:
        try:
            # Use the passed parser to analyze the snippet
            # This delegates language-specific snippet parsing to the appropriate parser
            snippet_refs = parser.analyze_snippet_for_references(code_block)
            if snippet_refs: # Ensure it's not None or empty
                code_references.extend(snippet_refs)
        except Exception as e:
            # import traceback # Keep commented unless debugging
            # print(traceback.format_exc())
            print(f"Error processing code block for references with parser: {e}")
            continue
    
    # The rest of this function uses regex and general string matching, 
    # which is largely language-agnostic or configurable via repo_name and EXCLUDE_PATTERNS.
    # However, some patterns like `module_pattern` might benefit from language-specific adjustments if needed.
    try:
        EXCLUDE_PATTERNS = {
            'the', 'this', 'that', 'readme', 'todo', 'note', 'warning', 'error', 'pr', 'rfc', 'python', 'py', 'pyc', 'pyo', 'pyd', 'os', 'sys', 'io', 'json', 'self', 'import', 'def', 'try', 'except', 'finally', 'with', 'as', 'if', 'else', 'elif', 'while', 'for', 'in', 'is', 'and', 'or', 'not', 'none', 'true', 'false', 'none', 'null', 'google', 'github', 'community', 'com', 'org', 'www', 'http', 'https', 'hh', 'mm', 'dd', 'uuuuuu', 'do', 'does', 'should', 'please', 'thanks', 'thank', 'wanted', 'want', 'however', 'instead', 'what', 'how', 'when', 'where', 'seems', 'seem', 'patch', 'both', 'name', 'have', 'to', 'be', 'can', 'will', 'may', 'might', 'could', 'would', 'should', 'must', 'need', 'want', 'try', 'use', 'using', 'get', 'take', 'look', 'root', 'google.com', 'github.com', 'docs.djangoproject.com', 'developer', 'already', 'pending', 'looking', 'several', 'java', 'cpp', 'set', 'dict', 'int', 'str', 'float', 'list', 'tuple', 'here', 'you', 'your', '', 'a', 'an', 'i', 'he', 'it', 'they', 'she', 's', 'in', 'out', 'fix', 'of', 'open', 'on', 'off', 
        }
        module_pattern = fr'\b({repo_name}(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)\b|\`({repo_name}(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)\`'
        module_refs = re.findall(module_pattern, text)
        method_pattern = r'[\.\`\[\'\:]([a-zA-Z_][a-zA-Z0-9_\-]*)'
        method_refs = re.findall(method_pattern, text)
        method_refs = [ref for ref in method_refs if ref.lower() not in EXCLUDE_PATTERNS]
        global_pattern = r'\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b'
        global_refs = re.findall(global_pattern, text) 
        global_refs = [ref for ref in global_refs if ref.lower() not in EXCLUDE_PATTERNS]
        self_pattern = r'self\.([a-zA-Z_][a-zA-Z0-9_]*)\b'
        self_refs = re.findall(self_pattern, text)
        module_pattern = r'([a-zA-Z_][a-zA-Z0-9_]*)\.[\w]'
        new_module_refs = [ref for ref in re.findall(module_pattern, text) 
                          if ref.lower() not in EXCLUDE_PATTERNS]
        module_refs.extend(new_module_refs)
        full_module_pattern = r'([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)'
        full_module_refs = [ref for ref in re.findall(full_module_pattern, text) 
                          if ref.lower() not in EXCLUDE_PATTERNS]
        module_refs.extend(full_module_refs)
        for self_ref in self_refs:
            if self_ref in exclude_set:
                continue
            code_references.append(('variable', self_ref))
        for method_ref in method_refs:
            if method_ref in exclude_set:
                continue
            code_references.append(('call', method_ref))
        for global_ref in global_refs:
            if global_ref in exclude_set:
                continue
            code_references.append(('global', global_ref))
        for module_ref in module_refs:
            if module_ref in exclude_set:
                continue
            code_references.append(('import', module_ref))
        for module_ref in full_module_refs:
            if module_ref in exclude_set:
                continue
            code_references.append(('import', module_ref))
        if len(code_references) == 0:
            class_pattern = r'([A-Z][a-zA-Z_]*)'
            class_refs = [ref for ref in re.findall(class_pattern, text) 
                                if ref.lower() not in EXCLUDE_PATTERNS]
            for class_ref in class_refs:
                code_references.append(('call', class_ref))
    except Exception as e:
        print(f"Error while parsing module references: {e}")
        print(traceback.format_exc())
    return list(sorted(set(code_references), key=lambda x: len(x[1]) + x[1].count('.') * 5 + x[1].count('.py') * 10, reverse=True))[:MAX_LIMIT]

def extract_methods_from_traceback(working_tree_dir, repo_root, content, kg, parser=None):
    methods = []
    # repo_root = working_tree_dir # This line seems to override the passed repo_root, which might be an issue. Consider reviewing.
    # For now, let's keep the original logic of using working_tree_dir as effective repo_root for path construction inside.
    # However, for parser.get_global_methods, the original repo_root (self.config['repo_root']) is used.

    # Regex patterns for stack trace, largely Python-specific.
    # TODO: Generalize these patterns or make them language-specific if trace formats differ significantly.
    stack_patterns = [
        r'File\\s+(?:"([^"]+?\\.py)"|([^:"\\s]+?\\.py))(?:"|,|\\s|:)\\s*(?:line\\s+)?(\\d+)(?:,\\s+|\\s+)in\\s+([^\\s\\(]+)',
        r'([^\\s]+?\\.py)\\s+in\\s+([^\\s\\(]+)', # Simpler pattern
        r'([^\\s"]+?\\.py)\\s+in\\s+([^\\s\\(]+)', # Simpler pattern
        r'File\\s+([^,]+?\\.py),\\s*line\\s+(\\d+)(?:,\\s+|\\s+)in\\s+([^\\s\\(]+)',
        r'([^:]+?\\.py):(\\d+)(?::\\s+|\\s+)in\\s+([^\\s\\(]+)'
    ]
    
    # More generic patterns (experimental - might need refinement)
    generic_stack_patterns = [
        # Catches "File path/to/file.ext, line 123, in some_function"
        r'File\\s+(?:"([^"]+)"|([\\w/\\\\.-]+?\\.[a-zA-Z]+))(?:",|,|:)?\\s*(?:line\\s+)?(\\d+)(?:,\\s+|\\s+)in\\s+([\\w.<>:]+)',
        # Catches "at package.class.method(SourceFile.ext:line)"
        r'at\\s+([\\w.]+)\\(([\\w.-]+\\.[a-zA-Z]+):(\\d+)\\)',
        # Catches "path/to/file.ext:line in function"
        r'([\\w/\\\\.-]+?\\.[a-zA-Z]+):(\\d+):\\s+in\\s+function\\s+([\\w.<>:]+)',
    ]
    
    processed_matches = set() # To avoid processing the same trace line multiple times

    for pattern_set_name, current_patterns in [("generic", generic_stack_patterns), ("python_specific", stack_patterns)]:
        for pattern in current_patterns:
            for match in re.finditer(pattern, content):
                match_tuple = match.groups()
                if match_tuple in processed_matches:
                    continue
                processed_matches.add(match_tuple)

                file_path_from_trace = None
                line_number_str = None
                method_name_from_trace = None

                if pattern_set_name == "generic":
                    if pattern == generic_stack_patterns[0]: 
                        file_path_from_trace = next((g for g in match_tuple[:2] if g is not None), None)
                        line_number_str = match_tuple[2]
                        method_name_from_trace = match_tuple[3]
                    elif pattern == generic_stack_patterns[1]: 
                        method_name_from_trace = match_tuple[0] 
                        file_path_from_trace = match_tuple[1]   
                        line_number_str = match_tuple[2]
                    elif pattern == generic_stack_patterns[2]: 
                        file_path_from_trace = match_tuple[0]
                        line_number_str = match_tuple[1]
                        method_name_from_trace = match_tuple[2]
                else: # python_specific patterns
                    if len(match_tuple) == 4: 
                        file_path_from_trace = next((g for g in match_tuple[:2] if g is not None), None) 
                        if file_path_from_trace is None and len(match_tuple) == 4 : 
                             file_path_from_trace = match_tuple[0]
                             line_number_str = match_tuple[1]
                             method_name_from_trace = match_tuple[2] if len(match_tuple) > 2 else None 
                        else: 
                            line_number_str = match_tuple[2] if len(match_tuple) > 2 else None
                            method_name_from_trace = match_tuple[3] if len(match_tuple) > 3 else None
                    elif len(match_tuple) == 2: 
                        file_path_from_trace = match_tuple[0]
                        method_name_from_trace = match_tuple[1]
                                      
                if not file_path_from_trace or not method_name_from_trace:
                    continue

                potential_file_path = os.path.join(working_tree_dir, file_path_from_trace) 
                if not os.path.exists(potential_file_path):
                    try:
                        search_term_for_kg = os.path.basename(file_path_from_trace)
                        file_entities_from_kg = kg.search_file_by_path(search_term_for_kg)
                        if file_entities_from_kg:
                            selected_entity = None
                            for entity_info in file_entities_from_kg:
                                path_in_kg = entity_info['file']['path']
                                if 'test' not in path_in_kg.lower():
                                    selected_entity = entity_info
                                    break
                            if not selected_entity: 
                                selected_entity = file_entities_from_kg[0]
                            actual_file_path = selected_entity['file']['path']
                        else:
                            continue
                    except Exception as e:
                        print(f"Error searching file {file_path_from_trace} in KG: {e}")
                        continue
                else:
                    actual_file_path = potential_file_path

                actual_parser = None
                if callable(parser): 
                    actual_parser = parser(actual_file_path) 
                elif parser is not None: 
                    actual_parser = parser
                
                if not actual_parser:
                    print(f"No parser found for file {actual_file_path} from stack trace. Skipping.")
                    continue

                try:
                    classes = actual_parser.extract_classes(actual_file_path)
                    methods_in_file = actual_parser.get_global_methods(actual_file_path, repo_root) 
                    methods_in_file.extend(actual_parser.get_global_variables(actual_file_path, repo_root))
                except Exception as e:
                    print(f"Error parsing {actual_file_path} with its parser: {e}")
                    continue
                
                found_method_details = None
                target_method_simple_name = method_name_from_trace.split('.')[-1].split('(')[0].replace('<', '').replace('>', '')

                for class_info in classes:
                    for m_detail in class_info['methods']:
                        if m_detail['name'].split('.')[-1] == target_method_simple_name:
                            found_method_details = m_detail
                            break
                    if found_method_details: break
                
                if not found_method_details:
                    for m_detail in methods_in_file:
                        if m_detail['name'].split('.')[-1] == target_method_simple_name:
                            found_method_details = m_detail
                            break
                
                if found_method_details:
                    line_num = int(line_number_str) if line_number_str and line_number_str.isdigit() else found_method_details['start_line']
                    method_info_to_add = {
                        'name': found_method_details['name'], 
                        'file_path': actual_file_path,
                        'signature': found_method_details['signature'],
                        'start_line': found_method_details['start_line'], 
                        'end_line': found_method_details['end_line'],   
                        'line_number': line_num, 
                        'source_code': found_method_details.get('source_code', ''),
                        'doc_string': found_method_details.get('doc_string', '')
                    }
                    methods.append(method_info_to_add)
                    print(f"Extracted method from trace: {method_info_to_add['name']} in {actual_file_path}")
                else:
                    print(f"Could not find details for method '{target_method_simple_name}' in parsed file {actual_file_path}")

    return methods

def get_ref_ids(repo_name, content):
    refs = set()
    close_refs = re.findall(r'(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)', content, re.IGNORECASE)
    refs.update(close_refs)
    general_refs = re.findall(r'(?<![\w])#(\d+)(?![\w-])', content)
    refs.update(general_refs)
    url_pattern = f"https://github.com/{repo_name}/(?:issues|pull)/(\\d+)"
    url_refs = re.findall(url_pattern, content)
    refs.update(url_refs)
    if repo_name == 'django/django':
        url_pattern = f"https://code.djangoproject.com/ticket/(\\d+)"
        url_refs = re.findall(url_pattern, content)
        refs.update(url_refs)
    return refs

def has_subdirs_scandir(path):
    with os.scandir(path) as it:
        return any(entry.is_dir() for entry in it)

def load_jsonl(filepath):
    with open(filepath, "r") as file:
        return [json.loads(line) for line in file]

def get_code(content):
    code_blocks = extract_code_blocks(content)
    code = code_blocks
    if len(code_blocks) > 0:
        code = code_blocks[0]
    return code

def legal_patch(patch_content):
    try:
        patch = PatchSet(patch_content)
        return patch_content.strip() != ''
    except:
        return False

def applable_patch(patch_content, repo_name, commit_id):
    try:
        repo_path = f"../{repo_name.split('/')[-1]}"
        with repo_locks[repo_path]:
            current_ref = os.popen(f'git -C "{repo_path}" rev-parse HEAD').read().strip()
            checkout_cmd = f'git -C "{repo_path}" checkout -f {commit_id} -q'
            print(checkout_cmd)
            if os.system(checkout_cmd) != 0:
                print(f"Failed to checkout commit {commit_id}")
                return False
            with tempfile.TemporaryDirectory() as temp_dir:
                patch_file = os.path.join(temp_dir, 'temp.patch')
                with open(patch_file, 'w', encoding='utf-8') as f:
                    f.write(patch_content)
                try:
                    cmd = f'git -C "{repo_path}" apply --check "{patch_file}"'
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    return result == 0
                    
                finally:
                    os.system(f'git -C "{repo_path}" checkout -f {current_ref} -q')
                    print(f'git -C "{repo_path}" checkout -f {current_ref} -q')
                
    except Exception as e:
        print(f"Error while checking if patch is appliable: {e}")
        return False

def relative_path(path):
    return '/'.join(path.split('/')[2:])

def fake_git_apply(repo_playground, file_path, old_content, patch) -> str:
    repo_playground = os.path.join(repo_playground, str(uuid.uuid4()))
    assert not os.path.exists(repo_playground), f"{repo_playground} already exists"
    os.makedirs(repo_playground)
    subprocess.run(f"cd {repo_playground} && git init", shell=True)
    subprocess.run(
        f"mkdir -p {repo_playground}/{os.path.dirname(file_path)}", shell=True
    )
    with open(f"{repo_playground}/{file_path}", "w") as f:
        f.write(old_content)
    subprocess.run(
        f"cd {repo_playground} && git add {file_path} && git commit -m 'initial commit'",
        shell=True,
    )
    patch_file = f"{str(uuid.uuid4())}.patch"
    with open(f"{repo_playground}/{patch_file}", "w") as f:
        f.write(patch)
    o = subprocess.run(
        f"cd {repo_playground} && git apply --whitespace=nowarn {patch_file}",
        shell=True,
        capture_output=True,
    )
    if o.stderr.decode("utf-8"):
        print("stderr> ", o.stderr.decode("utf-8"))
        with open(f"{repo_playground}/{file_path}", "w") as f:
            f.write(old_content + "\n")
        o = subprocess.run(
            f"cd {repo_playground} && git apply --whitespace=nowarn {patch_file}",
            shell=True,
            capture_output=True,
        )
        if o.stderr.decode("utf-8"):
            print("stderr> ", o.stderr.decode("utf-8"))
            assert False, "shouldn't happen"
    o = subprocess.run(
        f"cd {repo_playground} && cat {file_path}", shell=True, capture_output=True
    )
    s = o.stdout.decode("utf-8")
    subprocess.run(f"rm -rf {repo_playground}", shell=True)
    return s

def fake_git_repo(repo_playground, file_path, old_content, new_content) -> str:
    repo_playground = os.path.join(repo_playground, str(uuid.uuid4()))
    assert not os.path.exists(repo_playground), f"{repo_playground} already exists"
    os.makedirs(repo_playground)
    normalized_path = os.path.normpath(file_path)
    if normalized_path.startswith('../'):
        normalized_path = normalized_path.replace('../', '', 1)
    subprocess.run(f"cd {repo_playground} && git init", shell=True)
    subprocess.run(
        f"mkdir -p {repo_playground}/{os.path.dirname(normalized_path)}", shell=True
    )
    with open(f"{repo_playground}/{normalized_path}", "w") as f:
        f.write(old_content)
    subprocess.run(
        f"cd {repo_playground} && git add {normalized_path} && git commit -m 'initial commit'",
        shell=True,
    )
    with open(f"{repo_playground}/{normalized_path}", "w") as f:
        f.write(new_content)
    o = subprocess.run(
        f"cd {repo_playground} && git diff {normalized_path}", shell=True, capture_output=True
    )
    s = o.stdout.decode("utf-8")
    return s

def check_syntax(code):
    if not code.strip():
        return False
    try:
        ast.parse(code)
    except SyntaxError as e:
        print(f"SyntaxError: {e}")
        return False
    return True

def lint_code(repo_playground, temp_name, code, prev_code="") -> tuple[bool, set, set]:
    repo_playground = os.path.join(repo_playground, str(uuid.uuid4()))
    assert not os.path.exists(repo_playground), f"{repo_playground} already exists"
    os.makedirs(repo_playground)
    with open(f"{repo_playground}/{temp_name}", "w") as f:
        f.write(prev_code)
    fatal = "E9,F821,F823,F831,F406,F407,F701,F702,F704,F706"
    o = subprocess.run(
        f"flake8 --select={fatal} --isolated {repo_playground}/{temp_name}",
        shell=True,
        capture_output=True,
    )
    s = o.stdout.decode("utf-8")
    prev_errors = set()
    if s != "":
        for error in s.split(f"{repo_playground}/{temp_name}:")[1:]:
            num_free_error = ":".join(error.split(":")[2:]).strip()
            prev_errors.add(num_free_error)
    with open(f"{repo_playground}/{temp_name}", "w") as f:
        f.write(code)
    o = subprocess.run(
        f"flake8 --select={fatal} --isolated {repo_playground}/{temp_name}",
        shell=True,
        capture_output=True,
    )
    s = o.stdout.decode("utf-8")
    subprocess.run(f"rm -rf {repo_playground}", shell=True)
    errors = set()
    if s != "":
        for error in s.split(f"{repo_playground}/{temp_name}:")[1:]:
            num_free_error = ":".join(error.split(":")[2:]).strip()
            errors.add(num_free_error)
    if len(errors - prev_errors) > 0:
        return False, prev_errors, errors
    return True, set(), set()

def check_code_differ_by_just_empty_lines(code, prev_code) -> bool:
    normalized_code1 = remove_empty_lines(code)
    normalized_code2 = remove_empty_lines(prev_code)
    return normalized_code1 == normalized_code2

def extract_python_blocks(text):
    # Regular expression pattern to match ```python\n{text}\n```
    pattern = r"```python\n(.*?)\n```"

    # Use re.findall to find all matches
    matches = re.findall(pattern, text, re.DOTALL)

    if len(matches) == 0:
        return [text]

    return matches

def split_edit_multifile_commands(commands) -> dict[str, str]:
    """Split commands based on edited files."""
    file_to_commands = OrderedDict()
    for command in commands:
        file_name = None
        start_line = None
        end_line = None
        
        for subcommand in command.split(">>>>>>> REPLACE")[:-1]:
            subcommand = subcommand.strip()
            if "### " in subcommand:
                lines = subcommand.split('\n')
                for line in lines:
                    if line.startswith('### '):
                        file_name = "'" + line.replace('### ', '').strip() + "'"
                    elif line.startswith('- start_line'):
                        start_line = int(line.split(':')[1].strip())
                    elif line.startswith('- end_line'):
                        end_line = int(line.split(':')[1].strip())

            if len(subcommand.split("<<<<<<< SEARCH")) != 2:
                continue
                
            converted_command = {
                'command': (
                    "<<<<<<< SEARCH"
                    + subcommand.split("<<<<<<< SEARCH")[1]
                    + "\n"
                    + ">>>>>>> REPLACE"
                ),
                'start_line': start_line,
                'end_line': end_line
            }
            
            if file_name not in file_to_commands:
                file_to_commands[file_name] = []
            
            if not any(cmd['command'] == converted_command['command'] 
                      for cmd in file_to_commands[file_name]):
                file_to_commands[file_name].append(converted_command)
                
    return file_to_commands

def remove_empty_lines(code: str) -> str:
    # Split the code into lines
    lines = code.splitlines()
    # Remove empty lines
    filtered_lines = [line for line in lines if line.strip() != ""]
    return "\n".join(filtered_lines)

def parse_diff_edit_commands_strict(commands, content, only_one_replace=False):
    def parse_for_threedots(original, replace, content):
        if replace.startswith("...\n") and len(replace) > 4:
            replace = replace[4:]

        if original == "...":
            if not replace[0].isspace():
                for line in content.splitlines():
                    if len(line) > 0 and not line[0].isspace():
                        if content.count(line) == 1:
                            original = line
                            replace = replace + "\n\n" + line
                            break

                if original == "...":
                    print("Can't find a suitable replacement position")

        if original.startswith("...\n") and len(original) > 4:
            original = original[4:]

        return original, replace

    replaced = False
    
    for command in reversed(commands):
        search_replace = command['command'].split('<<<<<<< SEARCH')[1]
        search_replace_parts = search_replace.split('\n=======\n')
        if len(search_replace_parts) != 2:
            continue
            
        original = search_replace_parts[0].strip()
        replace = search_replace_parts[1].split('>>>>>>> REPLACE')[0].strip()

        original, replace = parse_for_threedots(original, replace, content)
        
        if original in content:
            if only_one_replace:
                content = content.replace(original, replace, 1)
            else:
                content = content.replace(original, replace)
            replaced = True
            print("Successfully applied changes")
        else:
            print("Content doesn't match")
            print("Expected content:", original)

    if not replaced:
        print("No changes were made")

    return content

def remove_comments_and_docstrings(source):
    io_obj = io.StringIO(source)
    out = ""
    prev_toktype = tokenize.INDENT
    last_lineno = -1
    last_col = 0
    for tok in tokenize.generate_tokens(io_obj.readline):
        token_type = tok[0]
        token_string = tok[1]
        start_line, start_col = tok[2]
        end_line, end_col = tok[3]
        ltext = tok[4]
        if start_line > last_lineno:
            last_col = 0
        if start_col > last_col:
            out += " " * (start_col - last_col)
        if token_type == tokenize.COMMENT:
            pass
        elif token_type == tokenize.STRING:
            if prev_toktype != tokenize.INDENT:
                if prev_toktype != tokenize.NEWLINE:
                    if start_col > 0:
                        out += token_string
        else:
            out += token_string
        prev_toktype = token_type
        last_col = end_col
        last_lineno = end_line
    out = "\n".join(l for l in out.splitlines() if l.strip())
    return out

def remove_ansi_sequences(input_string):
    ansi_escape_pattern = r"\x1b\[\d+m"
    clean_string = re.sub(ansi_escape_pattern, "", input_string)

    return clean_string

def txt_file_contains_string(path_to_txt, expected_output, other_patterns=[]):
    try:
        with open(path_to_txt, "r", encoding="utf-8") as file:
            content = file.read()
            filtered_content = remove_ansi_sequences(content)
            for pattern in other_patterns:
                if pattern in filtered_content:
                    return False
            return expected_output in filtered_content

    except FileNotFoundError:
        pass
    except IOError:
        print(f"An error occurred while reading the file at {path_to_txt}.")

    return False

def get_commit_method_by_signature(repo, commit, file_path, method_signature):
    file_content = get_commit_file(repo, commit, file_path)
    _, methods = get_class_and_method_from_content(file_content, file_path, repo.name)
    for method in methods:
        if method_signature in method['signature']:
            return method
    return None

def extract_json_code(code):
    json_code = re.search(r'```json\n(.*?)\n```', code, re.DOTALL)
    if json_code:
        return json_code.group(1)
    return code

def get_functions(tree):

    functions = {}

    class FunctionVisitor(ast.NodeVisitor):
        def __init__(self):
            self.parents = []

        def visit(self, node):
            self.parents.append(node)
            super().visit(node)
            self.parents.pop()

        def visit_FunctionDef(self, node):
            if not any(isinstance(parent, ast.ClassDef) for parent in self.parents):
                functions[node.name] = ast.unparse(node)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            if not any(isinstance(parent, ast.ClassDef) for parent in self.parents):
                functions[node.name] = ast.unparse(node)
            self.generic_visit(node)

    class ClassVisitor(ast.NodeVisitor):
        def visit_ClassDef(self, node):
            class_name = node.name
            for body_item in node.body:
                if isinstance(body_item, ast.FunctionDef) or isinstance(
                    body_item, ast.AsyncFunctionDef
                ):
                    functions[f"{class_name}.{body_item.name}"] = ast.unparse(body_item)
            self.generic_visit(node)

    FunctionVisitor().visit(tree)
    ClassVisitor().visit(tree)
    return functions

def is_just_new_function(code1, code2):
    tree1 = ast.parse(code1)
    tree2 = ast.parse(code2)

    functions1 = get_functions(tree1)
    functions2 = get_functions(tree2)

    # The new functions in the second code
    if len(set(list(functions1.keys())) - set(list(functions2.keys()))) > 0:
        # removes functions
        return False

    for func in functions1:
        if functions1[func] != functions2[func]:
            # modifies existing functions
            return False

    if len(set(list(functions2.keys())) - set(list(functions1.keys()))) > 0:
        return True

    # modifying global stuff is okay, because its actually same as functions almost.

    return False

def parse_patch(patch):
    file_changes = []
    current_file = None
    current_hunk = None
    deleted_lines = 0

    patch_lines = patch.split("\n")
    for line in patch_lines:
        if line.startswith("diff --git"):
            # Reset for new files
            if current_file:
                file_changes.append(current_file)
            current_file = {"file": "", "hunks": []}
        elif line.startswith("--- a/"):
            pass
        elif line.startswith("+++ b/"):
            if current_file is not None:
                current_file["file"] = line[6:]
        elif line.startswith("@@ "):
            if current_file is not None:
                match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
                if match:
                    current_hunk = {"start_line": int(match.group(2)), "changes": []}
                    current_file["hunks"].append(current_hunk)
                    deleted_lines = 0
                    added_lines = 0
        elif line.startswith("+") or line.startswith("-"):
            if current_hunk is not None:
                change_type = "add" if line.startswith("+") else "delete"
                if change_type == "delete":
                    deleted_lines += 1
                    current_hunk["changes"].append(
                        {
                            "type": change_type,
                            "content": line[1:].strip(),
                            "line": current_hunk["start_line"] - added_lines,
                        }
                    )
                    current_hunk["start_line"] += 1
                else:
                    added_lines += 1
                    current_hunk["changes"].append(
                        {
                            "type": change_type,
                            "content": line[1:].strip(),
                            "line": current_hunk["start_line"] - deleted_lines,
                        }
                    )
                    current_hunk["start_line"] += 1
        else:
            if current_hunk is not None:
                current_hunk["start_line"] += 1

    if current_file:
        file_changes.append(current_file)

    return file_changes

def normalize_patch(patch: str, original_file_content: str) -> str:
    "Remove edits to trailing spaces and comments in the patch."
    if not patch.strip():
        return ""
    # Extract info.
    file_changes = parse_patch(patch)
    if not file_changes:
        print(patch)
        print("=")
        import json

        print(json.dumps(file_changes, indent=2))
        exit(0)

    edited_file = file_changes[0]["file"]
    old_content = original_file_content
    # Get new file
    new_content = fake_git_apply("playground", edited_file, old_content, patch)
    if new_content is None:
        # Error during applying diff
        return patch

    # Normalize file contents
    def normalize_code(code):
        try:
            node = ast.parse(code)
            return ast.unparse(node)
        except:
            return code

    old_content = normalize_code(old_content)
    new_content = normalize_code(new_content)

    try:
        remove_docstring_old_content = remove_comments_and_docstrings(old_content)
        ast.parse(remove_docstring_old_content)  # check
        remove_docstring_new_content = remove_comments_and_docstrings(new_content)
        ast.parse(remove_docstring_new_content)  # check
    except:
        # when does this exception happen?
        # when the code has some class or function with empty docstring (thats valid python code)
        # but removing it is not, to be save we just use the original.
        remove_docstring_old_content = old_content
        remove_docstring_new_content = new_content

    diff = fake_git_repo(
        "playground",
        edited_file,
        remove_docstring_old_content,
        remove_docstring_new_content,
    )

    if is_just_new_function(remove_docstring_old_content, remove_docstring_new_content):
        # modify the diff to ignore context.
        new_diff = []
        for line in diff.splitlines():
            if line.startswith("-") or line.startswith("+"):
                new_diff.append(line)
        diff = "\n".join(new_diff)

    # Note that the normalized diff may not be applied to the original file.
    return diff

def minimize_patch(patch):
    lines = patch.splitlines()
    
    minimized_lines = []
    for line in lines:
        if line.startswith('-') or line.startswith('+'):
            cleaned_line = line[0] + ''.join(line[1:].split())
            minimized_lines.append(cleaned_line)
            
    return ''.join(minimized_lines)
