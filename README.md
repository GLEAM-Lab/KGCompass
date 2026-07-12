# MURAL

MURAL (Multi-source Unification of Retrieval And Localization) is a
fixed-budget repair-context system for issue-driven repository repair. It
passes BM25 and typed-knowledge-graph file rankings through the same
source-agnostic local selector, fuses the resulting entity rankings, and can
fill the unused tail of an existing localizer's context window.

This repository is the public artifact for the MURAL manuscript. It keeps the
demo, core scripts, and paper-facing ledgers needed to audit the reported
RQ1-RQ4 claims. Older diagnostics, unreported ablations, and partial
intermediate results are intentionally omitted from `artifacts/results/`.
The `kgcompass/` package name and frozen `KGCompass` result labels are retained
for compatibility; the artifact notes map them to the manuscript terminology.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `app.py`, `demo_web.py`, `static/`, `templates/` | Local web demo. |
| `kgcompass/` | Core localization and repair modules (legacy package name). |
| `scripts/` | Workspace scripts used to build localization and summary ledgers. |
| `artifacts/` | Paper-facing result ledgers, prompts, audit notes, and verifier. |
| `artifacts/results/` | Small committed ledgers aligned with manuscript tables and claims. |
| `artifacts/RESULT_TRACEABILITY.md` | Mapping from manuscript claims to artifact files and rerun commands. |

## Quick Start

Create a Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the paper-side verifier:

```bash
python3 artifacts/scripts/verify_paper_results.py
```

Expected result:

```json
{
  "ok": true,
  "scope": "all",
  "failed": []
}
```

The verifier reads only files committed under `artifacts/results/` and checks
the manuscript-facing values for the ground-truth mapping, RQ1 controlled
context windows, RQ2 LLM and released-localizer fusion rows, RQ3
patch-derived repair-context coverage, RQ4 full-500
repair outcomes, and leakage/sensitivity statements.

## Paper-Facing Results

The main ledgers are:

- `artifacts/results/tse_gt_mapping_v6.tsv`
- `artifacts/results/path_mining_file_expansion_ablation_20260531.tsv`
- `artifacts/results/llm_pathmined_kg_ht10_20260531.tsv`
- `artifacts/results/glm5_baseline_fusion_controls_top10_20260614.tsv`
- `artifacts/results/external_verified_loc_baselines_cosil_release_20260601.tsv`
- `artifacts/results/qwen25_32b_kgcompass_fusion_20260601.tsv`
- `artifacts/results/local_open_models_pathmined_top10_5p5_summary.tsv`
- `artifacts/results/patch_derived_context_summary_20260702.tsv`
- `artifacts/results/claudecode_context_probe_glm5_20260531.tsv`

See `artifacts/RESULT_TRACEABILITY.md` for the complete file-to-claim mapping
and the full-workspace commands used to produce the ledgers.

## Web Demo

Install the smaller web-demo dependency set if you only want to run the UI:

```bash
pip install -r requirements_web.txt
python3 demo_web.py
```

Or start the Flask app directly:

```bash
python3 app.py
```

The web app writes generated outputs to `web_outputs/` at runtime. Those outputs
are intentionally ignored by the repository.
