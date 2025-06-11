#!/bin/bash
set -e

# Enable debug output if DEBUG env is set
if [[ "$DEBUG" == "1" ]]; then
  set -x
fi

# --- Environment and Proxy Setup ---
# Add the project root to PYTHONPATH to solve module import issues without using -m.
export PYTHONPATH=$(pwd)

# Set proxy if needed, and ensure localhost is excluded for Neo4j connection.
export http_proxy=http://172.27.16.1:7890
export https_proxy=http://172.27.16.1:7890
unset all_proxy

# --- Configuration ---
INSTANCE_ID=$1
MODEL_NAME="deepseek" # Hardcoded to deepseek
TEMPERATURE=${TEMPERATURE:-0.3}

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
REPOS_DIR="./playground" # Store all cloned repos inside the project's playground directory
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
RUN_DIR="tests/${INSTANCE_ID}_${MODEL_NAME}"
REPAIR_MODEL_NAME="${MODEL_NAME}_0" # Default repair config

# --- Directories for this run ---
mkdir -p "$RUN_DIR"
KG_LOCATIONS_DIR="${RUN_DIR}/kg_locations"
LLM_LOCATIONS_DIR="${RUN_DIR}/llm_locations"
FINAL_LOCATIONS_DIR="${RUN_DIR}/final_locations"
PATCH_DIR="${RUN_DIR}/patches"
LOG_FILE="${RUN_DIR}/run.log"

mkdir -p "$KG_LOCATIONS_DIR" "$LLM_LOCATIONS_DIR" "$FINAL_LOCATIONS_DIR" "$PATCH_DIR"


echo "================================================="
echo "Starting KGCompass repair for instance: $INSTANCE_ID"
echo "Run directory: $RUN_DIR"
echo "================================================="

# --- Prerequisites check ---
# In a Docker Compose environment, the app container should connect to the neo4j service name.
# We will rely on docker-compose's `depends_on` to ensure Neo4j is ready.
# The check is removed to avoid dependency on 'nc' and issues with hostname resolution.
# if ! nc -z ${NEO4J_HOST:-"localhost"} 7687; then
#   echo "ERROR: Cannot connect to Neo4j at ${NEO4J_HOST:-"localhost"}:7687." >&2
#   exit 1
# fi
echo "✅ Assuming Neo4j connection is available via Docker Compose network."

# --- Pipeline Steps ---

# Step 1: Knowledge Graph-based Bug Location
echo -e "\n--- Step 1: KG-based Bug Location ---"
KG_RESULT_FILE="${KG_LOCATIONS_DIR}/${INSTANCE_ID}.json"
if [ -f "$KG_RESULT_FILE" ]; then
    echo "✅ KG location file already exists, skipping."
else
    # Assumes fl.py writes its output to a JSON file.
    python3 kgcompass/fl.py "$INSTANCE_ID" "$REPO_IDENTIFIER" "$KG_LOCATIONS_DIR"
    echo "✅ KG location saved to $KG_RESULT_FILE"
fi

# Step 2: LLM-based Bug Location
echo -e "\n--- Step 2: LLM-based Bug Location ---"
LLM_RESULT_FILE="${LLM_LOCATIONS_DIR}/${INSTANCE_ID}.json"
if [ -f "$LLM_RESULT_FILE" ]; then
    echo "✅ LLM location file already exists, skipping."
else
    # Assumes llm_loc.py can take --instance_id to process a single instance.
    python3 kgcompass/llm_loc.py "$LLM_LOCATIONS_DIR" --instance_id "$INSTANCE_ID"
    echo "✅ LLM location saved to $LLM_RESULT_FILE"
    echo "--- Generated LLM Location File ---"
    ls -l "$LLM_RESULT_FILE"
fi

# Step 3: Fix/Merge Bug Location
echo -e "\n--- Step 3: Merge and Fix Bug Locations for $INSTANCE_ID ---"
FINAL_RESULT_FILE="${FINAL_LOCATIONS_DIR}/${INSTANCE_ID}.json"
if [ -f "$FINAL_RESULT_FILE" ]; then
    echo "✅ Final location file already exists, skipping."
else
    # Assumes fix_fl_line.py is adapted to work on single instances from specific dirs.
    python3 kgcompass/fix_fl_line.py "$LLM_LOCATIONS_DIR" "$FINAL_LOCATIONS_DIR" --instance_id "$INSTANCE_ID"
    echo "✅ Final location saved to $FINAL_RESULT_FILE"
fi

# Step 4: Final Patch Generation
echo -e "\n--- Step 4: Final Patch Generation ---"
# Note: The patch file name is determined inside repair.py, we check for its existence.
PATCH_FILE="${PATCH_DIR}/${INSTANCE_ID}.patch"
if [ -f "$PATCH_FILE" ]; then
    echo "✅ Final patch file already exists, skipping."
else
    # Assumes repair.py uses the final location file to generate the patch.
    # Arguments have been corrected to match the updated repair.py script.
    python3 kgcompass/repair.py "$FINAL_LOCATIONS_DIR" \
        --instance_id "$INSTANCE_ID" \
        --playground_dir "$REPOS_DIR" \
        --repo_identifier "$REPO_IDENTIFIER"
    echo "✅ Final patch generation step executed."
    echo "--- Generated Patch File ---"
    ls -l "$PATCH_FILE"
fi


echo -e "\n================================================="
echo "🎉 Repair pipeline finished for instance: $INSTANCE_ID"
echo "Find all logs and artifacts in: $RUN_DIR"
echo "=================================================" 