# KGCompass Paper Artifacts

This directory contains submission-side traceability artifacts for the final KGCompass manuscript. The small ledgers under `artifacts/results/` are sufficient to verify the manuscript tables and key RQ statements; the full per-instance KG JSON directories remain in the main KGCompass experiment workspace because of size.

- `motivating_case_django_15503.json`: selected path-mined motivating example evidence for `django__django-15503`, including ground-truth patch locations, KGCompass rank/path, and BM25/GLM-5/strict-KG top predictions.
- `motivating_case_django_13344.json`: archived earlier clean example evidence retained for traceability but no longer used as the manuscript's main motivating case.
- `motivating_case_search_summary.json`: summary of the offline cache search used to select a fair motivating example where full path-mined KGCompass hits while BM25, GLM-5 issue-only, Regex/FileExpand, and strict KG miss.
- `issue_comment_boundary.json`: leakage boundary for issue comments and benchmark hint fields, documenting that all issue/PR comments and `hint_text`/`hints_text` are excluded from the paper-valid localization setting.
- `results/time_boundary_exposure_audit_20260601.tsv`, `.json`, and `results/time_boundary_exposure_examples_20260601.tsv`: empirical exposure audit for the raw SWE-bench Verified `hints_text` field, showing how often the comment-derived hint channel contains localization cues such as edited file paths, line-anchored GitHub URLs, and diff-like snippets.
- `results/path_mining_full500_summary.tsv` and `results/path_mining_recovered_examples.tsv`: full path-mined KGCompass localization ledger and recovered examples. This is the main method output; strict KG is kept as an ablation.
- `results/rq3_path_audit_observations_20260614.tsv` and `results/rq3_rank_audit_observations_20260614.tsv`: anonymized marginal observation ledgers for the exploratory RQ-3 legacy path/rank audit. Each ledger has 320 outcome-level observations restored from the earlier figure-count audit (116 labeled correct, 204 labeled wrong). They are not a 500-instance per-instance benchmark ledger and should not be read as a joint path-rank table.
- `results/path_availability_audit_20260613.tsv`: aggregate path-availability table rebuilt from the RQ-3 path-audit observation ledger, reporting the non-null-path association test.
- `results/rank_availability_audit_20260613.tsv`: aggregate rank-availability table rebuilt from the RQ-3 rank-audit observation ledger, reporting Top-1/Top-5/Top-10/Top-20 association tests.
- `results/path_mining_file_expansion_ablation_20260531.tsv`: controlled localization and KG-grounded file-expansion ablations comparing full path-mined KGCompass against retrieval baselines, CodeGraph, source-order expansion, symbol-only expansion, LocalPathRank, and the KG-reachability-only ablation reported in the manuscript as `KGCompass w/o file-local paths`.
- `results/rq1_pathmined_paired_stats_20260531.tsv`: paired RQ-1 confidence intervals and exact McNemar tests.
- `results/codegraph_anchor_rq3_20260531.tsv`: No-history CodeGraph baseline evaluated under the same Top-20 localization metrics; it disables all historical issue/PR artifacts and uses only the target issue title/body plus base-commit source code.
- `results/time_boundary_external_artifact_sensitivity_20260531.tsv` and `.json`: sensitivity analysis that removes non-root issue/PR evidence-path candidates from the Top-20 export.
- `results/llm_pathmined_kg_ht10_20260531.tsv`: LLM-only and LLM+path-mined-KG localization ledger used in RQ-2.
- `results/glm5_baseline_fusion_controls_top10_20260614.tsv`: GLM-5 Top-10+second-source Top-10 fusion controls for BM25, DPR, BLUiR, CodeGraph, Regex/FileExpand, LocalPathRank, and KGCompass, including paired Hit@20 wins/losses against GLM-5 issue-only.
- `results/fusion_split_sensitivity_glm5_pathmined_20260601.tsv`: archived post-hoc diagnostic of GLM-5/KGCompass split sizes under the same Top-20 budget. Rows are named by the number of GLM-5 predictions initially retained before KGCompass fills and the evaluator applies dedup/backfill. This file audits robustness of the fixed 10+10 interface and is not used to select the paper protocol or to define the GLM-5 issue-only baseline.
- `results/local_open_models_pathmined_top10_5p5_summary.tsv`: local open-source model Top-10 stress rows used in RQ-2, covering Qwen3-Coder-30B and DeepSeek-Coder-V2-Lite with and without the 5+5 KGCompass context.
- `results/external_verified_loc_baselines_cosil_release_20260601.tsv` and `.json`: released SWE-bench Verified localization outputs from CoSIL, LocAgent, Agentless, and OrcaLoca, re-evaluated with the paper's file/method/entity target mapping for the unified RQ-2 strong-baseline table.
- `results/qwen25_32b_kgcompass_fusion_20260601.tsv` and `.json`: released Qwen2.5-32B strong-baseline rows with the same 10+10 KGCompass fusion contract used in RQ-2.
- `results/agentless_release_eval_top2groups_fuzzy.json`, `results/agentless_top2groups_compare_20260601.tsv`, and `results/agentless_file3_compare.tsv`: additional audit of the original Agentless release localization outputs on the same 500 SWE-bench Verified instances.
- `results/orcaloca_external_reference_20260601.json` and `results/lite_verified_intersection_current_methods.tsv`: OrcaLoca source audit, documenting that OrcaLoca's own public main localization result is reported on SWE-bench Lite; the main RQ-2 table uses the SWE-bench Verified OrcaLoca output distributed with the CoSIL release artifact.
- `results/regex_fileexpand_strict_v1_summary.tsv`, `results/regex_fileexpand_strict_v1_paired.json`, and `results/regex_fileexpand_strict_v1_paired_extended.json`: strict KG-free Regex/FileExpand ablation used in RQ-3 to test whether KGCompass reduces to issue-text pattern matching plus file expansion.
- `results/local_open_models_full500_case_candidates.json`: archived localization case-candidate ledger from the local open-model audit.
- `results/claudecode_context_probe_glm5_20260531.tsv` and `results/claudecode_context_probe_glm5_20260531/`: RQ-4 downstream repair check with a GLM-5-backed ClaudeCode repair harness on all 500 SWE-bench Verified instances with both no-KG and +KG official summaries. The canonical reported files are the merged `full500_*` ledgers. They deterministically merge the first-100 and remaining-400 disjoint shards under the same no-network harness. `paired_stats.json` gives the paired resolved accounting over the merged full-500 ledgers. In this ledger, `missing_report` follows the official evaluator summary and counts submitted predictions that did not yield a successfully testable report/result, not missing benchmark instances.
- `results/claudecode_context_probe_glm5_20260531/rq4_case_sphinx_10673.json`: trace record for the RQ-4 in-depth repair case study.
- `scripts/export_codegraph_anchor_baseline.py`: source-inspection snapshot of the No-history CodeGraph exporter.
- `scripts/export_path_mined_filelocal.py` and `scripts/fuse_path_mined_with_kg.py`: source-inspection snapshots of the path-mining and rank-union exporters.
- `scripts/export_kg_file_expansion_ablation.py` and `scripts/analyze_rq1_paired_stats.py`: source-inspection snapshots of the file-expansion control ablation and paired-statistics scripts.
- `scripts/export_regex_fileexpand_baseline.py`: source-inspection snapshot of the strict Regex/FileExpand exporter.
- `scripts/analyze_glm5_baseline_fusion_controls.py`: source-inspection snapshot of the GLM-5 Top-10+baseline fusion paired-accounting script.
- `scripts/audit_time_boundary_exposure.py`: source-inspection snapshot of the hint/comment exposure audit.
- `scripts/eval_external_qwen25_kg_fusion.py`: source-inspection snapshot of the released Qwen2.5-32B plus KGCompass fusion evaluator.
- `scripts/verify_paper_results.py`: paper-side verifier that reads only committed files under `artifacts/results/` and checks the manuscript-facing table values and key RQ statements.
- `scripts/rebuild_rq3_path_rank_audit.py`: paper-side checker that rebuilds the exploratory RQ-3 legacy path/rank audit summaries from the anonymized observation ledgers.
- `RESULT_TRACEABILITY.md`: index of the final result sources and reproduction commands used by the manuscript.
- `results/`: submission-side copies of the final audit, table ledgers, RQ-3 mechanism summaries, and case-study notes used by the manuscript.

The manuscript's localization numbers trace to the completed paper-valid strict KG artifact `runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6/`, the full path-mined selector output `runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1/`, and the comparison ledgers listed in `RESULT_TRACEABILITY.md`. The paper-valid setting may use time-eligible repository artifacts, but only titles/descriptions and code-visible anchors, never issue/PR comments, benchmark hints, target fixing artifacts, future fixing artifacts, pull-request patch diffs, or linked patch/commit expansion.

Leakage-sentinel audits can be reproduced from the main KGCompass workspace with `scripts/audit_kg_leakage.py`; a paper-side copy is available at `artifacts/scripts/audit_kg_leakage.py` for source inspection. The final audit is `logs/kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json`. It reports zero target-PR hits, future-fix hits, content issues, structural issues, and metadata issues. It also reports five `generic_fixed_issue_reference` warnings; these are sentinel warnings for generic words such as "fixed" near issue text, not leakage failures. Localization cache summaries can be reproduced from the main workspace with `scripts/summarize_prefl_cache.py`.

## Reviewer Quick Path

Reviewers should start from the following files. The paths below are main KGCompass workspace paths; paper-side copies of the final ledgers are stored under `artifacts/results/` in this repository and are sufficient to verify the manuscript tables. The `temp_run/` prefix in some source columns is the workspace output root used by the evaluation scripts.

The mirrored files under `artifacts/scripts/` are source-inspection snapshots, not standalone paper-repo entrypoints. Reproduction commands should be run from the main KGCompass repository on `main`, where the SWE-bench Verified cache, local base-commit repositories, and full per-instance run directories are available.

For a paper-side consistency check that does not require the main experiment workspace, run:

```bash
python3 artifacts/scripts/verify_paper_results.py
```

The verifier reads only committed files under `artifacts/results/` and checks the main manuscript table values, the RQ-2 complementarity accounting, the RQ-3 67-win/2-loss file-local-mining accounting and net +65 Hit@20 gain, the exploratory 320-row path/rank audit ledgers, the RQ-4 merged full-500 repair ledgers and paired repair results, and the leakage/sensitivity audit summaries.

To rebuild only the exploratory RQ-3 legacy audit summaries from the anonymized observation ledgers, run:

```bash
python3 artifacts/scripts/rebuild_rq3_path_rank_audit.py
```

1. Manuscript source: `main.tex` and Sections `0.abstract.tex`--`9.conclusion.tex`.
2. Final leakage audit: `logs/kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json`.
3. Final table ledgers:
   - `logs/comparison_current/path_mining_full500_summary.tsv`
   - `logs/comparison_current/path_mining_file_expansion_ablation_20260531.tsv`
   - `logs/comparison_current/rq1_pathmined_paired_stats_20260531.tsv`
   - `logs/comparison_current/codegraph_anchor_rq3_20260531.tsv`
   - `logs/comparison_current/time_boundary_external_artifact_sensitivity_20260531.tsv`
   - `logs/comparison_current/time_boundary_exposure_audit_20260601.tsv`
   - `logs/comparison_current/llm_pathmined_kg_ht10_20260531.tsv`
   - `artifacts/results/glm5_baseline_fusion_controls_top10_20260614.tsv`
   - `logs/comparison_current/fusion_split_sensitivity_glm5_pathmined_20260601.tsv`
   - `logs/comparison_current/qwen25_32b_kgcompass_fusion_20260601.tsv`
   - `logs/comparison_current/kg_clean_tse_timesafe_main_20260529_v6_rq3.json`
   - `logs/comparison_current/regex_fileexpand_strict_v1_summary.tsv`
   - `artifacts/results/glm5_retrieval_fusion_controls_pathmined_20260531.tsv`
   - `logs/comparison_current/glm5_pathmined_kg_complementarity_20260531.json`
   - `artifacts/results/tse_paired_stats_pathmined_20260531.tsv`
   - `logs/comparison_current/glm5_pathmined_per_repo_20260531.tsv`
   - `logs/comparison_current/local_open_models_pathmined_top10_5p5_summary.tsv`
   - `artifacts/results/claudecode_context_probe_glm5_20260531.tsv`
   - `artifacts/results/claudecode_context_probe_glm5_20260531/rq4_case_sphinx_10673.json`
   - `logs/comparison_current/local_open_models_full500_case_candidates.json`
4. Reproduction ledger: `RESULT_TRACEABILITY.md`.

The main-paper evidence chain is localization-first and uses the complete 500-instance SWE-bench Verified benchmark.

For convenience, the same small final ledgers are copied under `artifacts/results/` in this paper repository. The large per-instance KG JSON directory remains in the main KGCompass experiment workspace.
