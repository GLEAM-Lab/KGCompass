# KGCompass Paper Artifacts

This directory contains the submission-side files that directly support the
current KGCompass manuscript. The result ledgers under `artifacts/results/` are
trimmed to paper-facing rows only: unreported diagnostics, legacy audits,
obsolete ablations, and partial shard metrics are not included.

## Top-Level Files

- `motivating_case_django_15503.json`: selected motivating example evidence for
  `django__django-15503`, matching the manuscript's motivating figure.
- `issue_comment_boundary.json`: input-boundary note documenting that benchmark
  hints and issue/PR comments are excluded from the paper-valid localization
  setting.
- `prompts/llm_fault_location_prompt.md`: LLM issue-only localization prompt.
- `RESULT_TRACEABILITY.md`: source-to-claim mapping and rerun command index.
- `scripts/evaluate_patch_derived_context.py`: reproduces the patch-derived
  repair-context coverage ledger from official SWE-bench Verified patches,
  cached target mappings, and ranked context-window outputs.

## Result Ledgers

- `tse_gt_mapping_v6.tsv`: ground-truth target mapping summary used in the
  experimental setup table.
- `path_mining_file_expansion_ablation_20260531.tsv`: RQ1/RQ3 context-window
  rows reported in the manuscript: BM25, BLUiR, CodeGraph, KGCompass without
  file-local paths, and full KGCompass.
- `path_mining_full500_summary.tsv`: compact full/KG-only summary
  used for RQ3 hit-count accounting.
- `rq1_pathmined_paired_stats_20260531.tsv`: paired full-vs-KG-without-file-local
  statistics used for the +65 net Hit@20 gain and 67/2 win/loss claim.
- `llm_pathmined_kg_ht10_20260531.tsv`: issue-only and LLM+KGCompass rows for
  GLM-5, Qwen3-Coder-Next, Kimi-K2.5, and Claude-4.6 Sonnet, plus standalone
  KGCompass.
- `glm5_baseline_fusion_controls_top10_20260614.tsv`: focused GLM-5 fixed-prefix
  tail controls for CodeGraph and KGCompass.
- `external_verified_loc_baselines_cosil_release_20260601.tsv`: released
  SWE-bench Verified Qwen2.5-32B localizer rows reported in the unified
  strong-baseline table.
- `qwen25_32b_kgcompass_fusion_20260601.tsv`: CoSIL-Qwen2.5-32B and
  CoSIL-Qwen2.5-32B+KGCompass rows.
- `local_open_models_pathmined_top10_5p5_summary.tsv`: local Qwen3-Coder-30B and
  DeepSeek-Coder-V2-Lite Top-10 issue-only and 5+5 KGCompass rows.
- `glm5_pathmined_kg_complementarity_20260531.json` and `.tsv`: GLM-5/KGCompass
  overlap and rescued-instance aggregate accounting.
- `glm5_pathmined_rescued_instances_20260531.tsv`: per-instance ledger for the
  58 GLM-5 fusion wins.
- `tse_paired_stats_pathmined_20260531.tsv`: GLM-5 issue-only vs KGCompass
  paired statistics.
- `kg_clean_tse_timesafe_main_20260529_v6_rq3.json` and `.tsv`: KG-only evidence
  path and rank summaries used by the mechanism analysis.
- `rq3_file_local_path_mining_summary.tsv`: RQ3 file-local path-mining aggregate
  counts, including the 67 gross wins, 2 regressions, and 55 three-hop wins.
- `patch_derived_context_summary_20260702.tsv` and `.json`: RQ3
  patch-derived repair-context coverage table. It reports edit-target recall,
  complete edit-target coverage, support-context recall, and context
  completeness for the controlled rows and GLM-5 fixed-prefix rows.
- `patch_derived_context_targets_20260702.json`: deterministic edit/support
  target cache used by the patch-derived context evaluation. Support targets
  are non-edited functions or assignments in patched files whose simple names
  appear as calls or attribute references in official patch hunks.
- `time_boundary_external_artifact_sensitivity_20260531.tsv`: sensitivity check
  cited in threats to validity.
- `kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json`: final
  leakage-sentinel audit.
- `claudecode_context_probe_glm5_20260531.tsv`: RQ4 full-500 repair summary.
- `claudecode_context_probe_glm5_20260531/`: RQ4 full-500 official result
  ledgers, summary JSON files, paired full-500 statistics, and the
  `sphinx-doc__sphinx-10673` case trace.

## Verifier

Run:

```bash
python3 artifacts/scripts/verify_paper_results.py
```

The verifier checks only the paper-facing files listed above, including the
patch-derived repair-context ledgers, and also fails if unexpected result files
are present under `artifacts/results/`.
