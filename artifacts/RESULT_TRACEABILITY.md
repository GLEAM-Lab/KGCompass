# Result Traceability

This note maps every retained result ledger to either the MURAL main manuscript
or its separately compiled supplementary material. Files for unreported
diagnostics, obsolete ablations, partial shards, and the retired KG-only
downstream repair study are intentionally absent.

Frozen ledgers retain historical `KGCompass` labels. In the submitted
documents, `KGCompass` is `KG-local`, `BM25+KG RRF file-local` is standalone
MURAL, and `GLM-5 + BM25+KG RRF file-local` is GLM-5+MURAL. This mapping changes
terminology only; candidate rankings and metric values are unchanged.

## Evaluation Scope

- Benchmark: all 500 SWE-bench Verified instances.
- Structural source:
  `runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6/`.
- KG-local rank union:
  `runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1/`.
- Shared input boundary: original issue title/body plus base-commit code.
- Excluded inputs: benchmark hints, issue/PR comments, evidence from the pull
  request associated with the target repair, patch text, linked repair commits,
  and future artifacts.
- Evaluator-only data: official patches and all derived target mappings.

The final leakage audit is copied to
`artifacts/results/kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json`.
It reports 500/500 valid instances, zero target-PR hits, zero trace hits from
future repair artifacts, and no content, structural, or metadata violations.

## Submission-Side Verification

Run:

```bash
python3 artifacts/scripts/verify_paper_results.py
```

The verifier checks:

- the exact result-file inventory;
- the target-mapping table;
- RQ-1 controlled source, selector, fusion, and paired statistics;
- RQ-2 fixed-prefix controls and paired statistics;
- RQ-3 mapped edit-target coverage;
- supplementary budget-sensitivity values; and
- leakage and external-artifact sensitivity statements.

## Main-Manuscript Mapping

### Experimental Setup

- Ground-truth mapping:
  `artifacts/results/tse_gt_mapping_v6.tsv`.
- Input-boundary record:
  `artifacts/issue_comment_boundary.json`.

### RQ-1: Controlled Context Windows

- BM25, BLUiR, CodeGraph, graph-only KG, and KG-local:
  `artifacts/results/path_mining_file_expansion_ablation_20260531.tsv`.
- Matched BM25/KG file-local and MURAL rows:
  `artifacts/results/retrieve_then_localize_top20_20260711.tsv`.
- Bootstrap intervals, win/loss counts, and exact tests:
  `artifacts/results/retrieve_then_localize_paired_20260711.tsv`.
- Per-instance Hit@20 disagreements:
  `artifacts/results/retrieve_then_localize_disagreements_20260711.tsv`.
- First-stage Top-20 file coverage:
  `artifacts/results/ranked_file_source_coverage_20260711.tsv` and
  `artifacts/results/ranked_file_source_paired_20260711.tsv`.

### RQ-2: Fixed-Prefix LLM Fusion

- GLM-5 issue-only, KG-local, BM25-local, and MURAL rows:
  `artifacts/results/retrieve_then_localize_top20_20260711.tsv`.
- CodeGraph fixed-prefix control:
  `artifacts/results/glm5_baseline_fusion_controls_top10_20260614.tsv`.
- Paired source and fusion statistics:
  `artifacts/results/retrieve_then_localize_paired_20260711.tsv`.

### RQ-3: Complete Edit-Target Coverage

- Aggregate edit-target recall and complete coverage:
  `artifacts/results/patch_derived_context_summary_20260702.tsv` and `.json`.
- Deterministic mapped targets:
  `artifacts/results/patch_derived_context_targets_20260702.json`.

### Threats to Validity

- Leakage-sentinel audit:
  `artifacts/results/kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json`.
- External-artifact sensitivity:
  `artifacts/results/time_boundary_external_artifact_sensitivity_20260531.tsv`.

## Supplementary-Material Mapping

### Budget Sensitivity

- Four-budget aggregate rows:
  `artifacts/results/retrieve_then_localize_budget_curve_20260711.tsv`.
- Four-budget paired statistics:
  `artifacts/results/retrieve_then_localize_budget_paired_20260711.tsv`.

### Reproduction Settings

- Exact localization prompt:
  `artifacts/prompts/llm_fault_location_prompt.md`.

## Reproduction Commands

The commands below target the full experiment workspace, where benchmark
checkouts, cached mappings, and per-instance run directories are available.
Scripts mirrored under `artifacts/scripts/` are source-inspection snapshots.

### Leakage Audit

```bash
python3 artifacts/scripts/audit_kg_leakage.py \
  runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --output-json logs/kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json \
  --fail-on-issue
```

### Controlled Source Rows

```bash
python3 artifacts/scripts/eval_controls_v3.py \
  --group full_pathmined=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1 \
  --group strict_kg_ablation=runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --group bm25_nohint=runs/text_baselines_nohints/2000 \
  --group bluir=runs/text_baselines_bluir/2300 \
  --group no_history_codegraph=runs/codegraph_anchor/tse_timesafe_main_20260531_v2 \
  --output-tsv logs/comparison_current/path_mining_file_expansion_ablation_20260531.tsv \
  --top-k 20
```

### BM25 File-Local Selection and MURAL

```bash
BM25_METHODS=runs/text_baselines_nohints/2000
BM25_SEEDS=temp_run/bm25_top20_file_seeds
BM25_FILELOCAL=temp_run/bm25_filelocal
KG_FILELOCAL=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1
RRF_FILELOCAL=temp_run/bm25_kg_rrf_filelocal

python3 artifacts/scripts/export_ranked_file_seeds.py \
  --input-dir "$BM25_METHODS" \
  --output-dir "$BM25_SEEDS" \
  --ids-file temp_run/SWE-bench_Verified_ids.jsonl \
  --max-files 20 \
  --support-mode count

python3 artifacts/scripts/export_path_mined_filelocal.py \
  --input-dir "$BM25_SEEDS" \
  --output-dir "$BM25_FILELOCAL" \
  --ids-file temp_run/SWE-bench_Verified_ids.jsonl \
  --limit 50

python3 artifacts/scripts/export_equal_rrf_fusion.py \
  --primary-dir "$BM25_FILELOCAL" \
  --secondary-dir "$KG_FILELOCAL" \
  --output-dir "$RRF_FILELOCAL" \
  --top-k 50 \
  --rrf-k 60 \
  --force
```

### Fixed-Prefix Top-20 Controls

```bash
python3 artifacts/scripts/export_fixed_prefix_fusion.py \
  --primary-dir temp_run/eval_aliyun_glm5_issueonly \
  --secondary-dir "$BM25_FILELOCAL" \
  --output-dir temp_run/glm5_bm25_filelocal_b20 \
  --budget 20 \
  --primary-prefix 10 \
  --secondary-pool 20 \
  --force

python3 artifacts/scripts/export_fixed_prefix_fusion.py \
  --primary-dir temp_run/eval_aliyun_glm5_issueonly \
  --secondary-dir "$RRF_FILELOCAL" \
  --output-dir temp_run/glm5_bm25_kg_rrf_b20 \
  --budget 20 \
  --primary-prefix 10 \
  --secondary-pool 20 \
  --force

python3 artifacts/scripts/analyze_retrieve_localize_controls.py \
  --ids-file temp_run/SWE-bench_Verified_ids.jsonl \
  --gt-cache temp_run/output/gt_eval_cache_verified_v3_entities.json \
  --top-k 20 \
  --group KG_filelocal="$KG_FILELOCAL" \
  --group BM25_filelocal="$BM25_FILELOCAL" \
  --group BM25_KG_RRF_filelocal="$RRF_FILELOCAL" \
  --group GLM5_issue=temp_run/eval_aliyun_glm5_issueonly \
  --group GLM5_KG_filelocal=temp_run/fusions_glm5_baseline_controls_20260614_head10/GLM5_KGCompass_ht10 \
  --group GLM5_BM25_filelocal=temp_run/glm5_bm25_filelocal_b20 \
  --group GLM5_BM25_KG_RRF_filelocal=temp_run/glm5_bm25_kg_rrf_b20 \
  --compare KG_filelocal=BM25_filelocal \
  --compare BM25_filelocal=BM25_KG_RRF_filelocal \
  --compare GLM5_issue=GLM5_BM25_filelocal \
  --compare GLM5_issue=GLM5_BM25_KG_RRF_filelocal \
  --compare GLM5_KG_filelocal=GLM5_BM25_filelocal \
  --compare GLM5_BM25_filelocal=GLM5_BM25_KG_RRF_filelocal \
  --output-summary logs/comparison_current/retrieve_then_localize_top20_20260711.tsv \
  --output-paired logs/comparison_current/retrieve_then_localize_paired_20260711.tsv \
  --output-disagreements logs/comparison_current/retrieve_then_localize_disagreements_20260711.tsv
```

### Patch-Derived Coverage

```bash
python3 artifacts/scripts/evaluate_patch_derived_context.py \
  --ids-file temp_run/SWE-bench_Verified_ids.jsonl \
  --gt-cache temp_run/output/gt_eval_cache_verified_v3_entities.json \
  --target-cache artifacts/results/patch_derived_context_targets_20260702.json \
  --output-tsv logs/comparison_current/patch_derived_context_summary_20260702.tsv \
  --output-json logs/comparison_current/patch_derived_context_summary_20260702.json \
  --row "BM25 files + file-local=bm25_filelocal=temp_run/private_bm25_filelocal_20260704/bm25_top20_files_filelocal" \
  --row "BM25+KG RRF file-local=bm25_kg_rrf_filelocal=temp_run/private_bm25_filelocal_20260704/hybrid_rrf/BM25_KG_deterministic_rrf" \
  --row "GLM-5 + BM25 files + file-local=glm5_bm25_filelocal=temp_run/private_bm25_filelocal_20260704/budget_fusions/GLM5_BM25FileLocal_b20_p10" \
  --row "GLM-5 + BM25+KG RRF file-local=glm5_bm25_kg_rrf_filelocal=temp_run/private_bm25_filelocal_20260704/hybrid_rrf/deterministic_budget_fusions/GLM5_Hybrid_b20_p10" \
  --top-k 20
```

The exact GLM-5 endpoint identifier, evaluation snapshot, and frozen
localization prompt are reported in the supplementary material and under
`artifacts/prompts/`.
