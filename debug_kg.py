#!/usr/bin/env python3
"""
诊断脚本：检查知识图谱中的节点和关系
用于调试为什么没有生成方法和类
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'kgcompass'))
from neo4j import GraphDatabase
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

def check_kg_state(instance_id):
    """检查知识图谱中的节点和关系状态"""
    # 清理instance_id用作数据库名
    db_name = instance_id.replace('-', '').replace('_', '')
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    try:
        with driver.session() as session:
            print(f"\n{'='*80}")
            print(f"诊断知识图谱: {instance_id}")
            print(f"{'='*80}\n")
            
            # 1. 检查是否有root节点
            print("1. 检查Root节点:")
            root_query = """
            MATCH (root:Issue {id: 'root'})
            RETURN root.title as title, 
                   root.content as content,
                   root.embedding IS NOT NULL as has_embedding
            """
            root_result = session.run(root_query).single()
            if root_result:
                print(f"   ✓ Root节点存在")
                print(f"   - 标题: {root_result['title'][:100]}...")
                print(f"   - 有Embedding: {root_result['has_embedding']}")
            else:
                print(f"   ✗ 未找到Root节点")
                return
            
            # 2. 统计各类节点数量
            print("\n2. 节点统计:")
            count_query = """
            MATCH (n)
            RETURN labels(n)[0] as label, count(*) as count
            ORDER BY count DESC
            """
            for record in session.run(count_query):
                print(f"   - {record['label']}: {record['count']} 个")
            
            # 3. 检查Method节点
            print("\n3. Method节点详情:")
            method_query = """
            MATCH (m:Method)
            RETURN count(m) as total,
                   count(CASE WHEN m.embedding IS NOT NULL THEN 1 END) as with_embedding
            """
            method_result = session.run(method_query).single()
            if method_result:
                print(f"   - 总数: {method_result['total']}")
                print(f"   - 有Embedding: {method_result['with_embedding']}")
                
                # 显示几个Method示例
                sample_query = """
                MATCH (m:Method)
                RETURN m.name as name, m.file_path as file_path, 
                       m.embedding IS NOT NULL as has_embedding
                LIMIT 5
                """
                print("   - 示例:")
                for record in session.run(sample_query):
                    print(f"     * {record['name']} ({record['file_path']}) - Embedding: {record['has_embedding']}")
            
            # 4. 检查Class节点
            print("\n4. Class节点详情:")
            class_query = """
            MATCH (c:Class)
            RETURN count(c) as total,
                   count(CASE WHEN c.embedding IS NOT NULL THEN 1 END) as with_embedding
            """
            class_result = session.run(class_query).single()
            if class_result:
                print(f"   - 总数: {class_result['total']}")
                print(f"   - 有Embedding: {class_result['with_embedding']}")
            
            # 5. 检查root到Method/Class的连通性
            print("\n5. 连通性分析:")
            
            # Root -> Issue -> File -> Method 路径
            path_query = """
            MATCH path = (root:Issue {id: 'root'})-[:RELATED*1..5]-(m:Method)
            WITH m, length(path) as path_length
            RETURN count(DISTINCT m) as reachable_methods, 
                   min(path_length) as min_hops,
                   max(path_length) as max_hops
            """
            path_result = session.run(path_query).single()
            if path_result and path_result['reachable_methods']:
                print(f"   ✓ 可达的Method节点: {path_result['reachable_methods']} 个")
                print(f"   - 最短路径: {path_result['min_hops']} 跳")
                print(f"   - 最长路径: {path_result['max_hops']} 跳")
            else:
                print(f"   ✗ 没有Method节点可从root到达")
            
            # Root -> Class 路径
            class_path_query = """
            MATCH path = (root:Issue {id: 'root'})-[:RELATED*1..5]-(c:Class)
            WITH c, length(path) as path_length
            RETURN count(DISTINCT c) as reachable_classes,
                   min(path_length) as min_hops,
                   max(path_length) as max_hops
            """
            class_path_result = session.run(class_path_query).single()
            if class_path_result and class_path_result['reachable_classes']:
                print(f"   ✓ 可达的Class节点: {class_path_result['reachable_classes']} 个")
                print(f"   - 最短路径: {class_path_result['min_hops']} 跳")
                print(f"   - 最长路径: {class_path_result['max_hops']} 跳")
            else:
                print(f"   ✗ 没有Class节点可从root到达")
            
            # 6. 检查关系类型
            print("\n6. 关系统计:")
            rel_query = """
            MATCH ()-[r:RELATED]->()
            RETURN r.description as description, count(*) as count
            ORDER BY count DESC
            LIMIT 10
            """
            for record in session.run(rel_query):
                print(f"   - {record['description']}: {record['count']} 个")
            
            # 7. 检查root的直接关系
            print("\n7. Root的直接关系:")
            root_rel_query = """
            MATCH (root:Issue {id: 'root'})-[r:RELATED]-(n)
            RETURN labels(n)[0] as node_type, 
                   r.description as relationship,
                   count(*) as count
            """
            for record in session.run(root_rel_query):
                print(f"   - {record['relationship']} -> {record['node_type']}: {record['count']} 个")
            
            # 8. 检查一个完整的路径示例
            print("\n8. 路径示例 (Root -> ... -> Method):")
            path_example_query = """
            MATCH path = (root:Issue {id: 'root'})-[:RELATED*1..4]-(m:Method)
            WITH path, m
            LIMIT 1
            UNWIND nodes(path) as node
            RETURN labels(node)[0] as type,
                   CASE 
                       WHEN node:Issue THEN node.id
                       WHEN node:File THEN node.path
                       WHEN node:Method THEN node.name
                       WHEN node:Class THEN node.name
                       ELSE 'unknown'
                   END as identifier
            """
            path_nodes = list(session.run(path_example_query))
            if path_nodes:
                print("   路径: ", end="")
                for i, record in enumerate(path_nodes):
                    if i > 0:
                        print(" -> ", end="")
                    print(f"{record['type']}({record['identifier']})", end="")
                print()
            else:
                print("   ✗ 无法找到从root到Method的路径")
            
            print(f"\n{'='*80}")
            print("诊断完成")
            print(f"{'='*80}\n")
            
    finally:
        driver.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python debug_kg.py <instance_id>")
        print("示例: python debug_kg.py pytest-dev__pytest-5262")
        sys.exit(1)
    
    instance_id = sys.argv[1]
    check_kg_state(instance_id)

