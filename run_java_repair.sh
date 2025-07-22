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
  echo "Example: $0 google__gson-1787"
  exit 1
fi

# --- Java Repository Cloning ---
declare -A JAVA_REPO_URL_MAP
JAVA_REPO_URL_MAP["google__gson"]="https://github.com/google/gson.git"
JAVA_REPO_URL_MAP["fasterxml__jackson-databind"]="https://github.com/FasterXML/jackson-databind.git"
JAVA_REPO_URL_MAP["fasterxml__jackson-core"]="https://github.com/FasterXML/jackson-core.git"
JAVA_REPO_URL_MAP["fasterxml__jackson-dataformat-xml"]="https://github.com/FasterXML/jackson-dataformat-xml.git"
JAVA_REPO_URL_MAP["mockito__mockito"]="https://github.com/mockito/mockito.git"
JAVA_REPO_URL_MAP["apache__dubbo"]="https://github.com/apache/dubbo.git"
JAVA_REPO_URL_MAP["elastic__logstash"]="https://github.com/elastic/logstash.git"
JAVA_REPO_URL_MAP["alibaba__fastjson2"]="https://github.com/alibaba/fastjson2.git"
JAVA_REPO_URL_MAP["googlecontainertools__jib"]="https://github.com/GoogleContainerTools/jib.git"

REPO_IDENTIFIER=${INSTANCE_ID%-*}
CLONE_URL=${JAVA_REPO_URL_MAP[$REPO_IDENTIFIER]}
REPOS_DIR="./playground" # Store all cloned repos inside the project's playground directory
REPO_PATH="${REPOS_DIR}/${REPO_IDENTIFIER}"

if [ -z "$CLONE_URL" ]; then
  echo "ERROR: Java repository for '$REPO_IDENTIFIER' not found in the script's map." >&2
  echo "Supported Java repositories: ${!JAVA_REPO_URL_MAP[@]}" >&2
  exit 1
fi

if [ ! -d "$REPO_PATH" ]; then
  echo "--- Java Repository '$REPO_IDENTIFIER' not found. Cloning... ---"
  mkdir -p "$REPOS_DIR"
  git clone "$CLONE_URL" "$REPO_PATH"
  echo "✅ Java Repository cloned to $REPO_PATH"
else
  echo "✅ Java Repository '$REPO_IDENTIFIER' already exists at $REPO_PATH."
fi

# --- Derived variables ---
RUN_DIR="tests_java/${INSTANCE_ID}_${MODEL_NAME}"
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
echo "Starting KGCompass Java repair for instance: $INSTANCE_ID"
echo "Repository: $REPO_IDENTIFIER"
echo "Run directory: $RUN_DIR"
echo "================================================="

# --- Prerequisites check ---
echo "✅ Assuming Neo4j connection is available."

# --- Pipeline Steps ---

# Step 1: Knowledge Graph-based Bug Location (Java-specific)
echo -e "\n--- Step 1: Java KG-based Bug Location ---"
KG_RESULT_FILE="${KG_LOCATIONS_DIR}/${INSTANCE_ID}.json"

# Check if KG file already exists in java_kg_results
EXISTING_KG_FILE="java_kg_results/${REPO_IDENTIFIER}/${INSTANCE_ID}.json"
if [ -f "$EXISTING_KG_FILE" ]; then
    echo "✅ Found existing KG file, copying to run directory..."
    cp "$EXISTING_KG_FILE" "$KG_RESULT_FILE"
    echo "✅ KG location copied from $EXISTING_KG_FILE"
elif [ -f "$KG_RESULT_FILE" ]; then
    echo "✅ KG location file already exists in run directory, skipping."
else
    echo "--- Generating KG location for Java instance ---"
    # Use multi-swe-bench benchmark for Java instances
    python3 kgcompass/fl.py "$INSTANCE_ID" "$REPO_IDENTIFIER" "$KG_LOCATIONS_DIR" "multi-swe-bench"
    echo "✅ Java KG location saved to $KG_RESULT_FILE"
fi

# Step 2: LLM-based Bug Location (Java-specific)
echo -e "\n--- Step 2: Java LLM-based Bug Location ---"
LLM_RESULT_FILE="${LLM_LOCATIONS_DIR}/${INSTANCE_ID}.json"
if [ -f "$LLM_RESULT_FILE" ]; then
    echo "✅ LLM location file already exists, skipping."
else
    echo "--- Generating LLM location for Java instance ---"
    # Use instance_id parameter to process single Java instance
    python3 kgcompass/llm_loc.py "$LLM_LOCATIONS_DIR" --instance_id "$INSTANCE_ID" --benchmark "multi-swe-bench"
    echo "✅ Java LLM location saved to $LLM_RESULT_FILE"
    echo "--- Generated LLM Location File ---"
    ls -l "$LLM_RESULT_FILE"
fi

# Step 3: Fix/Merge Bug Location (Java-specific)
echo -e "\n--- Step 3: Merge and Fix Java Bug Locations for $INSTANCE_ID ---"
FINAL_RESULT_FILE="${FINAL_LOCATIONS_DIR}/${INSTANCE_ID}.json"
if [ -f "$FINAL_RESULT_FILE" ]; then
    echo "✅ Final location file already exists, skipping."
else
    echo "--- Merging and fixing Java bug locations ---"
    # Process single Java instance
    python3 kgcompass/fix_fl_line.py "$LLM_LOCATIONS_DIR" "$FINAL_LOCATIONS_DIR" --instance_id "$INSTANCE_ID" --benchmark "multi-swe-bench"
    echo "✅ Java final location saved to $FINAL_RESULT_FILE"
fi

# Step 4: Final Patch Generation (Java-specific)
echo -e "\n--- Step 4: Java Final Patch Generation ---"
PATCH_FILE="${PATCH_DIR}/${INSTANCE_ID}.patch"
if [ -f "$PATCH_FILE" ]; then
    echo "✅ Final patch file already exists, skipping."
else
    echo "--- Generating patch for Java instance ---"
    # Generate patch using final location file for Java
    python3 kgcompass/repair.py "$FINAL_LOCATIONS_DIR" \
        --instance_id "$INSTANCE_ID" \
        --playground_dir "$REPOS_DIR" \
        --repo_identifier "$REPO_IDENTIFIER" \
        --benchmark "multi-swe-bench"
    echo "✅ Java final patch generation step executed."
    echo "--- Generated Patch File ---"
    if [ -f "$PATCH_FILE" ]; then
        ls -l "$PATCH_FILE"
        echo "--- Patch Content Preview ---"
        head -20 "$PATCH_FILE"
    else
        echo "⚠️  Patch file not found, check logs for errors."
    fi
fi

echo -e "\n================================================="
echo "🎉 Java repair pipeline finished for instance: $INSTANCE_ID"
echo "Repository: $REPO_IDENTIFIER"
echo "Find all logs and artifacts in: $RUN_DIR"
echo "=================================================" 