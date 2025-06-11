from dotenv import load_dotenv
import os
import neo4j

load_dotenv()

# GitHub Configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Bailian
BAILIAN_API_KEY = os.getenv("BAILIAN_API_KEY")

# Neo4j - Use environment variable if available, otherwise default to localhost
# This makes the application compatible with both Docker and local execution
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4jpassword")

# Knowledge Graph Configuration
MAX_CANDIDATE_METHODS = 500
MAX_SEARCH_DEPTH = 2

# Dataset Configuration
DATASET_NAME = "princeton-nlp/SWE-bench_Lite"

# Graph Configuration
DECAY_FACTOR = 0.6
VECTOR_SIMILARITY_WEIGHT = 0.3

# Model Configuration
LLM_MODELS = {
    'openai': 'gpt-4',
    'deepseek': 'deepseek-v3',
    'deepseek-r1': 'deepseek-ai/DeepSeek-R1',
    'qwen': 'qwen-max-2025-01-25',
}

# API Configuration
DEEPSEEK_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEEPSEEK_API_KEY = os.getenv("BAILIAN_API_KEY")
QWEN_API_KEY = os.getenv("BAILIAN_API_KEY")
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# LLM Request Configuration
MAX_TOKENS = 4096
DIVERSE_TEMPERATURE = 0.8
TOP_P = 0.95

MAX_INPUT_LENGTH = {
    'openai': 128000,
    'deepseek': 65536 / 3,
    'qwen': 65536 / 3,
    'bailian': 32000,
}
LLM_LOC_MAX = 5

MODEL_MAP = {
    'deepseek': 'deepseek-coder',
    'qwen': 'qwen-turbo',
    'yi': 'yi-large',
}

NEO4J_CONFIG = {
    "uri": NEO4J_URI,
    "user": NEO4J_USER,
    "password": NEO4J_PASSWORD,
}
