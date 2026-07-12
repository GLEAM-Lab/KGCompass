# MURAL Paper Artifacts

This directory contains the submission-side files that directly support the
current MURAL manuscript. The result ledgers under `artifacts/results/` are
trimmed to paper-facing rows only: unreported diagnostics, legacy audits,
obsolete ablations, and partial shard metrics are not included.

The implementation package and several frozen result-row names predate the
MURAL framing. In those ledgers, `KGCompass` denotes the manuscript's current
`KG-local` source, `BM25+KG RRF file-local` denotes standalone MURAL, and
`GLM-5 + BM25+KG RRF file-local` denotes GLM-5+MURAL. These historical labels
are preserved so archived commands, checksums, and the verifier remain stable.

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
- `scripts/export_ranked_file_seeds.py`: converts BM25 method output into a
  ranked file input for the unchanged file-local miner. Each file record keeps
  its best BM25 method rank and the number of retrieved BM25 candidates in that
  file as a label-free source-support signal.
- `scripts/export_fixed_prefix_fusion.py`: builds the fixed-budget
  localizer-prefix plus file-local-tail windows.
- `scripts/export_equal_rrf_fusion.py`: deterministically combines two
  file-local rankings with equal-weight reciprocal-rank fusion (RRF), using
  the stronger source as the declared tie-break only when RRF scores tie.
- `scripts/analyze_retrieve_localize_controls.py`: reports aggregate metrics,
  paired bootstrap intervals, exact McNemar tests, and disagreement instances.
- `scripts/analyze_ranked_file_sources.py`: evaluates the first-stage Top-$N$
  unique file lists before file-local mining.

## Result Ledgers

- `tse_gt_mapping_v6.tsv`: ground-truth target mapping summary used in the
  experimental setup table.
- `path_mining_file_expansion_ablation_20260531.tsv`: RQ1/RQ3 context-window
  source-control rows reported in the manuscript: BM25, BLUiR, CodeGraph,
  graph-only KG, and KG rank union (historically labeled `KGCompass`).
- `rq1_pathmined_paired_stats_20260531.tsv`: paired full-vs-KG-without-file-local
  statistics used for the +65 net Hit@20 gain and 67/2 win/loss claim.
- `llm_pathmined_kg_ht10_20260531.tsv`: issue-only and LLM+KG-local rows for
  GLM-5, Qwen3-Coder-Next, Kimi-K2.5, and Claude-4.6 Sonnet, plus standalone
  KG-local.
- `glm5_baseline_fusion_controls_top10_20260614.tsv`: focused GLM-5 fixed-prefix
  tail controls for CodeGraph and KG-local.
- `retrieve_then_localize_top20_20260711.tsv`: matched Top-20 rows for BM25 and
  KG file sources, the unchanged file-local miner, their untuned equal-weight
  RRF combination, and GLM-5 fixed-prefix fusion with each tail.
- `retrieve_then_localize_paired_20260711.tsv`: paired metric deltas,
  bootstrap intervals, win/loss counts, and exact tests for the main source and
  fusion comparisons.
- `retrieve_then_localize_disagreements_20260711.tsv`: per-instance Hit@20
  disagreement ledger, including the 39 BM25-tail-only and 19 KG-tail-only
  GLM-5 cases.
- `retrieve_then_localize_budget_curve_20260711.tsv` and
  `retrieve_then_localize_budget_paired_20260711.tsv`: fixed-prefix results and
  paired statistics for KG, BM25, and equal-weight RRF tails at total budgets
  5, 10, 20, and 40.
- `ranked_file_source_coverage_20260711.tsv` and
  `ranked_file_source_paired_20260711.tsv`: direct first-stage Top-20 file
  coverage for KG and BM25, including paired uncertainty and exact testing.
- `external_verified_loc_baselines_cosil_release_20260601.tsv`: released
  CoSIL-Qwen2.5-32B localization row used in the same-backbone check.
- `qwen25_32b_kgcompass_fusion_20260601.tsv`: CoSIL-Qwen2.5-32B and
  CoSIL-Qwen2.5-32B+KG-local rows.
- `local_open_models_pathmined_top10_5p5_summary.tsv`: local Qwen3-Coder-30B and
  DeepSeek-Coder-V2-Lite Top-10 issue-only and 5+5 KG-local rows.
- `tse_paired_stats_pathmined_20260531.tsv`: GLM-5 issue-only vs KG-local
  paired statistics.
- `patch_derived_context_summary_20260702.tsv` and `.json`: RQ3
  patch-derived repair-context coverage table. It reports edit-target recall,
  complete edit-target coverage, support-proxy recall, and joint proxy
  coverage for the controlled rows and GLM-5 fixed-prefix rows, including
  BM25-file-local and BM25+KG RRF standalone and fused controls.
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
