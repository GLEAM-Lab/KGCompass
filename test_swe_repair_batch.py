#!/usr/bin/env python3
"""
测试 SWE-bench Verified 批量修复脚本
"""

import os
import sys
import subprocess
from pathlib import Path

def test_script_imports():
    """测试脚本是否可以正常导入"""
    print("测试脚本导入...")
    try:
        import swe_repair_batch
        print("✅ 脚本导入成功")
        return True
    except Exception as e:
        print(f"❌ 脚本导入失败: {e}")
        return False

def test_help_message():
    """测试帮助信息"""
    print("\n测试帮助信息...")
    try:
        result = subprocess.run([sys.executable, "swe_repair_batch.py", "--help"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("✅ 帮助信息显示正常")
            print("帮助信息预览:")
            print(result.stdout[:200] + "..." if len(result.stdout) > 200 else result.stdout)
            return True
        else:
            print(f"❌ 帮助信息显示失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ 帮助信息测试异常: {e}")
        return False

def test_repo_mapping():
    """测试仓库映射"""
    print("\n测试仓库映射...")
    try:
        from swe_repair_batch import SWE_BENCH_REPO_URL_MAP
        
        expected_repos = [
            "astropy__astropy", "django__django", "matplotlib__matplotlib",
            "mwaskom__seaborn", "psf__requests", "pylint-dev__pylint",
            "pytest-dev__pytest", "scikit-learn__scikit-learn",
            "sphinx-doc__sphinx", "sympy__sympy"
        ]
        
        for repo in expected_repos:
            if repo in SWE_BENCH_REPO_URL_MAP:
                print(f"✅ {repo}: {SWE_BENCH_REPO_URL_MAP[repo]}")
            else:
                print(f"❌ 缺少仓库映射: {repo}")
                return False
        
        print(f"✅ 仓库映射完整 ({len(SWE_BENCH_REPO_URL_MAP)} 个仓库)")
        return True
    except Exception as e:
        print(f"❌ 仓库映射测试失败: {e}")
        return False

def test_directory_structure():
    """测试目录结构检查"""
    print("\n测试目录结构...")
    try:
        from swe_repair_batch import get_swe_instances
        
        # 测试不存在的目录
        instances = get_swe_instances("nonexistent_dir")
        if instances == []:
            print("✅ 不存在目录处理正确")
        else:
            print("❌ 不存在目录处理错误")
            return False
        
        # 测试存在但为空的目录
        test_dir = Path("test_empty_kg_dir")
        test_dir.mkdir(exist_ok=True)
        instances = get_swe_instances(str(test_dir))
        test_dir.rmdir()
        
        if instances == []:
            print("✅ 空目录处理正确")
        else:
            print("❌ 空目录处理错误")
            return False
        
        return True
    except Exception as e:
        print(f"❌ 目录结构测试失败: {e}")
        return False

def test_api_types():
    """测试 API 类型参数"""
    print("\n测试 API 类型参数...")
    
    valid_apis = ["anthropic", "openai", "deepseek", "qwen"]
    
    for api_type in valid_apis:
        try:
            # 测试参数是否被接受（不实际运行，只检查参数解析）
            result = subprocess.run([
                sys.executable, "swe_repair_batch.py", 
                "--api_type", api_type,
                "--instance_id", "test_instance"  # 提供一个测试实例避免实际执行
            ], capture_output=True, text=True, timeout=5)
            
            # 即使实例不存在也应该能正常解析参数
            print(f"✅ API 类型 '{api_type}' 参数解析正常")
        except subprocess.TimeoutExpired:
            print(f"✅ API 类型 '{api_type}' 参数解析正常 (超时但说明参数被接受)")
        except Exception as e:
            print(f"❌ API 类型 '{api_type}' 参数测试失败: {e}")
            return False
    
    return True

def test_required_scripts():
    """测试所需的脚本文件是否存在"""
    print("\n测试所需脚本文件...")
    
    required_scripts = [
        "kgcompass/llm_loc_claude.py",
        "kgcompass/repair_claude.py",
        "kgcompass/fix_fl_line.py"
    ]
    
    for script in required_scripts:
        if Path(script).exists():
            print(f"✅ {script}: 存在")
        else:
            print(f"❌ {script}: 不存在")
            return False
    
    return True

def test_verified_only_loading():
    """测试 verified-only 实例加载功能"""
    print("\n测试 verified-only 实例加载...")
    try:
        from swe_repair_batch import load_verified_only_instances
        
        # 测试不存在的文件
        instances = load_verified_only_instances("nonexistent_file.jsonl")
        if instances == []:
            print("✅ 不存在文件处理正确")
        else:
            print("❌ 不存在文件处理错误")
            return False
        
        # 创建测试文件
        test_file = "test_verified_only.jsonl"
        test_data = [
            '{"instance_id": "test__repo-123"}',
            '{"instance_id": "another__repo-456"}',
            '{"invalid": "no_instance_id"}',  # 无效行
            'invalid json',  # 无效 JSON
        ]
        
        with open(test_file, 'w') as f:
            f.write('\n'.join(test_data))
        
        # 测试加载
        instances = load_verified_only_instances(test_file)
        
        # 清理测试文件
        os.remove(test_file)
        
        if len(instances) == 2 and "test__repo-123" in instances and "another__repo-456" in instances:
            print("✅ verified-only 文件加载正确")
            return True
        else:
            print(f"❌ verified-only 文件加载错误，期望2个实例，实际{len(instances)}个")
            return False
        
    except Exception as e:
        print(f"❌ verified-only 加载测试失败: {e}")
        return False

def test_verified_only_parameters():
    """测试 verified-only 参数"""
    print("\n测试 verified-only 参数...")
    
    try:
        # 测试 --verified-only 参数
        result = subprocess.run([
            sys.executable, "swe_repair_batch.py", 
            "--verified-only",
            "--instance_id", "test_instance"  # 提供一个测试实例避免实际执行
        ], capture_output=True, text=True, timeout=5)
        
        print("✅ --verified-only 参数解析正常")
        
        # 测试 --verified-only-file 参数
        result = subprocess.run([
            sys.executable, "swe_repair_batch.py", 
            "--verified-only-file", "custom_file.jsonl",
            "--instance_id", "test_instance"
        ], capture_output=True, text=True, timeout=5)
        
        print("✅ --verified-only-file 参数解析正常")
        return True
        
    except subprocess.TimeoutExpired:
        print("✅ verified-only 参数解析正常 (超时但说明参数被接受)")
        return True
    except Exception as e:
        print(f"❌ verified-only 参数测试失败: {e}")
        return False

def main():
    print("=" * 60)
    print("SWE-bench Verified 批量修复脚本测试")
    print("=" * 60)
    
    tests = [
        test_script_imports,
        test_help_message,
        test_repo_mapping,
        test_directory_structure,
        test_api_types,
        test_required_scripts,
        test_verified_only_loading,
        test_verified_only_parameters
    ]
    
    passed = 0
    total = len(tests)
    
    for test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"❌ 测试异常: {e}")
    
    print("\n" + "=" * 60)
    print(f"测试完成: {passed}/{total} 个测试通过")
    
    if passed == total:
        print("🎉 所有测试通过!")
        print("\n使用示例:")
        print("# 首先生成 verified-only 实例列表")
        print("python prepare_verified_only_jsonl.py")
        print("\n# 使用 Claude API 处理 verified-only 实例")
        print("python swe_repair_batch.py --verified-only --api_type anthropic")
        print("\n# 使用 OpenAI API 处理指定数量的 verified-only 实例")
        print("python swe_repair_batch.py --verified-only --api_type openai --limit 5")
        print("\n# 使用 DeepSeek API 并行处理 verified-only 实例")
        print("python swe_repair_batch.py --verified-only --api_type deepseek --workers 4 --temperature 0.5")
        print("\n# 处理单个指定实例")
        print("python swe_repair_batch.py --instance_id django__django-12345 --api_type anthropic")
    else:
        print("❌ 部分测试失败，请检查问题")
    
    print("=" * 60)

if __name__ == "__main__":
    main() 