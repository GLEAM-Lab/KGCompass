# MURAL Submission Artifacts

This directory contains the files that directly support the MURAL manuscript
and its separately compiled supplementary material. The result ledgers under
`artifacts/results/` are restricted to reported rows and audit records.
Unreported diagnostics, obsolete ablations, partial shard metrics, and the
retired KG-only downstream repair study are not included.

The implementation package and several frozen result-row names predate the
MURAL framing. In retained ledgers, `KGCompass` denotes the manuscript's
`KG-local` source, `BM25+KG RRF file-local` denotes standalone MURAL, and
`GLM-5 + BM25+KG RRF file-local` denotes GLM-5+MURAL. Historical labels remain
unchanged so archived commands and checksums stay stable.

## Top-Level Files

- `motivating_case_django_15503.json`: evidence for the motivating example.
- `issue_comment_boundary.json`: input-boundary and leakage-audit note.
- `prompts/llm_fault_location_prompt.md`: verbatim LLM localization prompt,
  reproduced in the supplementary material.
- `RESULT_TRACEABILITY.md`: file-to-claim mapping and reproduction commands.
- `scripts/verify_paper_results.py`: strict result-inventory and value checker.
- `scripts/export_ranked_file_seeds.py`: converts BM25 code-method output to
  ranked file records for the shared file-local selector.
- `scripts/export_fixed_prefix_fusion.py`: builds prefix-preserving context
  windows under a fixed output budget.
- `scripts/export_equal_rrf_fusion.py`: combines BM25-local and KG-local
  rankings with equal-weight reciprocal-rank fusion (RRF).
- `scripts/analyze_retrieve_localize_controls.py`: computes aggregate metrics,
  paired bootstrap intervals, exact McNemar tests, and disagreement records.
- `scripts/evaluate_patch_derived_context.py`: computes mapped edit-target
  recall and complete edit-target coverage.

## Main-Manuscript Ledgers

- `tse_gt_mapping_v6.tsv`: target-mapping summary for all 500 instances.
- `path_mining_file_expansion_ablation_20260531.tsv`: BM25, BLUiR, CodeGraph,
  graph-only KG, and KG-local controlled rows.
- `retrieve_then_localize_top20_20260711.tsv`: matched BM25/KG file-source,
  file-local, MURAL, and GLM-5 fixed-prefix rows.
- `retrieve_then_localize_paired_20260711.tsv`: paired deltas, bootstrap
  intervals, win/loss counts, and exact tests for the main comparisons.
- `retrieve_then_localize_disagreements_20260711.tsv`: per-instance Hit@20
  disagreement records for the reported source comparisons.
- `ranked_file_source_coverage_20260711.tsv` and
  `ranked_file_source_paired_20260711.tsv`: first-stage Top-20 file coverage.
- `glm5_baseline_fusion_controls_top10_20260614.tsv`: fixed-prefix CodeGraph and
  KG-local controls used in RQ-2.
- `patch_derived_context_summary_20260702.tsv` and `.json`: mapped edit-target
  coverage used in RQ-3.
- `patch_derived_context_targets_20260702.json`: deterministic edit-target
  cache used by the patch-derived evaluation.
- `time_boundary_external_artifact_sensitivity_20260531.tsv`: external-artifact
  sensitivity statement in threats to validity.
- `kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json`: final
  leakage-sentinel audit.

## Supplementary Ledgers

- `retrieve_then_localize_budget_curve_20260711.tsv` and
  `retrieve_then_localize_budget_paired_20260711.tsv`: budgets 5, 10, 20, and
  40 for KG-local, BM25-local, and MURAL tails.

## Verifier

Run:

```bash
python3 artifacts/scripts/verify_paper_results.py
```

The verifier checks every retained main-manuscript and supplementary value. It
also fails when an unexpected file appears under `artifacts/results/`, which
keeps the public result inventory aligned with the submitted documents.
