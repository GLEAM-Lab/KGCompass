# Result Traceability

This note indexes the submission-side artifacts that support the quantitative claims in the manuscript. It covers the paper-valid localization evidence chain and the downstream repair evidence used for RQ-4.

## Evaluation Scope

- Benchmark: all 500 SWE-bench Verified instances.
- Strict KG artifact: `runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6/`.
- Main path-mined selector output: `runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1/`.
- Main information boundary: time-eligible issue and pull-request titles/descriptions plus base-commit code structure.
- Excluded inputs: benchmark `hint_text`/`hints_text`, all issue and pull-request comments, target fixing pull request links, pull-request patch diffs, linked commits, and artifacts created at or after the target fixing pull request.
- Final audit: `logs/kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json`, copied to `artifacts/results/kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json`.

The final audit reports `total=500`, `ok=500`, `target_pr_hits=0`, `future_fix_trace_hits=0`, `metadata_issues=0`, `content_issue_counts={}`, and `structural_issue_counts={}`. It also reports `warning_content_issue_counts={"generic_fixed_issue_reference": 5}`. These warnings are sentinel matches for generic words such as "fixed" near issue text and are not treated as leakage failures because the flagged entries contain no target PR, future-fix trace, target patch, or metadata violation.

## Paper-side Verification

The paper repository contains a lightweight verifier that reads only committed files under `artifacts/results/` and checks the manuscript-facing numbers:

```bash
python3 artifacts/scripts/verify_paper_results.py
```

The verifier covers the RQ-1/RQ-2/RQ-3/RQ-4 table values, the GLM-5/KG complementarity accounting, the RQ-3 67-win/2-loss file-local-mining accounting and net +65 Hit@20 gain, the exploratory 320-row path/rank audit ledgers, the RQ-4 merged full-500 repair ledgers, and the leakage/sensitivity summaries. It is intended for artifact reviewers who want to validate the final manuscript ledgers without the full experiment workspace.

The exploratory RQ-3 legacy path/rank audit can also be rebuilt separately from its anonymized observation ledgers:

```bash
python3 artifacts/scripts/rebuild_rq3_path_rank_audit.py
```

## Manuscript Tables

- Ground-truth mapping: `logs/comparison_current/tse_gt_mapping_v6.tsv`, copied to `artifacts/results/tse_gt_mapping_v6.tsv`.
- RQ-1 path-mined KGCompass and strict-KG ablation: `logs/comparison_current/path_mining_full500_summary.tsv`, copied to `artifacts/results/path_mining_full500_summary.tsv`.
- RQ-1 baseline rows for BM25, DPR, BLUiR, and No-history CodeGraph: `logs/comparison_current/path_mining_file_expansion_ablation_20260531.tsv`, copied to `artifacts/results/path_mining_file_expansion_ablation_20260531.tsv`. This same ledger also supports the control-ablation table below.
- Path-mining recovered examples: `logs/comparison_current/path_mining_recovered_examples.tsv`, copied to `artifacts/results/path_mining_recovered_examples.tsv`.
- RQ-1 file-expansion control ablations: `logs/comparison_current/path_mining_file_expansion_ablation_20260531.tsv`, copied to `artifacts/results/path_mining_file_expansion_ablation_20260531.tsv`.
- RQ-1 paired statistics, including the matched No-history CodeGraph baseline: `logs/comparison_current/rq1_pathmined_paired_stats_20260531.tsv`, copied to `artifacts/results/rq1_pathmined_paired_stats_20260531.tsv`.
- RQ-3 No-history CodeGraph ablation: `logs/comparison_current/codegraph_anchor_rq3_20260531.tsv`, copied to `artifacts/results/codegraph_anchor_rq3_20260531.tsv`.
- RQ-3 external issue/PR path sensitivity: `logs/comparison_current/time_boundary_external_artifact_sensitivity_20260531.tsv` and `.json`, copied under `artifacts/results/`.
- RQ-3 exploratory legacy path/rank audit: `artifacts/results/rq3_path_audit_observations_20260614.tsv` and `artifacts/results/rq3_rank_audit_observations_20260614.tsv` contain anonymized marginal observation ledgers restored from the earlier path/rank figure-count audit. Each ledger contains 320 outcome-level observations (116 labeled correct, 204 labeled wrong). These ledgers are not a 500-instance per-instance benchmark ledger and are not used as a joint path-rank table.
- RQ-3 path-availability aggregate: `artifacts/results/path_availability_audit_20260613.tsv`, rebuilt from `rq3_path_audit_observations_20260614.tsv`, reports the non-null evidence-path association for the exploratory audit.
- RQ-3 rank-availability aggregate: `artifacts/results/rank_availability_audit_20260613.tsv`, rebuilt from `rq3_rank_audit_observations_20260614.tsv`, reports rank buckets and early-rank association tests for the exploratory audit.
- Benchmark hint/comment exposure audit: `logs/comparison_current/time_boundary_exposure_audit_20260601.tsv`, `.json`, and `logs/comparison_current/time_boundary_exposure_examples_20260601.tsv`, copied under `artifacts/results/`. This audit quantifies how often the raw SWE-bench Verified `hints_text` field exposes comment-derived localization cues; it is a boundary-risk audit, not a claim that a particular compared baseline consumed hints.
- RQ-2 LLM and LLM+path-mined-KG localization: `logs/comparison_current/llm_pathmined_kg_ht10_20260531.tsv`, copied to `artifacts/results/llm_pathmined_kg_ht10_20260531.tsv`.
- RQ-2 GLM-5/KGCompass split-size diagnostic: `logs/comparison_current/fusion_split_sensitivity_glm5_pathmined_20260601.tsv`, copied to `artifacts/results/fusion_split_sensitivity_glm5_pathmined_20260601.tsv`. This is an archived post-hoc robustness audit of the fixed 10+10 fusion contract; it is not used to choose the paper protocol. The row name `GLM5_headH_KG_tail` records the number of GLM-5 candidates initially retained before KGCompass fills and the evaluator applies dedup/backfill. The `GLM5_head20_KG_tail` row is therefore not the GLM-5 issue-only baseline; the issue-only GLM-5 row is in `llm_pathmined_kg_ht10_20260531.tsv`.
- RQ-2 local open-source Top-10 stress rows: `logs/comparison_current/local_open_models_pathmined_top10_5p5_summary.tsv`, copied to `artifacts/results/local_open_models_pathmined_top10_5p5_summary.tsv`.
- RQ-2 released SWE-bench Verified strong baselines: `logs/comparison_current/external_verified_loc_baselines_cosil_release_20260601.tsv` and `.json`, copied to `artifacts/results/external_verified_loc_baselines_cosil_release_20260601.tsv` and `.json`. These rows re-evaluate released CoSIL, LocAgent, Agentless, and OrcaLoca function-localization outputs under the paper's file/method/entity target mapping.
- RQ-2 same-backbone Qwen2.5-32B plus KGCompass fusion: `logs/comparison_current/qwen25_32b_kgcompass_fusion_20260601.tsv` and `.json`, copied to `artifacts/results/qwen25_32b_kgcompass_fusion_20260601.tsv` and `.json`. This ledger preserves each released Qwen2.5-32B localizer's first ten candidates and fills the remaining Top-20 budget with the same path-mined KGCompass artifact used in the main RQ-2 rows.
- Additional Agentless release audit: Agentless released localization outputs are evaluated in `logs/comparison_current/agentless_release_eval_top2groups_fuzzy.json`, copied to `artifacts/results/agentless_release_eval_top2groups_fuzzy.json`; the tabular Top-20 and file@3 comparisons are copied to `artifacts/results/agentless_top2groups_compare_20260601.tsv` and `artifacts/results/agentless_file3_compare.tsv`.
- OrcaLoca source audit: `artifacts/results/orcaloca_external_reference_20260601.json` records that OrcaLoca's own public main localization result is on SWE-bench Lite. The main RQ-2 table instead uses the SWE-bench Verified OrcaLoca output distributed with the CoSIL release artifact and re-evaluated in `external_verified_loc_baselines_cosil_release_20260601.tsv`.
- Archived GLM-5 retrieval-fusion diagnostic: `artifacts/results/glm5_retrieval_fusion_controls_pathmined_20260531.tsv` combines the recomputed path-mined KG fusion row with the unchanged retrieval-fusion controls. This diagnostic is retained for traceability but is not reported in the main manuscript tables.
- Paired statistical analysis: `artifacts/results/tse_paired_stats_pathmined_20260531.tsv`.
- RQ-3 KG mechanism summary: `logs/comparison_current/kg_clean_tse_timesafe_main_20260529_v6_rq3.json` and `.tsv`, copied under `artifacts/results/`.
- RQ-3 Regex/FileExpand ablation: `logs/comparison_current/regex_fileexpand_strict_v1_summary.tsv`, copied to `artifacts/results/regex_fileexpand_strict_v1_summary.tsv`; paired hit accounting is copied to `artifacts/results/regex_fileexpand_strict_v1_paired.json` and `artifacts/results/regex_fileexpand_strict_v1_paired_extended.json`.
- GLM-5 path-mined complementarity analysis: `logs/comparison_current/glm5_pathmined_kg_complementarity_20260531.json`, `.tsv`, and `logs/comparison_current/glm5_pathmined_rescued_instances_20260531.tsv`, copied under `artifacts/results/`.
- Per-project GLM-5 path-mined complementarity: `logs/comparison_current/glm5_pathmined_per_repo_20260531.tsv`, copied to `artifacts/results/glm5_pathmined_per_repo_20260531.tsv`.
- Full-benchmark GLM-5 temperature-0 repair context probe: `artifacts/results/glm5_temp0_repair_context_probe_20260601.tsv` and `.json`, derived from the copied official SWE-bench summaries under `artifacts/results/glm5_temp0_repair_context_probe_20260601/`. This separate 500-instance probe compares issue-only Top-20 localization context against the fixed Top-10 issue-only plus Top-10 path-mined KGCompass context under the same repair prompt, GLM-5 backend, and official SWE-bench evaluator.
- RQ-4 downstream ClaudeCode repair check: `artifacts/results/claudecode_context_probe_glm5_20260531.tsv`, derived from the copied official SWE-bench summaries and official-result JSONL files under `artifacts/results/claudecode_context_probe_glm5_20260531/`. The reported artifacts are the canonical merged `full500_*` ledgers: they deterministically combine the first-100 shard with the remaining-400 shard under the same no-network GLM-5 ClaudeCode harness, and `paired_stats.json` records paired resolved accounting over those merged full-500 ledgers. The only intended experimental input change between arms is whether the appended prompt includes KGCompass suspect files/functions. The RQ-4 run uses the paper-valid path-mined KGCompass artifact `runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1/`.
- Local open-model case-candidate audit: `logs/comparison_current/local_open_models_full500_case_candidates.json`; the submission-side copy is stored under `artifacts/results/`.

Model-label note: the Qwen robustness row is reported with the normalized manuscript label `Qwen3-Coder-Next`. Its source directory name contains the provider endpoint label used when the local run directory was created. The primary controlled claim uses the GLM-5 rows and the same path-mined KGCompass artifact.

Ablation-label note: artifact rows named `strict_kg_ablation` or `kg_clean` correspond to the manuscript's `KGCompass w/o file-local paths` row. They keep typed KG reachability and graph-only ranking but remove file-local path mining and rank union.

Path note: `temp_run/` is the workspace output root used by the evaluation scripts. The paper-side copies under `artifacts/results/` are sufficient for table verification; the full per-instance KG JSON artifact is released separately because of size.

## Reproduction Commands

All commands in this section are intended to be run from the main KGCompass workspace root, tested at commit `cdbf255` on branch `webapp`, where the SWE-bench Verified cache, local base-commit repositories, and full per-instance run directories are available. The mirrored files under `artifacts/scripts/` are source-inspection snapshots only; they intentionally are not standalone paper-repo entrypoints because the runnable scripts expect KGCompass workspace paths such as `SWE-bench_Verified_ids.jsonl`, cached repositories, `kgcompass/`, and `runs/`.

Final leakage audit:

```bash
python3 scripts/audit_kg_leakage.py \
  runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --output-json logs/kg_evidence_graph_tse_timesafe_main_20260529_v6_audit_final.json \
  --fail-on-issue
```

Final path-mined KGCompass export and LLM+KG fusion tables:

```bash
python3 scripts/export_path_mined_filelocal.py \
  --input-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --output-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathsource_v1 \
  --limit 50

python3 scripts/fuse_path_mined_with_kg.py \
  --kg-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --path-mined-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathsource_v1 \
  --output-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1 \
  --limit 50

python3 scripts/eval_controls_v3.py \
  --group pathunion_v1=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1 \
  --group pathsource_v1=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathsource_v1 \
  --group kg_clean=runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --group regex_fileexpand=runs/regex_fileexpand_strict/tse_timesafe_main_20260531_v1 \
  --output-tsv logs/comparison_current/path_mining_full500_summary.tsv \
  --top-k 20
```

The path-mining exporter reparses base-commit source inside KG-grounded files and does not invoke any LLM API or read network data. The LLM+KG ledgers in `llm_pathmined_kg_ht10_20260531.tsv` were produced by fusing existing issue-only LLM localization JSON files with the path-mined KGCompass artifact; the fusion step itself does not invoke any LLM API.

GLM-5/KGCompass split-size diagnostic. This diagnostic preserves the paper's final Top-20 budget and varies only how many GLM-5 predictions are kept before KGCompass fills the remaining slots. It was run after the fixed 10+10 protocol was already in place, so it is treated as an audit rather than a protocol-selection step:

```bash
for h in $(seq 0 20); do
  python3 temp_run/export_two_way_fusion.py \
    --primary-dir temp_run/eval_aliyun_glm5_issueonly \
    --secondary-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1 \
    --output-dir temp_run/fusion_split_sensitivity_glm5_pathmined_20260601/glm5_h${h} \
    --mode intersection \
    --strategy head_tail \
    --top-k 20 \
    --primary-head ${h} \
    --secondary-head 20 \
    --force
done

python3 scripts/eval_controls_v3.py \
  --ids-file SWE-bench_Verified_ids.jsonl \
  $(for h in $(seq 0 20); do printf -- "--group GLM5_head%s_KG_tail=temp_run/fusion_split_sensitivity_glm5_pathmined_20260601/glm5_h%s " "$h" "$h"; done) \
  --output-tsv logs/comparison_current/fusion_split_sensitivity_glm5_pathmined_20260601.tsv
```

Benchmark hint/comment exposure audit:

```bash
HF_DATASETS_OFFLINE=1 HF_HUB_OFFLINE=1 \
python3 scripts/audit_time_boundary_exposure.py \
  --output-json logs/comparison_current/time_boundary_exposure_audit_20260601.json \
  --output-tsv logs/comparison_current/time_boundary_exposure_audit_20260601.tsv \
  --examples-tsv logs/comparison_current/time_boundary_exposure_examples_20260601.tsv
```

This audit loads the cached raw `princeton-nlp/SWE-bench_Verified` dataset to inspect the benchmark `hints_text` field, because the paper-valid local JSONL intentionally strips hints before localization or repair prompts are built.
The public-submission README audit is opportunistic: it summarizes the local snapshot under `/home/barty/research/experiments/evaluation/verified` and does not infer hint usage when a README is silent.

Released Qwen2.5-32B plus KGCompass fusion:

```bash
python3 scripts/eval_external_qwen25_kg_fusion.py \
  --kg-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1 \
  --external-root /tmp/kgc_external_baselines/CoSIL/loc_to_patch_verified \
  --output-tsv logs/comparison_current/qwen25_32b_kgcompass_fusion_20260601.tsv \
  --output-json logs/comparison_current/qwen25_32b_kgcompass_fusion_20260601.json
```

The manuscript reports the CoSIL-Qwen2.5-32B+\tool row from this ledger because CoSIL-Qwen2.5-32B is the strongest released Qwen2.5-32B row in the unified strong-baseline table. The same script also audits Agentless, LocAgent, and OrcaLoca Qwen2.5-32B rows under the identical 10+10 fusion policy.

RQ-4 downstream ClaudeCode repair check. The manuscript reports this full-500 run as the downstream repair RQ while keeping the primary methodological claims on context-window localization and evidence grounding. The paper-side TSV is a mechanical summary of the copied official SWE-bench evaluator outputs under `artifacts/results/claudecode_context_probe_glm5_20260531/`. The `full500` rows combine the first-100 shard with the remaining-400 shard; `paired_stats.json` reports 41 resolved wins and 18 losses for KGCompass over noKG. The `missing_report` field follows the official evaluator summary and counts submitted predictions that did not yield a successfully testable report/result, not missing benchmark instances. The canonical paper-facing summary files are:

- `artifacts/results/claudecode_context_probe_glm5_20260531/first100_nokg_summary.json`
- `artifacts/results/claudecode_context_probe_glm5_20260531/first100_kg_summary.json`
- `artifacts/results/claudecode_context_probe_glm5_20260531/remaining400_nokg_summary.json`
- `artifacts/results/claudecode_context_probe_glm5_20260531/remaining400_kg_summary.json`
- `artifacts/results/claudecode_context_probe_glm5_20260531/full500_nokg_summary.json`
- `artifacts/results/claudecode_context_probe_glm5_20260531/full500_kg_summary.json`

The RQ-4 case-study trace is recorded in `artifacts/results/claudecode_context_probe_glm5_20260531/rq4_case_sphinx_10673.json`, with the source run directories, official statuses, KGCompass suspect context, and patch summary for `sphinx-doc__sphinx-10673`.

Full-benchmark GLM-5 temperature-0 repair context probe. The paper-side TSV is a mechanical summary of two official SWE-bench evaluator summaries copied under `artifacts/results/glm5_temp0_repair_context_probe_20260601/`. A source-inspection snapshot of the driver is copied to `artifacts/scripts/run_glm5_temp0_pair_repair.sh`. The generation script used the same repair prompt and GLM-5 backend for both rows; the only intended input change was the localization context directory. The original workspace sources were:

- `official_glm5_verified_temp0_pair/noKG_top20/r1_c20_t0/summary.json`
- `official_glm5_verified_temp0_pair/KG_10p10_top20/r1_c20_t0/summary.json`
- `predictions_glm5_verified_temp0_pair/noKG_top20/r1_c20_t0/predictions.jsonl`
- `predictions_glm5_verified_temp0_pair/KG_10p10_top20/r1_c20_t0/predictions.jsonl`
- `logs/glm5_verified_temp0_pair/driver_full_workers8_20260601_132356.log`

The corresponding command was:

```bash
OFFICIAL_NAMESPACE=logicstar \
OFFICIAL_MAX_WORKERS=8 \
SEND_SLACK_NOTIFY=1 \
bash temp_run/run_glm5_temp0_pair_repair.sh
```

KG-grounded file-expansion control ablations and paired statistics:

```bash
python3 scripts/export_kg_file_expansion_ablation.py \
  --input-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --output-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_file_source_order_v1 \
  --mode source_order \
  --limit 50

python3 scripts/export_kg_file_expansion_ablation.py \
  --input-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --output-dir runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_file_symbol_rank_v1 \
  --mode symbol_rank \
  --limit 50

python3 scripts/eval_controls_v3.py \
  --group full_pathmined=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1 \
  --group filelocal_symbol_rank=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_file_symbol_rank_v1 \
  --group filelocal_source_order=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_file_source_order_v1 \
  --group local_path_rank_only=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathsource_v1 \
  --group strict_kg_ablation=runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --group regex_fileexpand=runs/regex_fileexpand_strict/tse_timesafe_main_20260531_v1 \
  --group bm25_nohint=runs/text_baselines_nohints/2000 \
  --group dpr_filefirst=runs/text_baselines_dense_filefirst/2203 \
  --group bluir=runs/text_baselines_bluir/2300 \
  --output-tsv logs/comparison_current/path_mining_file_expansion_ablation_20260531.tsv \
  --top-k 20

python3 scripts/analyze_rq1_paired_stats.py \
  --main full_pathmined=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1 \
  --baseline local_path_rank_only=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathsource_v1 \
  --baseline filelocal_symbol_rank=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_file_symbol_rank_v1 \
  --baseline filelocal_source_order=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_file_source_order_v1 \
  --baseline strict_kg_ablation=runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --baseline regex_fileexpand=runs/regex_fileexpand_strict/tse_timesafe_main_20260531_v1 \
  --baseline bm25_nohint=runs/text_baselines_nohints/2000 \
  --baseline dpr_filefirst=runs/text_baselines_dense_filefirst/2203 \
  --baseline bluir=runs/text_baselines_bluir/2300 \
  --output-tsv logs/comparison_current/rq1_pathmined_paired_stats_20260531.tsv
```

No-history CodeGraph baseline:

```bash
python3 scripts/export_codegraph_anchor_baseline.py \
  --workers 12 \
  --output-dir runs/codegraph_anchor/tse_timesafe_main_20260531_v2

python3 scripts/eval_controls_v3.py \
  --group full_pathmined=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1 \
  --group no_history_codegraph=runs/codegraph_anchor/tse_timesafe_main_20260531_v2 \
  --group regex_fileexpand=runs/regex_fileexpand_strict/tse_timesafe_main_20260531_v1 \
  --group strict_kg_ablation=runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --output-tsv logs/comparison_current/codegraph_anchor_rq3_20260531.tsv \
  --top-k 20
```

This baseline disables all historical issue and pull-request artifacts. It extracts anchors only from the target issue title/body and follows base-commit code graph evidence (explicit file paths, dotted modules, definition-file hits, grep file hits, path-token overlap, and import-neighbor expansion). Its priority constants are fixed in `scripts/export_codegraph_anchor_baseline.py` and were not tuned on SWE-bench Verified. The paper-side source snapshot lists the values at `artifacts/scripts/export_codegraph_anchor_baseline.py:53-61`: explicit path = 1000, dotted module = 800, definition file = 120, git grep file = 15, path token = 4, import-neighbor decay = 0.55, distance score = 1,000,000, file-score scale = 100, and symbol score = 1000.

Strict Regex/FileExpand ablation. A source-inspection snapshot of the exporter is copied to this paper repository at `artifacts/scripts/export_regex_fileexpand_baseline.py`:

```bash
python3 scripts/export_regex_fileexpand_baseline.py \
  --workers 12 \
  --output-dir runs/regex_fileexpand_strict/tse_timesafe_main_20260531_v1

python3 scripts/eval_controls_v3.py \
  --group regex_fileexpand_strict=runs/regex_fileexpand_strict/tse_timesafe_main_20260531_v1 \
  --group strict_kg_ablation=runs/kg_verified_evidence_graph/tse_timesafe_main_20260529_v6 \
  --group kgcompass=runs/kg_verified_evidence_graph/tse_timesafe_main_20260531_pathunion_v1 \
  --group bm25_nohint=runs/text_baselines_nohints/2000 \
  --output-tsv logs/comparison_current/regex_fileexpand_strict_v1_summary.tsv \
  --top-k 20
```

This ablation uses issue text and base-commit source only. It does not invoke an LLM API and does not read KG edges, comments, benchmark hints, future artifacts, or target patch content.
All paper-side script copies are for source inspection; the reproduction commands above should be run from the main KGCompass workspace, where `SWE-bench_Verified_ids.jsonl`, cached base repositories, and comparison scripts are available.
