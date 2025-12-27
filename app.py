#!/usr/bin/env python3
"""
KGCompass Web Interface
一个用于展示和执行 KGCompass 软件修复流程的 Web 界面
"""

import os
import json
import subprocess
import threading
import time
import shutil
import re
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kgcompass-web-interface'

# 优化 Flask 配置以避免监控过多文件
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000  # 1年缓存静态文件
app.config['TEMPLATES_AUTO_RELOAD'] = False  # 禁用模板自动重载

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 全局变量存储任务状态
active_tasks: Dict[str, Dict] = {}
task_logs: Dict[str, List[str]] = {}

# 支持的仓库列表（SWE-bench 完整版）
SUPPORTED_REPOS = {
    # SWE-bench Lite 仓库
    "astropy__astropy": {
        "name": "astropy/astropy",
        "description": "Python库，用于天文学和天体物理学",
        "language": "Python",
        "stars": "4.3k"
    },
    "django__django": {
        "name": "django/django", 
        "description": "高级Python Web框架",
        "language": "Python",
        "stars": "79k"
    },
    "matplotlib__matplotlib": {
        "name": "matplotlib/matplotlib",
        "description": "Python 2D绘图库",
        "language": "Python", 
        "stars": "19k"
    },
    "mwaskom__seaborn": {
        "name": "mwaskom/seaborn",
        "description": "基于matplotlib的统计数据可视化库",
        "language": "Python",
        "stars": "12k"
    },
    "psf__requests": {
        "name": "psf/requests",
        "description": "优雅简洁的Python HTTP库",
        "language": "Python",
        "stars": "52k"
    },
    "pallets__flask": {
        "name": "pallets/flask",
        "description": "轻量级Python Web框架",
        "language": "Python",
        "stars": "67k"
    },
    "pydata__xarray": {
        "name": "pydata/xarray",
        "description": "N-D标记数组和数据集处理库",
        "language": "Python",
        "stars": "3.6k"
    },
    "pylint-dev__pylint": {
        "name": "pylint-dev/pylint",
        "description": "Python代码静态分析工具",
        "language": "Python",
        "stars": "5.2k"
    },
    "pytest-dev__pytest": {
        "name": "pytest-dev/pytest",
        "description": "Python测试框架",
        "language": "Python",
        "stars": "11k"
    },
    "scikit-learn__scikit-learn": {
        "name": "scikit-learn/scikit-learn", 
        "description": "Python机器学习库",
        "language": "Python",
        "stars": "59k"
    },
    "sphinx-doc__sphinx": {
        "name": "sphinx-doc/sphinx",
        "description": "Python文档生成工具",
        "language": "Python",
        "stars": "6.4k"
    },
    "sympy__sympy": {
        "name": "sympy/sympy",
        "description": "Python符号数学库",
        "language": "Python",
        "stars": "12k"
    },
    
    # SWE-bench 完整版额外仓库
    "psf__black": {
        "name": "psf/black",
        "description": "Python代码格式化工具",
        "language": "Python",
        "stars": "38k"
    },
    "pyvista__pyvista": {
        "name": "pyvista/pyvista",
        "description": "3D绘图和网格分析库",
        "language": "Python",
        "stars": "2.5k"
    },
    "marshmallow-code__marshmallow": {
        "name": "marshmallow-code/marshmallow",
        "description": "对象序列化/反序列化库",
        "language": "Python",
        "stars": "7k"
    },
    "pydata__pandas": {
        "name": "pandas-dev/pandas",
        "description": "数据分析和处理库",
        "language": "Python",
        "stars": "43k"
    },
    "sqlfluff__sqlfluff": {
        "name": "sqlfluff/sqlfluff",
        "description": "SQL Linter和格式化工具",
        "language": "Python",
        "stars": "7.5k"
    },
    "iterative__dvc": {
        "name": "iterative/dvc",
        "description": "数据版本控制系统",
        "language": "Python",
        "stars": "13k"
    },
    "schematics__schematics": {
        "name": "schematics/schematics",
        "description": "数据结构验证库",
        "language": "Python",
        "stars": "2.6k"
    },
    "pvlib__pvlib-python": {
        "name": "pvlib/pvlib-python",
        "description": "太阳能光伏系统模拟库",
        "language": "Python",
        "stars": "1k"
    },
    "pydicom__pydicom": {
        "name": "pydicom/pydicom",
        "description": "DICOM医学图像处理库",
        "language": "Python",
        "stars": "2k"
    },
    "pylint-dev__astroid": {
        "name": "pylint-dev/astroid",
        "description": "Python抽象语法树库",
        "language": "Python",
        "stars": "500"
    },
    "pypa__pip": {
        "name": "pypa/pip",
        "description": "Python包管理工具",
        "language": "Python",
        "stars": "9.4k"
    },
    "pydantic__pydantic": {
        "name": "pydantic/pydantic",
        "description": "数据验证库",
        "language": "Python",
        "stars": "20k"
    },
    "python__mypy": {
        "name": "python/mypy",
        "description": "Python静态类型检查器",
        "language": "Python",
        "stars": "18k"
    },
    "pytest-dev__pdb": {
        "name": "pytest-dev/pdb",
        "description": "Python调试器",
        "language": "Python",
        "stars": "300"
    },
    "aio-libs__aiohttp": {
        "name": "aio-libs/aiohttp",
        "description": "异步HTTP客户端/服务器",
        "language": "Python",
        "stars": "15k"
    },
    "pyca__cryptography": {
        "name": "pyca/cryptography",
        "description": "加密库",
        "language": "Python",
        "stars": "6.5k"
    },
    "boto__boto3": {
        "name": "boto/boto3",
        "description": "AWS SDK for Python",
        "language": "Python",
        "stars": "9k"
    },
    "httpie__httpie": {
        "name": "httpie/httpie",
        "description": "命令行HTTP客户端",
        "language": "Python",
        "stars": "33k"
    },
    "pallets__click": {
        "name": "pallets/click",
        "description": "命令行界面创建工具",
        "language": "Python",
        "stars": "15k"
    },
    "getmoto__moto": {
        "name": "getmoto/moto",
        "description": "AWS服务模拟库",
        "language": "Python",
        "stars": "7.5k"
    },
    "sqlalchemy__sqlalchemy": {
        "name": "sqlalchemy/sqlalchemy",
        "description": "Python SQL工具包和ORM",
        "language": "Python",
        "stars": "9k"
    }
}

# 示例 Issue IDs（只存储数字ID部分）
EXAMPLE_ISSUES = {
    # SWE-bench Lite 仓库示例
    "astropy__astropy": ["12907", "13033", "13236"],
    "django__django": ["11001", "11179", "11283"],
    "matplotlib__matplotlib": ["13989", "14471", "15928"],
    "mwaskom__seaborn": ["2389", "2576"],
    "psf__requests": ["2148", "3179", "4723"],
    "pallets__flask": ["3079", "4992"],
    "pydata__xarray": ["3159", "4248", "5131"],
    "pylint-dev__pylint": ["4604", "5859", "6506"],
    "pytest-dev__pytest": ["5413", "7490", "8365"],
    "scikit-learn__scikit-learn": ["13497", "13779", "14894"],
    "sphinx-doc__sphinx": ["8721", "9260", "10325"],
    "sympy__sympy": ["15308", "15346", "15678"],
    
    # SWE-bench 完整版额外仓库示例
    "psf__black": ["2506", "2916"],
    "pyvista__pyvista": ["2151", "2402"],
    "marshmallow-code__marshmallow": ["1359", "1566"],
    "pydata__pandas": ["17609", "21311", "22378"],
    "sqlfluff__sqlfluff": ["2419", "2894"],
    "iterative__dvc": ["4211", "5281"],
    "schematics__schematics": ["425", "498"],
    "pvlib__pvlib-python": ["1224", "1603"],
    "pydicom__pydicom": ["1095", "1373"],
    "pylint-dev__astroid": ["1138", "1432"],
    "pypa__pip": ["7668", "9617"],
    "pydantic__pydantic": ["4691", "5673"],
    "python__mypy": ["9716", "10803"],
    "pytest-dev__pdb": ["194", "256"],
    "aio-libs__aiohttp": ["3796", "4581"],
    "pyca__cryptography": ["5647", "6548"],
    "boto__boto3": ["1678", "2238"],
    "httpie__httpie": ["1168", "1428"],
    "pallets__click": ["1495", "1864"],
    "getmoto__moto": ["3482", "4520"],
    "sqlalchemy__sqlalchemy": ["4688", "5601"]
}

class GitHubHelper:
    """GitHub API 辅助类"""
    
    @staticmethod
    def parse_github_url(url: str) -> Optional[Tuple[str, str]]:
        """
        解析 GitHub URL，提取 owner 和 repo
        支持格式：
        - https://github.com/owner/repo
        - https://github.com/owner/repo.git
        - github.com/owner/repo
        - owner/repo
        """
        url = url.strip()
        
        # 移除 .git 后缀
        if url.endswith('.git'):
            url = url[:-4]
        
        # 移除尾部斜杠
        url = url.rstrip('/')
        
        # 尝试多种格式
        patterns = [
            r'https?://github\.com/([^/]+)/([^/]+)',
            r'github\.com/([^/]+)/([^/]+)',
            r'^([^/]+)/([^/]+)$'
        ]
        
        for pattern in patterns:
            match = re.match(pattern, url)
            if match:
                owner, repo = match.groups()
                # 移除可能的查询参数
                repo = repo.split('?')[0]
                return owner, repo
        
        return None
    
    @staticmethod
    def get_issue_info(owner: str, repo: str, issue_number: str) -> Optional[Dict]:
        """
        从 GitHub API 获取 issue 信息
        """
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
            
            # 检查是否有 GitHub token（可选，但能提高 API 限制）
            headers = {}
            github_token = os.environ.get('GITHUB_TOKEN')
            if github_token:
                headers['Authorization'] = f'token {github_token}'
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                issue_data = response.json()
                return {
                    'number': issue_data['number'],
                    'title': issue_data['title'],
                    'body': issue_data.get('body', ''),
                    'state': issue_data['state'],
                    'created_at': issue_data['created_at'],
                    'updated_at': issue_data['updated_at'],
                    'html_url': issue_data['html_url'],
                    'labels': [label['name'] for label in issue_data.get('labels', [])]
                }
            elif response.status_code == 404:
                return None
            else:
                print(f"GitHub API 错误: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"获取 issue 信息失败: {e}")
            return None
    
    @staticmethod
    def validate_repo(owner: str, repo: str) -> bool:
        """
        验证 GitHub 仓库是否存在且可访问
        """
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}"
            
            headers = {}
            github_token = os.environ.get('GITHUB_TOKEN')
            if github_token:
                headers['Authorization'] = f'token {github_token}'
            
            response = requests.get(url, headers=headers, timeout=10)
            return response.status_code == 200
            
        except Exception as e:
            print(f"验证仓库失败: {e}")
            return False
    
    @staticmethod
    def get_repo_info(owner: str, repo: str) -> Optional[Dict]:
        """
        获取仓库基本信息
        """
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}"
            
            headers = {}
            github_token = os.environ.get('GITHUB_TOKEN')
            if github_token:
                headers['Authorization'] = f'token {github_token}'
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                repo_data = response.json()
                return {
                    'name': repo_data['full_name'],
                    'description': repo_data.get('description', ''),
                    'stars': repo_data.get('stargazers_count', 0),
                    'language': repo_data.get('language', 'Unknown'),
                    'clone_url': repo_data['clone_url'],
                    'default_branch': repo_data.get('default_branch', 'main')
                }
            return None
            
        except Exception as e:
            print(f"获取仓库信息失败: {e}")
            return None

class RepairTaskManager:
    """修复任务管理器"""
    
    def __init__(self):
        self.output_dir = Path("web_outputs")
        self.output_dir.mkdir(exist_ok=True)
    
    def start_repair_task(self, task_id: str, instance_id: str, repo_key: str = None, 
                         custom_repo_info: Dict = None) -> bool:
        """
        启动修复任务
        
        Args:
            task_id: 任务ID
            instance_id: 实例ID
            repo_key: SWE-bench 仓库键（用于预定义仓库）
            custom_repo_info: 自定义仓库信息（用于自定义仓库）
                {
                    'owner': 仓库所有者,
                    'repo': 仓库名称,
                    'clone_url': 克隆URL,
                    'issue_number': Issue 号,
                    'repo_name': 仓库全名
                }
        """
        try:
            # 判断是预定义仓库还是自定义仓库
            is_custom = custom_repo_info is not None
            
            if is_custom:
                # 自定义仓库
                repo_name = custom_repo_info['repo_name']
                repo_identifier = f"{custom_repo_info['owner']}__{custom_repo_info['repo']}"
            else:
                # 预定义仓库
                if repo_key not in SUPPORTED_REPOS:
                    raise ValueError(f"不支持的仓库: {repo_key}")
                repo_name = SUPPORTED_REPOS[repo_key]['name']
                repo_identifier = repo_key
            
            # 创建任务状态
            active_tasks[task_id] = {
                'instance_id': instance_id,
                'repo_key': repo_key,
                'repo_name': repo_name,
                'repo_identifier': repo_identifier,
                'is_custom': is_custom,
                'status': 'initializing',
                'start_time': datetime.now().isoformat(),
                'current_step': 'prepare',
                'progress': 0,
                'output_dir': str(self.output_dir / task_id)
            }
            
            if is_custom:
                active_tasks[task_id]['custom_repo_info'] = custom_repo_info
            
            task_logs[task_id] = []
            
            # 创建输出目录
            task_output_dir = self.output_dir / task_id
            task_output_dir.mkdir(exist_ok=True)
            
            # 在新线程中执行修复任务
            if is_custom:
                thread = threading.Thread(
                    target=self._execute_custom_repair_pipeline,
                    args=(task_id, instance_id, custom_repo_info, task_output_dir)
                )
            else:
                thread = threading.Thread(
                    target=self._execute_repair_pipeline,
                    args=(task_id, instance_id, repo_key, task_output_dir)
                )
            thread.daemon = True
            thread.start()
            
            return True
            
        except Exception as e:
            if task_id in active_tasks:
                active_tasks[task_id]['status'] = 'error'
                active_tasks[task_id]['error'] = str(e)
            self._log_message(task_id, f"❌ 任务启动失败: {str(e)}")
            return False
    
    def _execute_repair_pipeline(self, task_id: str, instance_id: str, repo_key: str, output_dir: Path):
        """在 Docker 容器中执行真实的修复管道"""
        try:
            self._log_message(task_id, f"🚀 开始为 {instance_id} 执行修复流程")
            self._log_message(task_id, f"📋 仓库: {SUPPORTED_REPOS[repo_key]['name']}")
            
            # 检查 Docker 环境
            self._update_task_status(task_id, 'checking_docker', 5, "🐳 检查 Docker 环境...")
            
            # 检查 docker-compose 是否运行
            result = subprocess.run([
                "docker-compose", "ps", "-q", "app"
            ], capture_output=True, text=True, cwd=str(Path.cwd()))
            
            if result.returncode != 0 or not result.stdout.strip():
                self._log_message(task_id, "🐳 启动 Docker 服务...")
                # 启动 docker-compose 服务
                start_result = subprocess.run([
                    "docker-compose", "up", "-d", "--build"
                ], capture_output=True, text=True, cwd=str(Path.cwd()))
                
                if start_result.returncode != 0:
                    raise Exception(f"Docker 服务启动失败: {start_result.stderr}")
                
                self._log_message(task_id, "✅ Docker 服务已启动")
                
                # 等待服务完全启动
                import time
                time.sleep(10)
            else:
                self._log_message(task_id, "✅ Docker 服务已运行")
            
            # 设置输出目录映射
            # Docker 容器中的路径应该与主机路径相对应
            container_output_dir = f"/opt/KGCompass/web_outputs/{task_id}"
            
            # 在容器中执行修复命令
            self._update_task_status(task_id, 'docker_repair', 10, "🚀 在容器中执行修复...")
            self._log_message(task_id, f"🐳 在 Docker 容器中执行: run_repair.sh {instance_id}")
            
            # 构建 docker-compose exec 命令
            docker_cmd = [
                "docker-compose", "exec", "-T", "app", 
                "bash", "run_repair.sh", instance_id
            ]
            
            # 设置环境变量，将输出重定向到我们的 web_outputs
            env = os.environ.copy()
            env['DOCKER_OUTPUT_DIR'] = container_output_dir
            
            # 执行修复命令并实时获取输出
            self._log_message(task_id, "🔄 开始执行修复流程...")
            
            process = subprocess.Popen(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(Path.cwd()),
                env=env,
                bufsize=1,
                universal_newlines=True
            )
            
            # 实时读取并发送日志
            step_progress = {
                'KG-based Bug Location': 30,
                'LLM-based Bug Location': 50, 
                'Merge and Fix Bug Locations': 70,
                'Final Patch Generation': 90
            }
            
            current_progress = 10
            
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                
                if output:
                    line = output.strip()
                    self._log_message(task_id, line)
                    
                    # 根据输出内容更新进度
                    for step_name, progress in step_progress.items():
                        if step_name in line and progress > current_progress:
                            current_progress = progress
                            if 'KG-based' in step_name:
                                self._update_task_status(task_id, 'kg_mining', progress, "🔍 挖掘知识图谱...")
                            elif 'LLM-based' in step_name:
                                self._update_task_status(task_id, 'fault_localization', progress, "🎯 LLM 故障定位...")
                            elif 'Merge' in step_name:
                                self._update_task_status(task_id, 'merge_localization', progress, "🔗 合并定位结果...")
                            elif 'Patch Generation' in step_name:
                                self._update_task_status(task_id, 'patch_generation', progress, "⚡ 生成修复补丁...")
                            break
            
            # 等待进程完成
            return_code = process.poll()
            
            if return_code != 0:
                raise Exception(f"修复流程执行失败，返回码: {return_code}")
            
            # 查找生成的补丁文件
            self._update_task_status(task_id, 'collecting_results', 95, "📁 收集修复结果...")
            
            # 先检查本地 web_outputs 目录是否已有补丁
            host_patch_path = output_dir / f"{instance_id}_patch.diff"
            patch_file_path = None
            
            if host_patch_path.exists():
                self._log_message(task_id, f"✅ 补丁文件已存在: {host_patch_path}")
                patch_file_path = str(host_patch_path)
            else:
                # 在容器中查找补丁文件（查找 tests 目录下的，更快）
                self._log_message(task_id, "🔍 在容器中查找补丁文件...")
                find_cmd = [
                    "docker-compose", "exec", "-T", "app",
                    "find", f"/opt/KGCompass/tests/{instance_id}_deepseek/patches", "-name", "*.diff", "-type", "f", "-print", "-quit"
                ]
                
                find_result = subprocess.run(find_cmd, capture_output=True, text=True, cwd=str(Path.cwd()), timeout=10)
                
                if find_result.returncode == 0 and find_result.stdout.strip():
                    # 如果找到多个文件，选择第一个
                    patch_files = find_result.stdout.strip().split('\n')
                    container_patch_path = patch_files[0]
                    self._log_message(task_id, f"✅ 在容器中找到补丁文件: {container_patch_path}")
                    if len(patch_files) > 1:
                        self._log_message(task_id, f"📋 找到 {len(patch_files)} 个补丁文件，使用第一个")
                    
                    # 从容器复制补丁文件到主机
                    copy_cmd = [
                        "docker", "cp", 
                        f"kgcompass-app:{container_patch_path}",
                        str(host_patch_path)
                    ]
                    
                    copy_result = subprocess.run(copy_cmd, capture_output=True, text=True, timeout=10)
                    
                    if copy_result.returncode == 0:
                        self._log_message(task_id, f"📄 补丁已复制到: {host_patch_path}")
                        patch_file_path = str(host_patch_path)
                    else:
                        self._log_message(task_id, f"⚠️ 复制补丁文件失败: {copy_result.stderr}")
                        patch_file_path = None
                else:
                    self._log_message(task_id, "⚠️ 未找到补丁文件")
                    patch_file_path = None
            
            # 如果找到补丁文件，显示预览
            if patch_file_path and Path(patch_file_path).exists():
                try:
                    with open(patch_file_path, 'r', encoding='utf-8') as f:
                        patch_content = f.read()
                    self._log_message(task_id, f"📄 补丁内容预览:")
                    # 显示前10行
                    preview_lines = patch_content.split('\n')[:10]
                    for line in preview_lines:
                        self._log_message(task_id, f"  {line}")
                    patch_lines_count = len(patch_content.split('\n'))
                    if patch_lines_count > 10:
                        self._log_message(task_id, f"  ... (总共 {patch_lines_count} 行)")
                except Exception as e:
                    self._log_message(task_id, f"⚠️ 无法读取补丁内容: {e}")
            
            # 生成修复报告
            report = {
                "instance_id": instance_id,
                "repo_identifier": repo_key,
                "repo_name": SUPPORTED_REPOS[repo_key]['name'],
                "repair_successful": patch_file_path is not None,
                "patch_file": patch_file_path,
                "docker_execution": True,
                "timestamp": datetime.now().isoformat()
            }
            
            report_file = output_dir / f"{instance_id}_report.json"
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            
            # 任务完成
            self._update_task_status(task_id, 'completed', 100, "✅ 修复完成!")
            self._log_message(task_id, f"🎉 {instance_id} 修复完成!")
            
            active_tasks[task_id].update({
                'end_time': datetime.now().isoformat(),
                'patch_file': patch_file_path,
                'repair_report': str(report_file)
            })
            
        except Exception as e:
            self._update_task_status(task_id, 'error', 0, f"❌ 错误: {str(e)}")
            self._log_message(task_id, f"❌ 修复失败: {str(e)}")
            active_tasks[task_id]['error'] = str(e)
    
    def _execute_custom_repair_pipeline(self, task_id: str, instance_id: str, 
                                       custom_repo_info: Dict, output_dir: Path):
        """执行自定义仓库的修复管道"""
        try:
            owner = custom_repo_info['owner']
            repo = custom_repo_info['repo']
            issue_number = custom_repo_info['issue_number']
            clone_url = custom_repo_info['clone_url']
            repo_identifier = f"{owner}__{repo}"
            
            self._log_message(task_id, f"🚀 开始为自定义仓库 {owner}/{repo} Issue #{issue_number} 执行修复流程")
            
            # 检查 Docker 环境
            self._update_task_status(task_id, 'checking_docker', 5, "🐳 检查 Docker 环境...")
            
            result = subprocess.run([
                "docker-compose", "ps", "-q", "app"
            ], capture_output=True, text=True, cwd=str(Path.cwd()))
            
            if result.returncode != 0 or not result.stdout.strip():
                self._log_message(task_id, "🐳 启动 Docker 服务...")
                start_result = subprocess.run([
                    "docker-compose", "up", "-d", "--build"
                ], capture_output=True, text=True, cwd=str(Path.cwd()))
                
                if start_result.returncode != 0:
                    raise Exception(f"Docker 服务启动失败: {start_result.stderr}")
                
                self._log_message(task_id, "✅ Docker 服务已启动")
                time.sleep(10)
            else:
                self._log_message(task_id, "✅ Docker 服务已运行")
            
            # 创建自定义修复脚本
            self._update_task_status(task_id, 'preparing', 10, "📝 准备自定义修复流程...")
            
            # 生成实例数据文件（模拟 SWE-bench 格式）
            self._create_custom_instance_file(task_id, instance_id, custom_repo_info, output_dir)
            
            # 构建 docker-compose exec 命令，使用自定义修复脚本
            self._update_task_status(task_id, 'docker_repair', 15, "🚀 在容器中执行修复...")
            self._log_message(task_id, f"🐳 在 Docker 容器中执行自定义修复: {instance_id}")
            
            docker_cmd = [
                "docker-compose", "exec", "-T", "app",
                "bash", "run_repair_custom.sh", 
                instance_id,
                clone_url,
                repo_identifier,
                issue_number
            ]
            
            env = os.environ.copy()
            
            # 执行修复命令并实时获取输出
            self._log_message(task_id, "🔄 开始执行修复流程...")
            
            process = subprocess.Popen(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(Path.cwd()),
                env=env,
                bufsize=1,
                universal_newlines=True
            )
            
            # 实时读取并发送日志
            step_progress = {
                'KG-based Bug Location': 40,
                'LLM-based Bug Location': 60,
                'Merge and Fix Bug Locations': 80,
                'Final Patch Generation': 95
            }
            
            current_progress = 15
            
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                
                if output:
                    line = output.strip()
                    self._log_message(task_id, line)
                    
                    # 根据输出内容更新进度
                    for step_name, progress in step_progress.items():
                        if step_name in line and progress > current_progress:
                            current_progress = progress
                            if 'KG-based' in step_name:
                                self._update_task_status(task_id, 'kg_mining', progress, "🔍 挖掘知识图谱...")
                            elif 'LLM-based' in step_name:
                                self._update_task_status(task_id, 'fault_localization', progress, "🎯 LLM 故障定位...")
                            elif 'Merge' in step_name:
                                self._update_task_status(task_id, 'merge_localization', progress, "🔗 合并定位结果...")
                            elif 'Patch Generation' in step_name:
                                self._update_task_status(task_id, 'patch_generation', progress, "⚡ 生成修复补丁...")
                            break
            
            # 等待进程完成
            return_code = process.poll()
            
            if return_code != 0:
                raise Exception(f"修复流程执行失败，返回码: {return_code}")
            
            # 查找生成的补丁文件
            self._update_task_status(task_id, 'collecting_results', 97, "📁 收集修复结果...")
            
            host_patch_path = output_dir / f"{instance_id}_patch.diff"
            patch_file_path = None
            
            if host_patch_path.exists():
                self._log_message(task_id, f"✅ 补丁文件已存在: {host_patch_path}")
                patch_file_path = str(host_patch_path)
            else:
                # 在容器中查找补丁文件
                self._log_message(task_id, "🔍 在容器中查找补丁文件...")
                find_cmd = [
                    "docker-compose", "exec", "-T", "app",
                    "find", f"/opt/KGCompass/tests/{instance_id}_deepseek/patches", 
                    "-name", "*.diff", "-type", "f", "-print", "-quit"
                ]
                
                find_result = subprocess.run(find_cmd, capture_output=True, text=True, 
                                            cwd=str(Path.cwd()), timeout=10)
                
                if find_result.returncode == 0 and find_result.stdout.strip():
                    container_patch_path = find_result.stdout.strip().split('\n')[0]
                    self._log_message(task_id, f"✅ 在容器中找到补丁文件: {container_patch_path}")
                    
                    # 从容器复制补丁文件到主机
                    copy_cmd = [
                        "docker", "cp",
                        f"kgcompass-app:{container_patch_path}",
                        str(host_patch_path)
                    ]
                    
                    copy_result = subprocess.run(copy_cmd, capture_output=True, text=True, timeout=10)
                    
                    if copy_result.returncode == 0:
                        self._log_message(task_id, f"📄 补丁已复制到: {host_patch_path}")
                        patch_file_path = str(host_patch_path)
                    else:
                        self._log_message(task_id, f"⚠️ 复制补丁文件失败: {copy_result.stderr}")
                else:
                    self._log_message(task_id, "⚠️ 未找到补丁文件")
            
            # 如果找到补丁文件，显示预览
            if patch_file_path and Path(patch_file_path).exists():
                try:
                    with open(patch_file_path, 'r', encoding='utf-8') as f:
                        patch_content = f.read()
                    self._log_message(task_id, f"📄 补丁内容预览:")
                    preview_lines = patch_content.split('\n')[:10]
                    for line in preview_lines:
                        self._log_message(task_id, f"  {line}")
                    patch_lines_count = len(patch_content.split('\n'))
                    if patch_lines_count > 10:
                        self._log_message(task_id, f"  ... (总共 {patch_lines_count} 行)")
                except Exception as e:
                    self._log_message(task_id, f"⚠️ 无法读取补丁内容: {e}")
            
            # 生成修复报告
            report = {
                "instance_id": instance_id,
                "repo_identifier": repo_identifier,
                "repo_name": custom_repo_info['repo_name'],
                "custom_repo": True,
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "repair_successful": patch_file_path is not None,
                "patch_file": patch_file_path,
                "docker_execution": True,
                "timestamp": datetime.now().isoformat()
            }
            
            report_file = output_dir / f"{instance_id}_report.json"
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            
            # 任务完成
            self._update_task_status(task_id, 'completed', 100, "✅ 修复完成!")
            self._log_message(task_id, f"🎉 {instance_id} 修复完成!")
            
            active_tasks[task_id].update({
                'end_time': datetime.now().isoformat(),
                'patch_file': patch_file_path,
                'repair_report': str(report_file)
            })
            
        except Exception as e:
            self._update_task_status(task_id, 'error', 0, f"❌ 错误: {str(e)}")
            self._log_message(task_id, f"❌ 修复失败: {str(e)}")
            active_tasks[task_id]['error'] = str(e)
    
    def _create_custom_instance_file(self, task_id: str, instance_id: str, 
                                    custom_repo_info: Dict, output_dir: Path):
        """
        为自定义仓库创建实例数据文件（模拟 SWE-bench 格式）
        重要：base_commit 应该是 Issue 创建时刻的 commit，防止数据泄露
        """
        try:
            # 获取 issue 详细信息
            owner = custom_repo_info['owner']
            repo_name = custom_repo_info['repo']
            issue_number = custom_repo_info['issue_number']
            full_repo_name = f"{owner}/{repo_name}"
            
            issue_info = GitHubHelper.get_issue_info(owner, repo_name, issue_number)
            
            if not issue_info:
                self._log_message(task_id, f"⚠️ 无法获取 Issue 详细信息，使用基本信息")
                issue_title = f"Issue #{issue_number}"
                issue_body = ""
                issue_created_at = datetime.now().isoformat()
                base_commit = custom_repo_info.get('default_branch', 'main')
            else:
                issue_title = issue_info['title']
                issue_body = issue_info['body'] or ""
                issue_created_at = issue_info['created_at']
                
                # 关键：获取 Issue 创建时刻的 commit
                self._log_message(task_id, f"🕐 Issue 创建于: {issue_created_at}")
                self._log_message(task_id, f"🔍 查找 Issue 创建时刻的 commit...")
                
                try:
                    # 使用 GitHub API 获取 Issue 创建时刻的 commit
                    from github import Github
                    from datetime import datetime as dt
                    
                    g = Github(os.environ.get('GITHUB_TOKEN'))
                    gh_repo = g.get_repo(full_repo_name)
                    
                    # 解析 created_at 时间
                    if isinstance(issue_created_at, str):
                        issue_dt = dt.fromisoformat(issue_created_at.replace('Z', '+00:00'))
                    else:
                        issue_dt = issue_created_at
                    
                    # 获取默认分支在 Issue 创建时刻之前的最新 commit
                    default_branch = gh_repo.default_branch
                    commits = gh_repo.get_commits(sha=default_branch, until=issue_dt)
                    
                    base_commit = commits[0].sha
                    commit_date = commits[0].commit.author.date
                    
                    self._log_message(task_id, f"✅ 找到 base_commit: {base_commit[:8]}")
                    self._log_message(task_id, f"   Commit 日期: {commit_date}")
                    
                except Exception as e:
                    self._log_message(task_id, f"⚠️ 无法获取历史 commit: {e}")
                    self._log_message(task_id, f"   使用默认分支: {custom_repo_info.get('default_branch', 'main')}")
                    base_commit = custom_repo_info.get('default_branch', 'main')
            
            # 创建实例数据
            instance_data = {
                "instance_id": instance_id,
                "repo": custom_repo_info['repo_name'],
                "problem_statement": f"# {issue_title}\n\n{issue_body}",
                "issue_number": issue_number,
                "base_commit": base_commit,  # 使用 Issue 创建时刻的 commit
                "custom_repo": True,
                "created_at": issue_created_at
            }
            
            # 保存到文件
            instance_file = output_dir / f"{instance_id}_instance.json"
            with open(instance_file, 'w', encoding='utf-8') as f:
                json.dump(instance_data, f, indent=2, ensure_ascii=False)
            
            self._log_message(task_id, f"📝 已创建实例数据文件: {instance_file}")
            
        except Exception as e:
            self._log_message(task_id, f"⚠️ 创建实例文件失败: {e}")
    
    
    def _update_task_status(self, task_id: str, status: str, progress: int, message: str):
        """更新任务状态"""
        if task_id in active_tasks:
            active_tasks[task_id].update({
                'status': status,
                'progress': progress,
                'current_step': message
            })
            
            socketio.emit('task_update', {
                'task_id': task_id,
                'status': status,
                'progress': progress,
                'message': message
            })
    
    def _log_message(self, task_id: str, message: str):
        """记录日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        
        if task_id not in task_logs:
            task_logs[task_id] = []
        task_logs[task_id].append(log_entry)
        
        socketio.emit('task_log', {
            'task_id': task_id,
            'message': log_entry
        })

# 全局任务管理器
task_manager = RepairTaskManager()

@app.route('/')
def index():
    """主页"""
    return render_template('index.html', 
                         repos=SUPPORTED_REPOS,
                         examples=EXAMPLE_ISSUES)

@app.route('/api/start_repair', methods=['POST'])
def start_repair():
    """启动修复任务（支持预定义仓库和自定义仓库）"""
    data = request.get_json()
    
    # 检查是否为自定义仓库模式
    is_custom = data.get('is_custom', False)
    
    if is_custom:
        # 自定义仓库模式
        github_url = data.get('github_url', '').strip()
        issue_number = data.get('issue_number', '').strip()
        
        if not github_url or not issue_number:
            return jsonify({'success': False, 'error': '请填写完整的 GitHub 仓库 URL 和 Issue 编号'}), 400
        
        # 解析 GitHub URL
        parsed = GitHubHelper.parse_github_url(github_url)
        if not parsed:
            return jsonify({'success': False, 'error': '无效的 GitHub 仓库 URL'}), 400
        
        owner, repo = parsed
        
        # 验证仓库是否存在
        if not GitHubHelper.validate_repo(owner, repo):
            return jsonify({'success': False, 'error': f'仓库 {owner}/{repo} 不存在或无法访问'}), 400
        
        # 获取仓库信息
        repo_info = GitHubHelper.get_repo_info(owner, repo)
        if not repo_info:
            return jsonify({'success': False, 'error': '无法获取仓库信息'}), 400
        
        # 验证 Issue 是否存在
        issue_info = GitHubHelper.get_issue_info(owner, repo, issue_number)
        if not issue_info:
            return jsonify({'success': False, 'error': f'Issue #{issue_number} 不存在'}), 400
        
        # 生成实例 ID (格式: owner__repo-issue_number)
        repo_identifier = f"{owner}__{repo}"
        instance_id = f"{repo_identifier}-{issue_number}"
        
        # 生成任务 ID
        task_id = str(uuid.uuid4())
        
        # 准备自定义仓库信息
        custom_repo_info = {
            'owner': owner,
            'repo': repo,
            'repo_name': f"{owner}/{repo}",
            'clone_url': repo_info['clone_url'],
            'issue_number': issue_number,
            'default_branch': repo_info.get('default_branch', 'main'),
            'issue_info': issue_info
        }
        
        # 启动任务
        success = task_manager.start_repair_task(
            task_id, 
            instance_id, 
            repo_key=None,
            custom_repo_info=custom_repo_info
        )
        
        if success:
            return jsonify({
                'success': True,
                'task_id': task_id,
                'instance_id': instance_id,
                'repo_name': f"{owner}/{repo}",
                'issue_number': issue_number,
                'issue_title': issue_info['title'],
                'message': '自定义仓库修复任务已启动'
            })
        else:
            return jsonify({
                'success': False,
                'error': '任务启动失败'
            }), 500
    
    else:
        # 预定义仓库模式（SWE-bench）
        issue_number = data.get('issue_number', '').strip()
        repo_key = data.get('repo_key', '').strip()
        
        if not issue_number or not repo_key:
            return jsonify({'success': False, 'error': '请填写完整的Issue ID和仓库'}), 400
        
        if repo_key not in SUPPORTED_REPOS:
            return jsonify({'success': False, 'error': f'不支持的仓库: {repo_key}'}), 400
        
        # 拼接完整的实例ID
        instance_id = f"{repo_key}-{issue_number}"
        
        # 生成任务ID
        task_id = str(uuid.uuid4())
        
        # 启动任务
        success = task_manager.start_repair_task(task_id, instance_id, repo_key)
        
        if success:
            return jsonify({
                'success': True,
                'task_id': task_id,
                'instance_id': instance_id,
                'message': '修复任务已启动'
            })
        else:
            return jsonify({
                'success': False,
                'error': '任务启动失败'
            }), 500

@app.route('/api/validate_github_repo', methods=['POST'])
def validate_github_repo():
    """验证 GitHub 仓库和 Issue"""
    data = request.get_json()
    github_url = data.get('github_url', '').strip()
    issue_number = data.get('issue_number', '').strip()
    
    if not github_url:
        return jsonify({'success': False, 'error': '请输入 GitHub 仓库 URL'}), 400
    
    # 解析 GitHub URL
    parsed = GitHubHelper.parse_github_url(github_url)
    if not parsed:
        return jsonify({
            'success': False,
            'error': '无效的 GitHub 仓库 URL',
            'hint': '支持格式: https://github.com/owner/repo 或 owner/repo'
        }), 400
    
    owner, repo = parsed
    
    # 验证仓库
    if not GitHubHelper.validate_repo(owner, repo):
        return jsonify({
            'success': False,
            'error': f'仓库 {owner}/{repo} 不存在或无法访问'
        }), 404
    
    # 获取仓库信息
    repo_info = GitHubHelper.get_repo_info(owner, repo)
    
    result = {
        'success': True,
        'owner': owner,
        'repo': repo,
        'repo_name': f"{owner}/{repo}",
        'repo_info': repo_info
    }
    
    # 如果提供了 issue_number，也验证 issue
    if issue_number:
        issue_info = GitHubHelper.get_issue_info(owner, repo, issue_number)
        if issue_info:
            result['issue_valid'] = True
            result['issue_info'] = issue_info
        else:
            result['issue_valid'] = False
            result['issue_error'] = f'Issue #{issue_number} 不存在'
    
    return jsonify(result)

@app.route('/api/tasks')
def get_all_tasks():
    """获取所有任务列表"""
    return jsonify({
        'success': True,
        'tasks': list(active_tasks.keys()),
        'active_count': len(active_tasks)
    })

@app.route('/api/task_status/<task_id>')
def get_task_status(task_id: str):
    """获取任务状态"""
    if task_id not in active_tasks:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    
    task = active_tasks[task_id]
    logs = task_logs.get(task_id, [])
    
    return jsonify({
        'success': True,
        'task': task,
        'logs': logs[-50:]  # 最近50条日志
    })

@app.route('/api/download_patch/<task_id>')
def download_patch(task_id: str):
    """下载补丁文件"""
    if task_id not in active_tasks:
        return jsonify({'error': '任务不存在'}), 404
    
    task = active_tasks[task_id]
    if 'patch_file' not in task or not task['patch_file']:
        return jsonify({'error': '补丁文件不存在'}), 404
    
    patch_file = Path(task['patch_file'])
    if not patch_file.exists():
        return jsonify({'error': '补丁文件未找到'}), 404
    
    return send_file(patch_file, as_attachment=True, download_name=f"{task['instance_id']}_patch.diff")

@app.route('/patch_view/<task_id>')
def view_patch(task_id: str):
    """查看补丁内容"""
    if task_id not in active_tasks:
        return "任务不存在", 404
    
    task = active_tasks[task_id]
    if 'patch_file' not in task or not task['patch_file']:
        return "补丁文件不存在", 404
    
    patch_file = Path(task['patch_file'])
    if not patch_file.exists():
        return "补丁文件未找到", 404
    
    # 读取补丁内容
    try:
        with open(patch_file, 'r', encoding='utf-8') as f:
            patch_content = f.read()
    except Exception as e:
        return f"无法读取补丁文件: {e}", 500
    
    # 解析补丁内容
    patch_lines = []
    stats = {'additions': 0, 'deletions': 0, 'files': 0}
    file_changes = []
    current_file = None
    
    for line in patch_content.split('\n'):
        line_type = 'patch-line-context'
        
        if line.startswith('---') or line.startswith('+++'):
            line_type = 'patch-line-hunk'
            if line.startswith('---'):
                # 新文件开始
                if current_file:
                    file_changes.append(current_file)
                current_file = {
                    'filename': line[4:].strip(),
                    'additions': 0,
                    'deletions': 0,
                    'changes': 0
                }
                stats['files'] += 1
        elif line.startswith('@@'):
            line_type = 'patch-line-hunk'
        elif line.startswith('+') and not line.startswith('+++'):
            line_type = 'patch-line-added'
            stats['additions'] += 1
            if current_file:
                current_file['additions'] += 1
                current_file['changes'] += 1
        elif line.startswith('-') and not line.startswith('---'):
            line_type = 'patch-line-removed'
            stats['deletions'] += 1
            if current_file:
                current_file['deletions'] += 1
                current_file['changes'] += 1
        
        patch_lines.append({
            'content': line,
            'type': line_type
        })
    
    if current_file:
        file_changes.append(current_file)
    
    return render_template('patch_view.html',
                         instance_id=task['instance_id'],
                         repo_name=task['repo_name'],
                         patch_content=patch_content,
                         patch_lines=patch_lines,
                         stats=stats,
                         file_changes=file_changes,
                         download_url=f'/api/download_patch/{task_id}')

@socketio.on('connect')
def handle_connect():
    """WebSocket连接处理"""
    emit('connected', {'message': '已连接到KGCompass修复服务'})

@socketio.on('disconnect')
def handle_disconnect():
    """WebSocket断开处理"""
    print('客户端断开连接')

if __name__ == '__main__':
    # 创建输出目录
    Path("web_outputs").mkdir(exist_ok=True)
    
    print("🚀 启动 KGCompass Web 界面...")
    print("📡 访问地址: http://localhost:5000")
    
    # 获取调试模式设置，默认关闭以避免监控过多文件
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    
    if debug_mode:
        print("🔧 调试模式已启用")
        # 设置更严格的文件监控
        from werkzeug.serving import make_ssl_devcert, run_with_reloader
        # 只监控核心文件，排除仓库目录
        import sys
        if hasattr(sys, '_getframe'):
            # 限制监控范围到当前应用文件
            extra_files = ['app.py', 'templates/', 'static/']
            app.config['TEMPLATES_AUTO_RELOAD'] = True
    else:
        print("📊 生产模式运行（无文件监控）")
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=debug_mode) 