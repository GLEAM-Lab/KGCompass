#!/bin/bash
set -e

# --- Configuration ---
INSTANCE_ID=$1
MODEL_PROVIDER=${MODEL_PROVIDER:-"bailian"}
MODEL_NAME=${MODEL_NAME:-"deepseek"}
NUM_WORKERS=${NUM_WORKERS:-8}
TEMPERATURE=${TEMPERATURE:-0}

if [ -z "$INSTANCE_ID" ]; then
  echo "Usage: $0 <instance_id>"
  echo "Example: $0 django--django-12345"
  exit 1
fi

# --- Repository Cloning ---
declare -A REPO_URL_MAP
REPO_URL_MAP["astropy__astropy"]="https://github.com/astropy/astropy.git"
REPO_URL_MAP["django__django"]="https://github.com/django/django.git"
REPO_URL_MAP["matplotlib__matplotlib"]="https://github.com/matplotlib/matplotlib.git"
REPO_URL_MAP["mwaskom__seaborn"]="https://github.com/mwaskom/seaborn.git"
REPO_URL_MAP["psf__requests"]="https://github.com/psf/requests.git"
REPO_URL_MAP["pylint-dev__pylint"]="https://github.com/pylint-dev/pylint.git"
REPO_URL_MAP["pytest-dev__pytest"]="https://github.com/pytest-dev/pytest.git"
REPO_URL_MAP["scikit-learn__scikit-learn"]="https://github.com/scikit-learn/scikit-learn.git"
REPO_URL_MAP["sphinx-doc__sphinx"]="https://github.com/sphinx-doc/sphinx.git"
REPO_URL_MAP["sympy__sympy"]="https://github.com/sympy/sympy.git"

REPO_IDENTIFIER=${INSTANCE_ID%-*}
CLONE_URL=${REPO_URL_MAP[$REPO_IDENTIFIER]}
REPOS_DIR="../swe_bench_repos" # A directory outside the project to store all cloned repos
REPO_PATH="${REPOS_DIR}/${REPO_IDENTIFIER}"

if [ -z "$CLONE_URL" ]; then
  echo "ERROR: Repository for '$REPO_IDENTIFIER' not found in the script's map." >&2
  echo "Please add the git clone URL for this repository to run_repair.sh" >&2
  exit 1
fi

if [ ! -d "$REPO_PATH" ]; then
  echo "--- Repository '$REPO_IDENTIFIER' not found. Cloning... ---"
  mkdir -p "$REPOS_DIR"
  git clone "$CLONE_URL" "$REPO_PATH"
  echo "✅ Repository cloned to $REPO_PATH"
else
  echo "✅ Repository '$REPO_IDENTIFIER' already exists at $REPO_PATH."
fi

# --- Derived variables ---
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RUN_DIR="runs/${INSTANCE_ID}_${MODEL_NAME}_${TIMESTAMP}"
REPAIR_MODEL_NAME="${MODEL_NAME}_0" # Default repair config

# --- Directories for this run ---
mkdir -p "$RUN_DIR"
KG_LOCATIONS_DIR="${RUN_DIR}/kg_locations"
LLM_LOCATIONS_DIR="${RUN_DIR}/llm_locations"
FINAL_LOCATIONS_DIR="${RUN_DIR}/final_locations"
PATCH_DIR="${RUN_DIR}/patches"
LOG_FILE="${RUN_DIR}/run.log"

mkdir -p "$KG_LOCATIONS_DIR" "$LLM_LOCATIONS_DIR" "$FINAL_LOCATIONS_DIR" "$PATCH_DIR"

# Redirect all output to log file and console
exec > >(tee -a "$LOG_FILE") 2>&1

echo "================================================="
echo "Starting KGCompass repair for instance: $INSTANCE_ID"
echo "Run directory: $RUN_DIR"
echo "================================================="

# --- Prerequisites check ---
if ! nc -z localhost 7687; then
  echo "ERROR: Neo4j is not running on localhost:7687. Please start it first." >&2
  echo "You can use: bash neo4j.sh" >&2
  exit 1
fi
echo "✅ Neo4j connection successful."

# --- Pipeline Steps ---

# Step 1: Knowledge Graph-based Bug Location
echo -e "\n--- Step 1: KG-based Bug Location ---"
# Assumes fl.py writes its output to {location_dir}/{instance_id}.json
python3 kgcompass/fl.py "$INSTANCE_ID" "$REPO_IDENTIFIER" "$KG_LOCATIONS_DIR"
echo "✅ KG location saved to ${KG_LOCATIONS_DIR}/${INSTANCE_ID}.json"

# Step 2: LLM-based Bug Location
echo -e "\n--- Step 2: LLM-based Bug Location ---"
# Assumes llm_loc.py can take --instance_id to process a single instance
python3 kgcompass/llm_loc.py "$MODEL_NAME" "$NUM_WORKERS" "$LLM_LOCATIONS_DIR" --instance_id "$INSTANCE_ID"
echo "✅ LLM location saved to ${LLM_LOCATIONS_DIR}/${INSTANCE_ID}.json"

# Step 3: Fix/Merge Bug Location
echo -e "\n--- Step 3: Merge and Fix Bug Locations ---"
# Assumes fix_fl_line.py is adapted to work on single instances from specific dirs
python3 kgcompass/fix_fl_line.py "$LLM_LOCATIONS_DIR" "$FINAL_LOCATIONS_DIR" --instance_id "$INSTANCE_ID"
echo "✅ Final location saved to ${FINAL_LOCATIONS_DIR}/${INSTANCE_ID}.json"

# Step 4: Final Patch Generation
echo -e "\n--- Step 4: Final Patch Generation ---"
# Assumes repair.py uses the final location file to generate the patch
python3 kgcompass/repair.py "$REPAIR_MODEL_NAME" "$NUM_WORKERS" "$MODEL_PROVIDER" "$TEMPERATURE" "$FINAL_LOCATIONS_DIR" "20" \
    --instance_id "$INSTANCE_ID" \
    --output_dir "$PATCH_DIR"
echo "✅ Final patch generated in $PATCH_DIR"


echo -e "\n================================================="
echo "🎉 Repair pipeline finished for instance: $INSTANCE_ID"
echo "Find all logs and artifacts in: $RUN_DIR"
echo "=================================================" 