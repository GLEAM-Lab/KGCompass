"""
Benchmark 配置和处理逻辑模块
支持不同类型的 benchmark 数据集
"""

import os
from enum import Enum
from typing import Dict, Any, Optional
from datasets import load_dataset


class BenchmarkType(Enum):
    """支持的 Benchmark 类型"""
    SWE_BENCH = "swe-bench"           # 原始 SWE-bench (Python 项目)
    MULTI_SWE_BENCH = "multi-swe-bench"  # Multi-SWE-bench (Java 项目)


class BenchmarkConfig:
    """Benchmark 配置类"""
    
    # 不同 benchmark 的仓库URL映射
    REPO_URL_MAPS = {
        BenchmarkType.SWE_BENCH: {
            # Python 项目仓库
            "astropy__astropy": "https://github.com/astropy/astropy.git",
            "django__django": "https://github.com/django/django.git",
            "matplotlib__matplotlib": "https://github.com/matplotlib/matplotlib.git",
            "scikit-learn__scikit-learn": "https://github.com/scikit-learn/scikit-learn.git",
            "scipy__scipy": "https://github.com/scipy/scipy.git",
            "sympy__sympy": "https://github.com/sympy/sympy.git",
            "pytest-dev__pytest": "https://github.com/pytest-dev/pytest.git",
            "psf__requests": "https://github.com/psf/requests.git",
            "pallets__flask": "https://github.com/pallets/flask.git",
        },
        
        BenchmarkType.MULTI_SWE_BENCH: {
            # Java 项目仓库
            "google__gson": "https://github.com/google/gson.git",
            "fasterxml__jackson-databind": "https://github.com/FasterXML/jackson-databind.git",
            "fasterxml__jackson-core": "https://github.com/FasterXML/jackson-core.git",
            "fasterxml__jackson-dataformat-xml": "https://github.com/FasterXML/jackson-dataformat-xml.git",
            "mockito__mockito": "https://github.com/mockito/mockito.git",
            "apache__dubbo": "https://github.com/apache/dubbo.git",
            "elastic__logstash": "https://github.com/elastic/logstash.git",
            "alibaba__fastjson2": "https://github.com/alibaba/fastjson2.git",
            "googlecontainertools__jib": "https://github.com/GoogleContainerTools/jib.git",
        }
    }
    
    # 不同 benchmark 的数据集配置
    DATASET_CONFIGS = {
        BenchmarkType.SWE_BENCH: {
            "dataset_name": "princeton-nlp/SWE-bench_Verified",
            "split": "test",
            "local_file": "SWE-bench_Verified.jsonl"
        },
        
        BenchmarkType.MULTI_SWE_BENCH: {
            "dataset_name": None,  # 使用本地文件
            "split": None,
            "local_file": "swe-bench_java"  # 目录包含多个 JSONL 文件
        }
    }
    
    # 不同 benchmark 的文件扩展名和语言
    LANGUAGE_CONFIGS = {
        BenchmarkType.SWE_BENCH: {
            "language": "python",
            "file_extensions": [".py"],
            "test_files": ["test_*.py", "*_test.py", "tests.py"]
        },
        
        BenchmarkType.MULTI_SWE_BENCH: {
            "language": "java", 
            "file_extensions": [".java"],
            "test_files": ["*Test.java", "*Tests.java", "Test*.java"]
        }
    }


class BenchmarkManager:
    """Benchmark 管理器"""
    
    def __init__(self, benchmark_type: str):
        """
        初始化 Benchmark 管理器
        
        Args:
            benchmark_type: benchmark 类型字符串
        """
        self.benchmark_type = self._parse_benchmark_type(benchmark_type)
        self.config = BenchmarkConfig()
    
    def _parse_benchmark_type(self, benchmark_type: str) -> BenchmarkType:
        """解析 benchmark 类型字符串"""
        benchmark_type = benchmark_type.lower().replace("_", "-")
        
        for bt in BenchmarkType:
            if bt.value == benchmark_type:
                return bt
        
        raise ValueError(f"不支持的 benchmark 类型: {benchmark_type}")
    
    def get_repo_url(self, repo_identifier: str) -> Optional[str]:
        """获取仓库URL"""
        repo_map = self.config.REPO_URL_MAPS.get(self.benchmark_type, {})
        return repo_map.get(repo_identifier)
    
    def get_supported_repos(self) -> list:
        """获取支持的仓库列表"""
        repo_map = self.config.REPO_URL_MAPS.get(self.benchmark_type, {})
        return list(repo_map.keys())
    
    def get_language_config(self) -> Dict[str, Any]:
        """获取语言配置"""
        return self.config.LANGUAGE_CONFIGS.get(self.benchmark_type, {})
    
    def get_dataset_config(self) -> Dict[str, Any]:
        """获取数据集配置"""
        return self.config.DATASET_CONFIGS.get(self.benchmark_type, {})
    
    def load_dataset_instances(self) -> list:
        """加载数据集实例"""
        dataset_config = self.get_dataset_config()
        
        if self.benchmark_type == BenchmarkType.SWE_BENCH:
            return self._load_swe_bench_instances(dataset_config)
        elif self.benchmark_type == BenchmarkType.MULTI_SWE_BENCH:
            return self._load_multi_swe_bench_instances(dataset_config)
        else:
            raise ValueError(f"不支持的 benchmark 类型: {self.benchmark_type}")
    
    def _load_swe_bench_instances(self, config: Dict[str, Any]) -> list:
        """加载 SWE-bench 实例"""
        instances = []
        
        # 优先使用本地文件
        local_file = config.get("local_file")
        if local_file and os.path.exists(local_file):
            import json
            with open(local_file, 'r') as f:
                for line in f:
                    data = json.loads(line.strip())
                    instances.append(data)
        else:
            # 从 HuggingFace 加载
            dataset_name = config.get("dataset_name")
            split = config.get("split", "test")
            if dataset_name:
                dataset = load_dataset(dataset_name, split=split)
                instances = list(dataset)
        
        return instances
    
    def _load_multi_swe_bench_instances(self, config: Dict[str, Any]) -> list:
        """加载 Multi-SWE-bench (Java) 实例"""
        instances = []
        local_dir = config.get("local_file")
        
        if local_dir and os.path.exists(local_dir):
            import json
            import glob
            
            # 遍历所有 JSONL 文件
            for jsonl_file in glob.glob(os.path.join(local_dir, "*.jsonl")):
                with open(jsonl_file, 'r') as f:
                    for line in f:
                        data = json.loads(line.strip())
                        instances.append(data)
        
        return instances
    
    def extract_repo_identifier(self, instance_id: str) -> str:
        """从实例ID中提取仓库标识符"""
        if self.benchmark_type == BenchmarkType.SWE_BENCH:
            # SWE-bench 格式: repo__name-issue_id
            return instance_id.rsplit('-', 1)[0]
        elif self.benchmark_type == BenchmarkType.MULTI_SWE_BENCH:
            # Multi-SWE-bench 格式: repo__name-issue_id  
            return instance_id.rsplit('-', 1)[0]
        else:
            return instance_id.rsplit('-', 1)[0]
    
    def get_playground_subdir(self) -> str:
        """获取 playground 子目录名称"""
        return "playground"
    
    def get_results_subdir(self) -> str:
        """获取结果子目录名称"""
        if self.benchmark_type == BenchmarkType.MULTI_SWE_BENCH:
            return "tests_java"
        else:
            return "tests"
    
    def get_kg_results_subdir(self) -> str:
        """获取KG结果子目录名称"""
        if self.benchmark_type == BenchmarkType.MULTI_SWE_BENCH:
            return "java_kg_results"
        else:
            return "kg_results"


def create_benchmark_manager(benchmark_type: str) -> BenchmarkManager:
    """创建 benchmark 管理器的工厂函数"""
    return BenchmarkManager(benchmark_type)


def get_supported_benchmarks() -> list:
    """获取支持的 benchmark 类型列表"""
    return [bt.value for bt in BenchmarkType] 