#!/usr/bin/env python3
"""
生成只在 SWE-bench Verified 中出现但不在 SWE-bench Lite 中出现的实例列表
"""

import json
from datasets import load_dataset

OUTPUT_PATH = "SWE-bench_Verified_only_ids.jsonl"

def main():
    print("📦 Loading SWE-bench datasets from HuggingFace...")
    
    # 加载两个数据集
    print("Loading SWE-bench Verified...")
    verified_ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    
    print("Loading SWE-bench Lite...")
    lite_ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    
    # 提取 instance_id
    verified_ids = {sample["instance_id"] for sample in verified_ds}
    lite_ids = {sample["instance_id"] for sample in lite_ds}
    
    print(f"SWE-bench Verified: {len(verified_ids)} instances")
    print(f"SWE-bench Lite: {len(lite_ids)} instances")
    
    # 计算差集：只在 Verified 中出现、但不在 Lite 中出现的列表
    only_verified_ids = sorted(verified_ids - lite_ids)
    
    print(f"Only in Verified (not in Lite): {len(only_verified_ids)} instances")
    
    # 保存为 JSONL 格式
    with open(OUTPUT_PATH, "w") as f:
        for instance_id in only_verified_ids:
            f.write(json.dumps({"instance_id": instance_id}, ensure_ascii=False) + "\n")
    
    print(f"✅ Written {len(only_verified_ids)} instances to {OUTPUT_PATH}")
    
    # 显示前10个示例
    print(f"\n前10个示例:")
    for i, instance_id in enumerate(only_verified_ids[:10]):
        print(f"  {i+1}. {instance_id}")
    
    if len(only_verified_ids) > 10:
        print(f"  ... 还有 {len(only_verified_ids) - 10} 个实例")

if __name__ == "__main__":
    main() 