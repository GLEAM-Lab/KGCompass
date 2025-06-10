# KGCompass
<div align="center">

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![arXiv](https://img.shields.io/badge/arXiv-2503.21710-b31b1b.svg)](https://arxiv.org/abs/2503.21710)
[![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg?style=flat)](CONTRIBUTING.md)

</div>

KGCompass is a novel approach for repository-level software repair that accurately links code structure with repository metadata using a knowledge graph, enabling more precise bug localization and patch generation.

Paper link: https://arxiv.org/abs/2503.21710

![KGCompass Trajectory Visualization](https://gcdnb.pbrd.co/images/pXnwAe3e5YlQ.png?o=1)

## Simplified Repair Workflow

We provide a simple script to run the entire KGCompass repair pipeline for a single SWE-bench instance. This script automates repository cloning, bug localization, and patch generation.

**Usage:**

1.  **Start Neo4j Database:**
    ```bash
    # Ensure Docker is running, then start the container
    bash neo4j.sh
    ```

2.  **Run Repair Pipeline:**
    ```bash
    # Run the repair for a specific instance
    # The script will automatically clone the required repository if it's not found.
    bash run_repair.sh <instance_id>

    # Example:
    bash run_repair.sh django--django-12345
    ```

This will create a dedicated directory in the `runs/` folder containing the logs and the final generated patch for the specified instance.

## Manual Step-by-Step Reproduction (For Developers)

For developers who wish to inspect the intermediate steps, the manual process is as follows:

#### 1. Knowledge Graph-based Bug Location
```bash
# This step uses the KG to find potentially relevant functions.
python3 dev/fl.py {instance_id} {repo_name} {kg_locations_dir}
```

#### 2. LLM-based Bug Location
```bash
# This step uses an LLM to identify buggy locations.
# Supported models: deepseek, qwen, yi
python3 dev/llm_loc.py {model_name} {num_workers} {llm_locations_dir} --instance_id {instance_id}
```

#### 3. Merge and Fix Bug Locations
```bash
# This step merges the results from the KG and LLM, creating a final location file.
python3 dev/fix_fl_line.py {llm_locations_dir} {final_locations_dir} --instance_id {instance_id}
```

#### 4. Patch Generation
```bash
# This command generates the final patch based on the merged location file.
# The model provider is implicitly 'bailian'.
python3 dev/repair.py {model_name} {num_workers} {temperature} {final_locations_dir} {n_results} --instance_id {instance_id} --output_dir {patch_dir}
```
