#!/usr/bin/env python3
"""
Test script for repair_claude.py API integration
"""

import os
import sys
sys.path.append('kgcompass')

from repair_claude import CodeRepair

def test_api_initialization():
    """测试不同 API 的初始化"""
    print("Testing API initialization...")
    
    # Test all API types
    api_types = ['deepseek', 'openai', 'anthropic', 'qwen']
    
    for api_type in api_types:
        try:
            repairer = CodeRepair(language='python', api_type=api_type, temperature=0.3)
            print(f"✅ {api_type}: Successfully initialized")
            print(f"   Model: {repairer.model}")
            print(f"   Max input length: {repairer.MAX_INPUT_LENGTH}")
        except Exception as e:
            print(f"❌ {api_type}: Failed to initialize - {e}")
        print()

def test_token_counting():
    """测试 token 计数功能"""
    print("Testing token counting...")
    
    test_text = "Hello, this is a test message for token counting."
    
    for api_type in ['deepseek', 'anthropic']:
        try:
            repairer = CodeRepair(language='python', api_type=api_type, temperature=0.3)
            token_count = repairer.count_tokens(test_text)
            print(f"✅ {api_type}: Token count = {token_count}")
        except Exception as e:
            print(f"❌ {api_type}: Token counting failed - {e}")

def test_simple_completion():
    """测试简单的 LLM 调用（需要有效的 API key）"""
    print("Testing simple completion (requires valid API keys)...")
    
    simple_prompt = "What is 2+2? Please answer briefly."
    
    # 只测试有 API key 的服务
    test_apis = []
    if os.getenv('CLAUDE_API_KEY'):
        test_apis.append('anthropic')
    if os.getenv('DEEPSEEK_API_KEY') or os.getenv('BAILIAN_API_KEY'):
        test_apis.append('deepseek')
    
    for api_type in test_apis:
        try:
            print(f"\nTesting {api_type}...")
            repairer = CodeRepair(language='python', api_type=api_type, temperature=0.3)
            response = repairer.get_completion(simple_prompt, stream=False)
            if response:
                print(f"✅ {api_type}: Response received")
                print(f"   Response preview: {response[:100]}...")
            else:
                print(f"❌ {api_type}: No response received")
        except Exception as e:
            print(f"❌ {api_type}: Completion failed - {e}")

if __name__ == "__main__":
    print("=" * 60)
    print("Testing repair_claude.py Multi-API Support")
    print("=" * 60)
    
    test_api_initialization()
    print("\n" + "=" * 60)
    
    test_token_counting()
    print("\n" + "=" * 60)
    
    test_simple_completion()
    print("\n" + "=" * 60)
    print("Testing completed!") 