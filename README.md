# MURAL

MURAL (Multi-source Unification of Retrieval And Localization) is a
fixed-budget repair-context system for issue-driven repository repair. It
passes BM25 and typed-knowledge-graph file rankings through the same
source-agnostic local selector, fuses the resulting entity rankings, and can
fill the unused tail of an existing localizer's context window.

This repository is the public artifact for the MURAL manuscript. It keeps the
demo, core scripts, and submission-facing ledgers needed to audit the three
main research questions and the separately compiled supplementary material.
Older diagnostics, unreported ablations, partial intermediate results, and the
retired KG-only downstream repair study are intentionally omitted from
`artifacts/results/`.
The `kgcompass/` package name and frozen `KGCompass` result labels are retained
for compatibility; the artifact notes map them to the manuscript terminology.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `app.py`, `demo_web.py`, `static/`, `templates/` | Local web demo. |
| `kgcompass/` | Core localization and repair modules (legacy package name). |
| `scripts/` | Workspace scripts used to build localization and summary ledgers. |
| `artifacts/` | Submission-facing result ledgers, prompts, audit notes, and verifier. |
| `artifacts/results/` | Small committed ledgers aligned with manuscript tables and claims. |
| `artifacts/RESULT_TRACEABILITY.md` | Mapping from manuscript claims to artifact files and rerun commands. |

## Quick Start

Create a Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the submission-side verifier:

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
the ground-truth mapping, controlled context windows, fixed-prefix fusion,
supplementary budget sensitivity, mapped edit-target coverage, and
leakage/sensitivity statements.

## Submission-Facing Results

The main ledgers are:

- `artifacts/results/tse_gt_mapping_v6.tsv`
- `artifacts/results/path_mining_file_expansion_ablation_20260531.tsv`
- `artifacts/results/retrieve_then_localize_top20_20260711.tsv`
- `artifacts/results/retrieve_then_localize_paired_20260711.tsv`
- `artifacts/results/retrieve_then_localize_budget_curve_20260711.tsv`
- `artifacts/results/glm5_baseline_fusion_controls_top10_20260614.tsv`
- `artifacts/results/patch_derived_context_summary_20260702.tsv`

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
