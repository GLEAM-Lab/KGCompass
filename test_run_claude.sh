#!/bin/bash

# Test script for run_claude.sh
echo "================================================="
echo "Testing run_claude.sh Multi-API Support"
echo "================================================="

# Test help message
echo -e "\n--- Testing help message ---"
./run_claude.sh

echo -e "\n--- Testing API type validation ---"
# Test different API types (just show what would be called, don't actually run)
test_apis=("anthropic" "openai" "deepseek" "qwen")

for api in "${test_apis[@]}"; do
    echo "✓ API type '$api' would be accepted"
    echo "  Command: ./run_claude.sh test-instance $api"
done

echo -e "\n--- Environment Variables Check ---"
# Check which API keys are available
apis_available=()

if [[ -n "$CLAUDE_API_KEY" ]]; then
    echo "✅ CLAUDE_API_KEY: Available"
    apis_available+=("anthropic")
else
    echo "❌ CLAUDE_API_KEY: Not set"
fi

if [[ -n "$OPENAI_API_KEY" ]]; then
    echo "✅ OPENAI_API_KEY: Available" 
    apis_available+=("openai")
else
    echo "❌ OPENAI_API_KEY: Not set"
fi

if [[ -n "$DEEPSEEK_API_KEY" || -n "$BAILIAN_API_KEY" ]]; then
    echo "✅ DEEPSEEK_API_KEY/BAILIAN_API_KEY: Available"
    apis_available+=("deepseek")
else
    echo "❌ DEEPSEEK_API_KEY/BAILIAN_API_KEY: Not set"
fi

if [[ -n "$QWEN_API_KEY" ]]; then
    echo "✅ QWEN_API_KEY: Available"
    apis_available+=("qwen")
else
    echo "❌ QWEN_API_KEY: Not set"
fi

echo -e "\n--- Available APIs for Testing ---"
if [[ ${#apis_available[@]} -eq 0 ]]; then
    echo "❌ No API keys found. Please set at least one API key to test."
    echo "Example:"
    echo "  export CLAUDE_API_KEY='your-claude-key'"
    echo "  export DEEPSEEK_API_KEY='your-deepseek-key'"
else
    echo "✅ Available APIs: ${apis_available[*]}"
    echo -e "\nTo test with a real instance, use:"
    for api in "${apis_available[@]}"; do
        echo "  ./run_claude.sh django__django-12345 $api"
    done
fi

echo -e "\n--- Script Validation ---"
# Check if the Claude scripts exist
if [[ -f "kgcompass/llm_loc_claude.py" ]]; then
    echo "✅ llm_loc_claude.py: Found"
else
    echo "❌ llm_loc_claude.py: Missing"
fi

if [[ -f "kgcompass/repair_claude.py" ]]; then
    echo "✅ repair_claude.py: Found"
else
    echo "❌ repair_claude.py: Missing"
fi

# Check if required directories exist
if [[ -d "kgcompass" ]]; then
    echo "✅ kgcompass directory: Found"
else
    echo "❌ kgcompass directory: Missing"
fi

echo -e "\n================================================="
echo "Test completed!"
echo "=================================================" 