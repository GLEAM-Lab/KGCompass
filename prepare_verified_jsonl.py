import json
from datasets import load_dataset

OUTPUT_PATH = "SWE-bench_Verified_ids.jsonl"

print("📦 Loading SWE-bench_Verified from HuggingFace…")
ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")

with open(OUTPUT_PATH, "w") as f:
    for sample in ds:
        f.write(json.dumps({"instance_id": sample["instance_id"]}, ensure_ascii=False) + "\n")

print(f"✅ Written {len(ds)} lines to {OUTPUT_PATH}")
print("将该文件拷贝/挂载到容器后，可用 mine_kg_bulk.py 处理。") 