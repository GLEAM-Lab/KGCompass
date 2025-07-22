#!/usr/bin/env python3
"""
Patch 管理器 - 处理补丁结果的收集、存储和管理
"""

import json
import os
import glob
from datetime import datetime
from pathlib import Path
import argparse


class PatchResult:
    """补丁处理结果数据结构"""
    
    def __init__(self, instance_id):
        self.instance_id = instance_id
        self.timestamp = datetime.now().isoformat()
        self.raw_patch_content = ""
        self.processed_patches = []  # 包含每个文件的diff patch信息
        self.applied_files = []      # 成功应用patch的文件
        self.failed_files = []       # 失败的文件及原因
        self.status = "pending"      # pending, success, partial, failed
        
        # 从instance_id解析org、repo、number
        self.org, self.repo, self.number = self._parse_instance_id(instance_id)
    
    def _parse_instance_id(self, instance_id):
        """从instance_id解析org、repo、number"""
        try:
            # 格式: org__repo-number 例如: google__gson-1787
            if '__' in instance_id and '-' in instance_id:
                org_repo, number = instance_id.rsplit('-', 1)
                org, repo = org_repo.split('__', 1)
                return org, repo, number
            else:
                # 回退处理
                parts = instance_id.replace('__', '_').split('-')
                if len(parts) >= 2:
                    return parts[0], parts[1] if len(parts) > 2 else "", parts[-1]
                else:
                    return "", "", instance_id
        except Exception:
            return "", "", instance_id
    
    def _combine_diff_patches(self):
        """合并所有diff patches为单个patch"""
        if not self.processed_patches:
            return ""
        
        combined_diff = ""
        for patch_info in self.processed_patches:
            diff_content = patch_info.get("diff_content", "")
            if diff_content:
                combined_diff += diff_content + "\n"
        
        return combined_diff.strip()
        
    def to_dict(self):
        """转换为字典格式用于JSON序列化"""
        return {
            "org": self.org,
            "repo": self.repo, 
            "number": self.number,
            "fix_patch": self._combine_diff_patches(),
            "instance_id": self.instance_id,
            "timestamp": self.timestamp,
            "raw_patch_content": self.raw_patch_content,
            "processed_patches": self.processed_patches,
            "applied_files": self.applied_files,
            "failed_files": self.failed_files,
            "status": self.status,
            "stats": {
                "total_files": len(self.processed_patches),
                "applied_count": len(self.applied_files),
                "failed_count": len(self.failed_files)
            }
        }
    
    def to_standard_format(self):
        """转换为标准格式，只包含必要字段"""
        return {
            "org": self.org,
            "repo": self.repo,
            "number": self.number,
            "fix_patch": self._combine_diff_patches()
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建PatchResult实例"""
        # 优先使用instance_id，如果没有则从org/repo/number重构
        instance_id = data.get("instance_id")
        if not instance_id:
            org = data.get("org", "")
            repo = data.get("repo", "")
            number = data.get("number", "")
            instance_id = f"{org}__{repo}-{number}" if org and repo and number else "unknown"
        
        result = cls(instance_id)
        result.timestamp = data.get("timestamp", result.timestamp)
        result.raw_patch_content = data.get("raw_patch_content", "")
        result.processed_patches = data.get("processed_patches", [])
        result.applied_files = data.get("applied_files", [])
        result.failed_files = data.get("failed_files", [])
        result.status = data.get("status", "pending")
        
        # 如果数据中直接包含org/repo/number，使用它们覆盖解析结果
        if "org" in data:
            result.org = data["org"]
        if "repo" in data:
            result.repo = data["repo"]
        if "number" in data:
            result.number = data["number"]
            
        return result


class PatchManager:
    """补丁管理器"""
    
    def __init__(self, output_file="patch_results.jsonl"):
        self.output_file = output_file
        self.results = {}  # instance_id -> PatchResult
        self.load_existing_results()
    
    def load_existing_results(self):
        """加载已存在的结果"""
        if os.path.exists(self.output_file):
            with open(self.output_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line.strip())
                        result = PatchResult.from_dict(data)
                        self.results[result.instance_id] = result
            print(f"📂 加载了 {len(self.results)} 个已存在的结果")
    
    def save_results(self, standard_format=False):
        """保存所有结果到JSONL文件"""
        with open(self.output_file, 'w', encoding='utf-8') as f:
            for result in self.results.values():
                if standard_format:
                    # 只保存标准格式的必要字段
                    data = result.to_standard_format()
                else:
                    # 保存完整信息
                    data = result.to_dict()
                f.write(json.dumps(data, ensure_ascii=False) + '\n')
        format_desc = "标准格式" if standard_format else "完整格式"
        print(f"💾 保存了 {len(self.results)} 个结果到 {self.output_file} ({format_desc})")
    
    def save_standard_format(self, output_file=None):
        """保存标准格式的JSONL文件"""
        if output_file is None:
            output_file = self.output_file.replace('.jsonl', '_standard.jsonl')
        
        success_results = [r for r in self.results.values() if r.status == "success" and r.processed_patches]
        
        with open(output_file, 'w', encoding='utf-8') as f:
            for result in success_results:
                data = result.to_standard_format()
                # 只保存有实际patch内容的结果
                if data["fix_patch"].strip():
                    f.write(json.dumps(data, ensure_ascii=False) + '\n')
        
        print(f"📄 保存了 {len(success_results)} 个标准格式结果到 {output_file}")
    
    def update_result(self, result: PatchResult):
        """更新或添加结果"""
        self.results[result.instance_id] = result
    
    def get_result(self, instance_id):
        """获取指定实例的结果"""
        return self.results.get(instance_id)
    
    def collect_from_patch_dir(self, patch_dir, run_dirs_pattern="tests_java/*_deepseek"):
        """从patch目录收集处理结果"""
        print(f"🔍 开始收集patch结果...")
        
        # 查找所有运行目录
        run_dirs = glob.glob(run_dirs_pattern)
        collected_count = 0
        
        for run_dir in run_dirs:
            instance_id = os.path.basename(run_dir).replace('_deepseek', '')
            
            # 检查是否已经处理过
            if instance_id in self.results:
                continue
            
            result = PatchResult(instance_id)
            
            # 1. 读取原始patch内容
            raw_patch_file = os.path.join(run_dir, "patches", f"{instance_id}.patch")
            if os.path.exists(raw_patch_file):
                with open(raw_patch_file, 'r', encoding='utf-8') as f:
                    result.raw_patch_content = f.read()
            
            # 2. 收集处理后的diff patches
            diff_patches_dir = os.path.join(run_dir, "patches", "diff_patches")
            if os.path.exists(diff_patches_dir):
                for diff_file in glob.glob(os.path.join(diff_patches_dir, f"{instance_id}_*.diff")):
                    file_name = os.path.basename(diff_file)
                    # 提取原始文件路径
                    original_file = file_name.replace(f"{instance_id}_", "").replace("_", "/").replace(".diff", "")
                    
                    with open(diff_file, 'r', encoding='utf-8') as f:
                        diff_content = f.read()
                    
                    patch_info = {
                        "file_path": original_file,
                        "diff_file": diff_file,
                        "diff_content": diff_content,
                        "size": len(diff_content)
                    }
                    result.processed_patches.append(patch_info)
            
            # 3. 检查应用状态（这里简化处理，实际可以通过git状态检查）
            if result.processed_patches:
                result.applied_files = [p["file_path"] for p in result.processed_patches]
                result.status = "success" if result.applied_files else "failed"
            else:
                result.status = "failed"
                result.failed_files = ["No diff patches generated"]
            
            self.update_result(result)
            collected_count += 1
            print(f"✅ 收集实例: {instance_id} ({len(result.processed_patches)} 个patch)")
        
        print(f"📊 总共收集了 {collected_count} 个新结果")
        return collected_count
    
    def process_existing_patches(self, tests_dir="tests_java"):
        """处理已存在但未记录的patch"""
        print(f"🔄 开始处理已存在的patch...")
        
        # 查找所有运行目录
        run_dirs = glob.glob(os.path.join(tests_dir, "*_deepseek"))
        processed_count = 0
        
        for run_dir in run_dirs:
            instance_id = os.path.basename(run_dir).replace('_deepseek', '')
            
            # 检查patch文件是否存在
            patch_file = os.path.join(run_dir, "patches", f"{instance_id}.patch")
            if not os.path.exists(patch_file):
                continue
            
            # 检查是否已经有完整记录
            existing_result = self.get_result(instance_id)
            if existing_result and existing_result.processed_patches:
                continue
            
            print(f"🔧 处理实例: {instance_id}")
            
            # 创建或更新结果
            if existing_result:
                result = existing_result
            else:
                result = PatchResult(instance_id)
            
            # 读取原始patch
            with open(patch_file, 'r', encoding='utf-8') as f:
                result.raw_patch_content = f.read()
            
            # 收集diff patches
            diff_patches_dir = os.path.join(run_dir, "patches", "diff_patches")
            result.processed_patches = []
            
            if os.path.exists(diff_patches_dir):
                for diff_file in glob.glob(os.path.join(diff_patches_dir, f"{instance_id}_*.diff")):
                    file_name = os.path.basename(diff_file)
                    original_file = file_name.replace(f"{instance_id}_", "").replace("_", "/").replace(".diff", "")
                    
                    with open(diff_file, 'r', encoding='utf-8') as f:
                        diff_content = f.read()
                    
                    patch_info = {
                        "file_path": original_file,
                        "diff_file": os.path.abspath(diff_file),
                        "diff_content": diff_content,
                        "size": len(diff_content)
                    }
                    result.processed_patches.append(patch_info)
            
            # 更新状态
            if result.processed_patches:
                result.applied_files = [p["file_path"] for p in result.processed_patches]
                result.status = "success"
            else:
                result.status = "failed"
                result.failed_files = ["No diff patches found"]
            
            self.update_result(result)
            processed_count += 1
        
        print(f"📊 处理了 {processed_count} 个已存在的patch")
        return processed_count
    
    def get_summary_stats(self):
        """获取统计摘要"""
        total = len(self.results)
        success = sum(1 for r in self.results.values() if r.status == "success")
        failed = sum(1 for r in self.results.values() if r.status == "failed")
        partial = sum(1 for r in self.results.values() if r.status == "partial")
        
        total_files = sum(len(r.processed_patches) for r in self.results.values())
        total_applied = sum(len(r.applied_files) for r in self.results.values())
        
        return {
            "total_instances": total,
            "success_instances": success,
            "failed_instances": failed,
            "partial_instances": partial,
            "success_rate": f"{success/total*100:.1f}%" if total > 0 else "0%",
            "total_files_patched": total_files,
            "total_applied_patches": total_applied
        }
    
    def print_summary(self):
        """打印统计摘要"""
        stats = self.get_summary_stats()
        print("\n" + "="*50)
        print("📊 Patch 处理摘要")
        print("="*50)
        print(f"总实例数: {stats['total_instances']}")
        print(f"成功实例: {stats['success_instances']} ({stats['success_rate']})")
        print(f"失败实例: {stats['failed_instances']}")
        print(f"部分成功: {stats['partial_instances']}")
        print(f"总文件补丁: {stats['total_files_patched']}")
        print(f"成功应用: {stats['total_applied_patches']}")
        print("="*50)


def main():
    parser = argparse.ArgumentParser(description="Patch管理器 - 收集和管理补丁处理结果")
    parser.add_argument("--output", default="patch_results.jsonl", help="输出JSONL文件路径")
    parser.add_argument("--collect", action="store_true", help="收集新的patch结果")
    parser.add_argument("--process-existing", action="store_true", help="处理已存在的patch")
    parser.add_argument("--tests-dir", default="tests_java", help="测试目录路径")
    parser.add_argument("--summary", action="store_true", help="显示统计摘要")
    parser.add_argument("--standard-format", action="store_true", help="保存标准格式JSONL (org/repo/number/fix_patch)")
    parser.add_argument("--standard-only", action="store_true", help="只保存标准格式JSONL文件")
    
    args = parser.parse_args()
    
    manager = PatchManager(args.output)
    
    if args.collect:
        manager.collect_from_patch_dir("patches")
    
    if args.process_existing:
        manager.process_existing_patches(args.tests_dir)
    
    if args.collect or args.process_existing:
        if args.standard_only:
            # 只保存标准格式
            manager.save_results(standard_format=True)
        else:
            # 保存完整格式
            manager.save_results(standard_format=False)
            
        # 如果指定了标准格式，额外生成标准格式文件
        if args.standard_format:
            manager.save_standard_format()
    
    if args.summary or not (args.collect or args.process_existing):
        manager.print_summary()


if __name__ == "__main__":
    main() 