#!/usr/bin/env python3
"""
测试自定义仓库功能
"""

import requests
import sys

def test_github_api():
    """测试 GitHub API 功能"""
    print("=" * 60)
    print("测试 GitHub API 功能")
    print("=" * 60)
    
    # 测试仓库信息获取
    test_cases = [
        ("https://github.com/pallets/flask", "flask"),
        ("psf/requests", "requests"),
        ("django/django", "django"),
    ]
    
    for url, name in test_cases:
        print(f"\n测试仓库: {name}")
        print(f"URL: {url}")
        
        # 解析 URL
        if url.startswith('http'):
            parts = url.replace('https://github.com/', '').replace('http://github.com/', '').strip('/')
        else:
            parts = url
        
        owner, repo = parts.split('/')
        
        # 获取仓库信息
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        
        try:
            response = requests.get(api_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ 仓库存在")
                print(f"  描述: {data.get('description', 'N/A')}")
                print(f"  Stars: {data.get('stargazers_count', 0)}")
                print(f"  语言: {data.get('language', 'Unknown')}")
            else:
                print(f"  ❌ 获取失败: {response.status_code}")
        except Exception as e:
            print(f"  ❌ 错误: {e}")
    
    print("\n" + "=" * 60)

def test_flask_api():
    """测试 Flask API 端点"""
    print("\n" + "=" * 60)
    print("测试 Flask API 端点")
    print("=" * 60)
    
    # 启动 Flask app（需要在另一个进程中运行）
    base_url = "http://localhost:5000"
    
    print(f"\n请确保 Flask 服务已启动在 {base_url}")
    print("运行命令: python app.py\n")
    
    # 测试验证端点
    test_data = {
        'github_url': 'https://github.com/pallets/flask',
        'issue_number': '4992'
    }
    
    print(f"测试数据: {test_data}")
    
    try:
        response = requests.post(
            f"{base_url}/api/validate_github_repo",
            json=test_data,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            print("  ✅ API 响应成功")
            print(f"  仓库: {result.get('repo_name', 'N/A')}")
            print(f"  Issue 有效: {result.get('issue_valid', False)}")
        else:
            print(f"  ❌ API 响应失败: {response.status_code}")
    except requests.exceptions.ConnectionError:
        print("  ⚠️  无法连接到 Flask 服务器")
        print("     请先运行: python app.py")
    except Exception as e:
        print(f"  ❌ 错误: {e}")
    
    print("\n" + "=" * 60)

def test_url_parsing():
    """测试 URL 解析功能"""
    print("\n" + "=" * 60)
    print("测试 URL 解析功能")
    print("=" * 60)
    
    test_urls = [
        "https://github.com/pallets/flask",
        "https://github.com/pallets/flask.git",
        "github.com/pallets/flask",
        "pallets/flask",
    ]
    
    import re
    
    for url in test_urls:
        print(f"\n测试 URL: {url}")
        
        # 模拟解析逻辑
        url_clean = url.strip()
        
        if url_clean.endswith('.git'):
            url_clean = url_clean[:-4]
        
        url_clean = url_clean.rstrip('/')
        
        patterns = [
            r'https?://github\.com/([^/]+)/([^/]+)',
            r'github\.com/([^/]+)/([^/]+)',
            r'^([^/]+)/([^/]+)$'
        ]
        
        parsed = False
        for pattern in patterns:
            match = re.match(pattern, url_clean)
            if match:
                owner, repo = match.groups()
                repo = repo.split('?')[0]
                print(f"  ✅ 解析成功: owner={owner}, repo={repo}")
                parsed = True
                break
        
        if not parsed:
            print(f"  ❌ 解析失败")
    
    print("\n" + "=" * 60)

def main():
    """主函数"""
    print("\n🚀 KGCompass 自定义仓库功能测试\n")
    
    # 测试 1: GitHub API
    test_github_api()
    
    # 测试 2: URL 解析
    test_url_parsing()
    
    # 测试 3: Flask API（需要服务器运行）
    if '--with-flask' in sys.argv:
        test_flask_api()
    else:
        print("\n提示: 添加 --with-flask 参数来测试 Flask API 端点")
    
    print("\n✅ 测试完成！\n")

if __name__ == '__main__':
    main()






