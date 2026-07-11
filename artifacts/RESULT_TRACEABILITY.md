# Result Traceability

This note maps the current MURAL manuscript claims to the committed
paper-side ledgers. It intentionally excludes older diagnostics and unreported
ablations so reviewers do not have to reconcile artifact-only results with the
paper text.

The implementation workspace and frozen ledgers retain historical `KGCompass`
labels. In the current manuscript, those rows are the `KG-local` source controls. Standalone
`BM25+KG RRF file-local` is MURAL, and `GLM-5 + BM25+KG RRF file-local` is the
GLM-5+MURAL fixed-prefix configuration. The mapping changes terminology only;
all recorded candidates and metric values are unchanged.

## Evaluation Scope

- Benchmark: all 500 SWE-bench Verified instances.
- KG-only time-safe artifact:
  `runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6/`.
- Main path-mined selector:
  `runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1/`.
- Shared input boundary: original issue title/body plus base-commit repository
  code.
- Excluded inputs: benchmark hints, issue/PR comments, target fixing pull
  request evidence, pull-request patch diffs, linked commits, and future fixing
  artifacts.

The final leakage audit is copied to
`artifacts/results/kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json`.
It reports 500/500 valid instances, zero target-PR hits, zero future-fix trace
hits, and no content, structural, or metadata failures.

## Paper-Side Verification

Run:

```bash
python3 artifacts/scripts/verify_paper_results.py
```

The verifier checks the paper-facing values for:

- the ground-truth mapping table;
- RQ1 controlled Top-20 context-window rows;
- RQ1/RQ2 source-swapped and equal-weight RRF file-local controls, paired
  tests, and budget curves;
- RQ2 LLM+KG-local, GLM-5 tail-control, released-localizer, and local
  open-model rows;
- GLM-5/KG-local overlap and paired statistics;
- RQ3 file-local path-mining mechanism counts;
- RQ3 patch-derived repair-context coverage;
- RQ4 full-500 ClaudeCode repair outcomes; and
- leakage and external-artifact sensitivity statements.

## Manuscript Mapping

- Ground-truth mapping:
  `artifacts/results/tse_gt_mapping_v6.tsv`.
- RQ1 controlled context windows:
  `artifacts/results/path_mining_file_expansion_ablation_20260531.tsv`.
  This file is trimmed to the manuscript rows: BM25, BLUiR, CodeGraph,
  graph-only KG and KG rank union (historical `KGCompass` labels).
- RQ1/RQ3 paired full-vs-without-file-local accounting:
  `artifacts/results/rq1_pathmined_paired_stats_20260531.tsv`.
- RQ2 LLM issue-only and LLM+KG-local rows:
  `artifacts/results/llm_pathmined_kg_ht10_20260531.tsv`.
- RQ2 GLM-5 fixed-prefix tail controls:
  `artifacts/results/glm5_baseline_fusion_controls_top10_20260614.tsv`.
- Source-swapped and equal-weight RRF retrieve-then-localize controls:
  `artifacts/results/retrieve_then_localize_top20_20260711.tsv`,
  `artifacts/results/retrieve_then_localize_paired_20260711.tsv`,
  `artifacts/results/retrieve_then_localize_disagreements_20260711.tsv`,
  `artifacts/results/retrieve_then_localize_budget_curve_20260711.tsv`, and
  `artifacts/results/retrieve_then_localize_budget_paired_20260711.tsv`.
- First-stage ranked-file coverage:
  `artifacts/results/ranked_file_source_coverage_20260711.tsv` and
  `artifacts/results/ranked_file_source_paired_20260711.tsv`.
- RQ2 released Qwen2.5-32B localizer rows:
  `artifacts/results/external_verified_loc_baselines_cosil_release_20260601.tsv`.
- RQ2 CoSIL-Qwen2.5-32B+KG-local row:
  `artifacts/results/qwen25_32b_kgcompass_fusion_20260601.tsv`.
- RQ2 local open-model Top-10 stress rows:
  `artifacts/results/local_open_models_pathmined_top10_5p5_summary.tsv`.
- RQ2 GLM-5/KG-local overlap and 58-win evidence accounting:
  `artifacts/results/glm5_pathmined_kg_complementarity_20260531.json`,
  `artifacts/results/glm5_pathmined_kg_complementarity_20260531.tsv`,
  `artifacts/results/glm5_pathmined_rescued_instances_20260531.tsv`, and
  `artifacts/results/tse_paired_stats_pathmined_20260531.tsv`.
- RQ3 KG-only path and rank summaries:
  `artifacts/results/kg_clean_tse_timesafe_main_20260529_v6_rq3.json` and
  `artifacts/results/kg_clean_tse_timesafe_main_20260529_v6_rq3.tsv`.
- RQ3 file-local path-mining aggregate:
  `artifacts/results/rq3_file_local_path_mining_summary.tsv`.
- RQ3 patch-derived repair-context coverage:
  `artifacts/results/patch_derived_context_summary_20260702.tsv`,
  `artifacts/results/patch_derived_context_summary_20260702.json`, and
  `artifacts/results/patch_derived_context_targets_20260702.json`.
- Threats-to-validity external-artifact sensitivity:
  `artifacts/results/time_boundary_external_artifact_sensitivity_20260531.tsv`.
- RQ4 full-500 ClaudeCode repair check:
  `artifacts/results/claudecode_context_probe_glm5_20260531.tsv`,
  the `full500_*` official result ledgers and summary JSON files under
  `artifacts/results/claudecode_context_probe_glm5_20260531/`,
  `paired_stats.json`, and `rq4_case_sphinx_10673.json`.

## Reproduction Commands

The commands below are intended for the full experiment workspace, where
historical package paths retain the original KGCompass name and SWE-bench
Verified caches, base-commit repositories, and per-instance run directories
are available. The mirrored scripts under `artifacts/scripts/` are
source-inspection snapshots.

Final leakage audit:

```bash
python3 scripts/audit_kg_leakage.py \
  runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --output-json logs/kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json \
  --fail-on-issue
```

Path-mined KG-source export and RQ1/RQ3 context-window ledgers:

```bash
PATH_MINED_INTERMEDIATE=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_filelocal_intermediate

python3 scripts/export_path_mined_filelocal.py \
  --input-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --output-dir "$PATH_MINED_INTERMEDIATE" \
  --limit 50

python3 scripts/fuse_path_mined_with_kg.py \
  --kg-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --path-mined-dir "$PATH_MINED_INTERMEDIATE" \
  --output-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1 \
  --limit 50

python3 scripts/eval_controls_v3.py \
  --group full_pathmined=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1 \
  --group strict_kg_ablation=runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --group bm25_nohint=runs/text_baselines_nohints/2000 \
  --group bluir=runs/text_baselines_bluir/2300 \
  --group no_history_codegraph=runs/codegraph_anchor/tse_timesafe_main_20260531_v2 \
  --output-tsv logs/comparison_current/path_mining_file_expansion_ablation_20260531.tsv \
  --top-k 20
```

RQ1/RQ3 paired full-vs-without-file-local statistics:

```bash
python3 scripts/analyze_rq1_paired_stats.py \
  --main full_pathmined=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1 \
  --baseline strict_kg_ablation=runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --output-tsv logs/comparison_current/rq1_pathmined_paired_stats_20260531.tsv
```

RQ3 patch-derived repair-context coverage:

```bash
python3 artifacts/scripts/evaluate_patch_derived_context.py \
  --ids-file temp_run/SWE-bench_Verified_ids.jsonl \
  --gt-cache temp_run/output/gt_eval_cache_verified_v3_entities.json \
  --support-cache artifacts/results/patch_derived_context_targets_20260702.json \
  --output-tsv logs/comparison_current/patch_derived_context_summary_20260702.tsv \
  --output-json logs/comparison_current/patch_derived_context_summary_20260702.json \
  --row "BM25 files + file-local=bm25_filelocal=temp_run/bm25_filelocal" \
  --row "BM25+KG RRF file-local=bm25_kg_rrf_filelocal=temp_run/bm25_kg_rrf_filelocal" \
  --row "GLM-5 + BM25 files + file-local=glm5_bm25_filelocal=temp_run/glm5_bm25_filelocal_b20" \
  --row "GLM-5 + BM25+KG RRF file-local=glm5_bm25_kg_rrf_filelocal=temp_run/glm5_bm25_kg_rrf_b20" \
  --top-k 20
```

BM25 files through the unchanged file-local miner:

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

Direct first-stage ranked-file coverage:

```bash
python3 artifacts/scripts/analyze_ranked_file_sources.py \
  --ids-file temp_run/SWE-bench_Verified_ids.jsonl \
  --gt-cache temp_run/output/gt_eval_cache_verified_v3_entities.json \
  --group KG_grounded_files=runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --group BM25_ranked_files=runs/text_baselines_nohints/2000 \
  --compare KG_grounded_files=BM25_ranked_files \
  --top-files 20 \
  --output-summary logs/comparison_current/ranked_file_source_coverage_20260711.tsv \
  --output-paired logs/comparison_current/ranked_file_source_paired_20260711.tsv
```

Fixed-prefix GLM-5 fusion and the paired Top-20 ledger:

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
  --compare GLM5_issue=GLM5_KG_filelocal \
  --compare GLM5_issue=GLM5_BM25_filelocal \
  --compare GLM5_issue=GLM5_BM25_KG_RRF_filelocal \
  --compare GLM5_KG_filelocal=GLM5_BM25_filelocal \
  --compare GLM5_BM25_filelocal=GLM5_BM25_KG_RRF_filelocal \
  --output-summary logs/comparison_current/retrieve_then_localize_top20_20260711.tsv \
  --output-paired logs/comparison_current/retrieve_then_localize_paired_20260711.tsv \
  --output-disagreements logs/comparison_current/retrieve_then_localize_disagreements_20260711.tsv
```

RQ2 GLM-5 fixed-prefix tail controls:

```bash
OUT_ROOT=temp_run/fusions_glm5_baseline_controls_20260614_head10
PRIMARY=temp_run/eval_aliyun_glm5_issueonly

while IFS="|" read -r name dir; do
  python3 temp_run/export_two_way_fusion.py \
    --primary-dir "$PRIMARY" \
    --secondary-dir "$dir" \
    --output-dir "$OUT_ROOT/$name" \
    --mode intersection \
    --strategy head_tail \
    --top-k 50 \
    --primary-head 10 \
    --secondary-head 10 \
    --force
done <<'EOF'
GLM5_CodeGraph_ht10|runs/codegraph_anchor/tse_timesafe_main_20260531_v2
GLM5_KGCompass_ht10|runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1
EOF

python3 artifacts/scripts/analyze_glm5_baseline_fusion_controls.py \
  --ids-file temp_run/SWE-bench_Verified_ids.jsonl \
  --issue-dir temp_run/eval_aliyun_glm5_issueonly \
  --group GLM5_CodeGraph_ht10=$OUT_ROOT/GLM5_CodeGraph_ht10 \
  --group GLM5_KGCompass_ht10=$OUT_ROOT/GLM5_KGCompass_ht10 \
  --output-tsv logs/comparison_current/glm5_baseline_fusion_controls_top10_20260614_paired.tsv \
  --top-k 20
```

Released Qwen2.5-32B plus KGCompass fusion:

```bash
python3 scripts/eval_external_qwen25_kg_fusion.py \
  --kg-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1 \
  --external-root /tmp/kgc_external_baselines/CoSIL/loc_to_patch_verified \
  --output-tsv logs/comparison_current/qwen25_32b_kgcompass_fusion_20260601.tsv \
  --output-json logs/comparison_current/qwen25_32b_kgcompass_fusion_20260601.json
```

The paper-side ledgers retain only the rows reported in the manuscript.
