# KGCompass

KGCompass is a repository-level bug-localization and repair prototype that combines
LLM-generated candidates with knowledge-graph evidence from repository structure and
historical development context.

This branch is kept intentionally small. It contains only:

- `app.py`, `demo_web.py`, `static/`, and `templates/` for the web demo.
- `kgcompass/`, `scripts/`, and root run scripts for localization/repair workflows.
- `artifacts/` for the paper-facing experiment ledgers, verification scripts, prompts,
  and traceability notes.

## Quick Demo

Install the web-demo dependencies:

```bash
pip install -r requirements_web.txt
```

Run the local demo helper:

```bash
python3 demo_web.py
```

Or start the Flask app directly:

```bash
python3 app.py
```

The web app creates `web_outputs/` at runtime. Generated run outputs are not tracked
in git.

## Paper Artifact

The curated paper artifact lives under `artifacts/`.

Run the result checker:

```bash
python3 artifacts/scripts/verify_paper_results.py
```

Rebuild the RQ3 path/rank audit ledgers:

```bash
python3 artifacts/scripts/rebuild_rq3_path_rank_audit.py
```

Important artifact entry points:

- `artifacts/README.md`: artifact overview and expected checks.
- `artifacts/RESULT_TRACEABILITY.md`: mapping from paper claims to result files.
- `artifacts/results/`: curated experiment results.
- `artifacts/scripts/`: scripts used to verify or regenerate paper-facing tables.

## Repair Pipeline

The repository still includes the core KGCompass scripts and Docker setup needed for
local experiments.

```bash
docker-compose up -d --build
docker-compose exec app bash run_repair.sh <instance_id>
```

Example:

```bash
docker-compose exec app bash run_repair.sh astropy__astropy-12907
```

Stop services with:

```bash
docker-compose down -v
```

## Citation

```bibtex
@article{yang2025enhancing,
  title={Enhancing Repository-Level Software Repair via Repository-Aware Knowledge Graphs},
  author={Yang, Boyang and Ren, Jiadong and Jin, Shunfu and Liu, Yang and Liu, Feng and Le, Bach and Tian, Haoye},
  journal={arXiv preprint arXiv:2503.21710},
  year={2025}
}
```
