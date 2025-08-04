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
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kgcompass-web-interface'
socketio = SocketIO(app, cors_allowed_origins="*")

# 全局变量存储任务状态
active_tasks: Dict[str, Dict] = {}
task_logs: Dict[str, List[str]] = {}

# 支持的仓库列表（从项目中提取）
SUPPORTED_REPOS = {
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
    }
}

# 示例 Issue IDs
EXAMPLE_ISSUES = {
    "astropy__astropy": ["astropy__astropy-12907", "astropy__astropy-13033", "astropy__astropy-13236"],
    "django__django": ["django__django-11001", "django__django-11179", "django__django-11283"],
    "matplotlib__matplotlib": ["matplotlib__matplotlib-13989", "matplotlib__matplotlib-14471"],
    "scikit-learn__scikit-learn": ["scikit-learn__scikit-learn-13497", "scikit-learn__scikit-learn-13779"],
    "sympy__sympy": ["sympy__sympy-15308", "sympy__sympy-15346", "sympy__sympy-15678"]
}

class RepairTaskManager:
    """修复任务管理器"""
    
    def __init__(self):
        self.output_dir = Path("web_outputs")
        self.output_dir.mkdir(exist_ok=True)
    
    def start_repair_task(self, task_id: str, instance_id: str, repo_key: str) -> bool:
        """启动修复任务"""
        try:
            # 验证输入
            if repo_key not in SUPPORTED_REPOS:
                raise ValueError(f"不支持的仓库: {repo_key}")
            
            # 创建任务状态
            active_tasks[task_id] = {
                'instance_id': instance_id,
                'repo_key': repo_key,
                'repo_name': SUPPORTED_REPOS[repo_key]['name'],
                'status': 'initializing',
                'start_time': datetime.now().isoformat(),
                'current_step': 'prepare',
                'progress': 0,
                'output_dir': str(self.output_dir / task_id)
            }
            task_logs[task_id] = []
            
            # 创建输出目录
            task_output_dir = self.output_dir / task_id
            task_output_dir.mkdir(exist_ok=True)
            
            # 在新线程中执行修复任务
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
            
            # 在容器中查找补丁文件
            find_cmd = [
                "docker-compose", "exec", "-T", "app",
                "find", f"/opt/KGCompass/runs", "-name", f"{instance_id}.patch", "-type", "f"
            ]
            
            find_result = subprocess.run(find_cmd, capture_output=True, text=True, cwd=str(Path.cwd()))
            
            if find_result.returncode == 0 and find_result.stdout.strip():
                container_patch_path = find_result.stdout.strip()
                self._log_message(task_id, f"✅ 在容器中找到补丁文件: {container_patch_path}")
                
                # 从容器复制补丁文件到主机
                host_patch_path = output_dir / f"{instance_id}_patch.diff"
                copy_cmd = [
                    "docker", "cp", 
                    f"kgcompass-app:{container_patch_path}",
                    str(host_patch_path)
                ]
                
                copy_result = subprocess.run(copy_cmd, capture_output=True, text=True)
                
                if copy_result.returncode == 0:
                    self._log_message(task_id, f"📄 补丁已复制到: {host_patch_path}")
                    
                    # 读取并显示补丁内容
                    try:
                        with open(host_patch_path, 'r', encoding='utf-8') as f:
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
                    
                    patch_file_path = str(host_patch_path)
                else:
                    self._log_message(task_id, f"⚠️ 复制补丁文件失败: {copy_result.stderr}")
                    patch_file_path = None
            else:
                self._log_message(task_id, "⚠️ 未找到补丁文件")
                patch_file_path = None
            
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
    """启动修复任务"""
    data = request.get_json()
    instance_id = data.get('instance_id', '').strip()
    repo_key = data.get('repo_key', '').strip()
    
    if not instance_id or not repo_key:
        return jsonify({'success': False, 'error': '请填写完整的实例ID和仓库'}), 400
    
    if repo_key not in SUPPORTED_REPOS:
        return jsonify({'success': False, 'error': f'不支持的仓库: {repo_key}'}), 400
    
    # 生成任务ID
    task_id = str(uuid.uuid4())
    
    # 启动任务
    success = task_manager.start_repair_task(task_id, instance_id, repo_key)
    
    if success:
        return jsonify({
            'success': True, 
            'task_id': task_id,
            'message': '修复任务已启动'
        })
    else:
        return jsonify({
            'success': False, 
            'error': '任务启动失败'
        }), 500

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
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=True) 