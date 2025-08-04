#!/usr/bin/env python3
"""
KGCompass Web Interface Demo
简单的演示脚本，用于测试 Web 界面的基本功能
"""

import os
import time
import subprocess
import threading
from pathlib import Path

def check_dependencies():
    """检查必要的依赖"""
    print("🔍 检查依赖...")
    
    try:
        import flask
        try:
            version = flask.__version__
        except AttributeError:
            # Flask 3.1+ 移除了 __version__
            import importlib.metadata
            version = importlib.metadata.version("flask")
        print(f"✅ Flask: {version}")
    except ImportError:
        print("❌ Flask 未安装")
        return False
    
    try:
        import flask_socketio
        try:
            version = flask_socketio.__version__
        except AttributeError:
            import importlib.metadata
            version = importlib.metadata.version("flask-socketio")
        print(f"✅ Flask-SocketIO: {version}")
    except ImportError:
        print("❌ Flask-SocketIO 未安装")
        return False
    
    return True

def check_files():
    """检查必要的文件"""
    print("📁 检查文件...")
    
    required_files = [
        "app.py",
        "templates/index.html",
        "static/css/style.css",
        "static/js/app.js",
        "requirements_web.txt"
    ]
    
    missing_files = []
    for file_path in required_files:
        if not Path(file_path).exists():
            missing_files.append(file_path)
            print(f"❌ 缺少: {file_path}")
        else:
            print(f"✅ 存在: {file_path}")
    
    return len(missing_files) == 0

def create_demo_output():
    """创建演示输出目录和文件"""
    print("📁 创建演示输出...")
    
    output_dir = Path("web_outputs")
    output_dir.mkdir(exist_ok=True)
    
    # 创建一个示例任务输出
    demo_task_dir = output_dir / "demo-task-123"
    demo_task_dir.mkdir(exist_ok=True)
    
    # 创建示例补丁文件
    patch_content = """--- a/example.py
+++ b/example.py
@@ -10,6 +10,9 @@ def example_function():
     if condition:
         return True
 
+    # Fix: Add proper error handling
+    if not isinstance(data, list):
+        raise ValueError("Data must be a list")
+
     return False
"""
    
    with open(demo_task_dir / "demo_patch.diff", "w") as f:
        f.write(patch_content)
    
    print(f"✅ 创建演示输出: {demo_task_dir}")

def run_quick_test():
    """运行快速测试"""
    print("\n🧪 运行快速测试...")
    
    try:
        # 测试导入 app 模块
        import app
        print("✅ app.py 可以正常导入")
        
        # 测试基本配置
        if hasattr(app, 'SUPPORTED_REPOS'):
            repo_count = len(app.SUPPORTED_REPOS)
            print(f"✅ 支持 {repo_count} 个仓库")
        
        if hasattr(app, 'EXAMPLE_ISSUES'):
            example_count = sum(len(issues) for issues in app.EXAMPLE_ISSUES.values())
            print(f"✅ 包含 {example_count} 个示例Issue")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

def start_demo_server():
    """启动演示服务器"""
    print("\n🚀 启动演示服务器...")
    print("📡 访问地址: http://localhost:5000")
    print("🛑 按 Ctrl+C 停止服务器")
    print("=" * 50)
    
    try:
        import app
        app.socketio.run(app.app, host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\n👋 服务器已停止")
    except Exception as e:
        print(f"\n❌ 服务器启动失败: {e}")

def main():
    """主函数"""
    print("🎯 KGCompass Web 界面演示")
    print("=" * 50)
    
    # 检查依赖
    if not check_dependencies():
        print("\n❌ 依赖检查失败，请运行:")
        print("pip install -r requirements_web.txt")
        return
    
    # 检查文件
    if not check_files():
        print("\n❌ 文件检查失败，请确保所有必要文件都已创建")
        return
    
    # 创建演示输出
    create_demo_output()
    
    # 运行测试
    if not run_quick_test():
        print("\n❌ 快速测试失败")
        return
    
    print("\n✅ 所有检查通过!")
    
    # 询问是否启动服务器
    response = input("\n启动演示服务器吗? (y/N): ").strip().lower()
    if response in ['y', 'yes']:
        start_demo_server()
    else:
        print("\n💡 手动启动命令:")
        print("python3 app.py")
        print("或者:")
        print("./start_web.sh")

if __name__ == "__main__":
    main() 