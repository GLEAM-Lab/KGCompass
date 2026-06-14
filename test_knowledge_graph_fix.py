#!/usr/bin/env python3
"""
测试 KnowledgeGraph 中的源码截断和参数修复功能
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'kgcompass'))

from kgcompass.knowledge_graph import KnowledgeGraph
from kgcompass.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

def test_large_source_code():
    """测试大源码处理"""
    print("🧪 测试大源码截断功能...")
    
    # 创建一个测试用的 KG 实例
    kg = KnowledgeGraph(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, "test_db")
    
    try:
        # 清理数据库
        kg.clear_graph()
        kg._create_indexes()
        
        # 创建一个大的源码字符串 (超过 20000 字符)
        large_source_code = "def test_method():\n" + "    # " + "x" * 25000 + "\n    pass"
        
        print(f"📏 源码长度: {len(large_source_code)} 字符")
        
        # 测试创建方法实体
        kg.create_method_entity(
            method_name="test_method",
            method_signature="test_method()",
            file_path="test/test_file.py",
            start_line=1,
            end_line=3,
            source_code=large_source_code,
            doc_string="Test method with large source code",
            weight=1
        )
        
        print("✅ 大源码方法创建成功！")
        
        # 测试创建类实体
        large_class_code = "class TestClass:\n" + "    # " + "y" * 25000 + "\n    pass"
        
        kg.create_class_entity(
            class_name="TestClass",
            file_path="test/test_file.py",
            start_line=5,
            end_line=7,
            source_code=large_class_code,
            doc_string="Test class with large source code",
            weight=1
        )
        
        print("✅ 大源码类创建成功！")
        
        # 测试重复创建（更新路径）
        kg.create_method_entity(
            method_name="test_method",
            method_signature="test_method()",
            file_path="test/test_file.py",
            start_line=1,
            end_line=3,
            source_code="def test_method():\n    print('updated')\n    pass",
            doc_string="Updated test method",
            weight=1
        )
        
        print("✅ 方法更新成功！")
        
        print("🎉 所有测试通过！Neo4j 源码截断和参数修复正常工作。")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        print(traceback.format_exc())
    finally:
        # 清理测试数据
        kg.clear_graph()
        kg.close()

if __name__ == "__main__":
    test_large_source_code() 