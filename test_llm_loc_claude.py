#!/usr/bin/env python3
"""
Test script for llm_loc_claude.py API integration
"""

import os
import sys
sys.path.append('kgcompass')

from llm_loc_claude import PreFaultLocalization

def test_api_initialization():
    """测试不同 API 的初始化"""
    print("Testing API initialization...")
    
    # Test all API types
    api_types = ['deepseek', 'openai', 'anthropic', 'qwen']
    
    for api_type in api_types:
        try:
            pre_fl = PreFaultLocalization(
                instance_id="test-instance", 
                benchmark_type="swe-bench", 
                api_type=api_type, 
                temperature=0.3
            )
            print(f"✅ {api_type}: Successfully initialized")
            print(f"   Model: {pre_fl.model_name}")
            print(f"   Max input length: {pre_fl.MAX_INPUT_LENGTH}")
            print(f"   Language: {pre_fl.language}")
        except Exception as e:
            print(f"❌ {api_type}: Failed to initialize - {e}")
        print()

def test_token_counting():
    """测试 token 计数功能"""
    print("Testing token counting...")
    
    test_text = "Hello, this is a test message for token counting in fault localization."
    
    for api_type in ['deepseek', 'anthropic']:
        try:
            pre_fl = PreFaultLocalization(
                instance_id="test-instance", 
                benchmark_type="swe-bench", 
                api_type=api_type, 
                temperature=0.3
            )
            token_count = pre_fl.count_tokens(test_text)
            print(f"✅ {api_type}: Token count = {token_count}")
        except Exception as e:
            print(f"❌ {api_type}: Token counting failed - {e}")

def test_simple_generation():
    """测试简单的 LLM 生成（需要有效的 API key）"""
    print("Testing simple generation (requires valid API keys)...")
    
    simple_prompt = """Based on the following bug description, predict potential code locations:

Bug: Function returns incorrect result when input is negative.

Please provide a JSON array with potential file paths and methods."""
    
    # 只测试有 API key 的服务
    test_apis = []
    if os.getenv('CLAUDE_API_KEY'):
        test_apis.append('anthropic')
    if os.getenv('DEEPSEEK_API_KEY') or os.getenv('BAILIAN_API_KEY'):
        test_apis.append('deepseek')
    
    for api_type in test_apis:
        try:
            print(f"\nTesting {api_type}...")
            pre_fl = PreFaultLocalization(
                instance_id="test-instance", 
                benchmark_type="swe-bench", 
                api_type=api_type, 
                temperature=0.3
            )
            response = pre_fl.generate(simple_prompt, stream=False)
            if response:
                print(f"✅ {api_type}: Response received")
                print(f"   Response preview: {response[:200]}...")
            else:
                print(f"❌ {api_type}: No response received")
        except Exception as e:
            print(f"❌ {api_type}: Generation failed - {e}")

def test_pre_locate():
    """测试 pre_locate 方法"""
    print("Testing pre_locate method...")
    
    test_description = """## Problem Statement
Function calculate_sum returns incorrect result when one of the inputs is negative.

## Potentially Related Functions from Knowledge Graph
### math_utils.py
- start_line : 15
- end_line : 25
def calculate_sum(a, b):
    return a + b
"""
    
    # 只测试有 API key 的服务
    test_apis = []
    if os.getenv('CLAUDE_API_KEY'):
        test_apis.append('anthropic')
    if os.getenv('DEEPSEEK_API_KEY') or os.getenv('BAILIAN_API_KEY'):
        test_apis.append('deepseek')
    
    for api_type in test_apis:
        try:
            print(f"\nTesting pre_locate with {api_type}...")
            pre_fl = PreFaultLocalization(
                instance_id="test-instance", 
                benchmark_type="swe-bench", 
                api_type=api_type, 
                temperature=0.3
            )
            response = pre_fl.pre_locate(test_description, stream=False)
            if response:
                print(f"✅ {api_type}: Pre-locate response received")
                print(f"   Response preview: {response[:200]}...")
            else:
                print(f"❌ {api_type}: No pre-locate response received")
        except Exception as e:
            print(f"❌ {api_type}: Pre-locate failed - {e}")

if __name__ == "__main__":
    print("=" * 60)
    print("Testing llm_loc_claude.py Multi-API Support")
    print("=" * 60)
    
    test_api_initialization()
    print("\n" + "=" * 60)
    
    test_token_counting()
    print("\n" + "=" * 60)
    
    test_simple_generation()
    print("\n" + "=" * 60)
    
    test_pre_locate()
    print("\n" + "=" * 60)
    print("Testing completed!") 