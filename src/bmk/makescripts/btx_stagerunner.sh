#!/usr/bin/env bash
# shellcheck shell=bash
# Generic staged command runner - executes scripts in staged parallel batches
#
# Required environment variables (set by Python CLI):
#   BMK_PROJECT_DIR    - Path to the project directory
#   BMK_COMMAND_PREFIX - Command prefix to match (e.g., "test", "build", "deploy")
#
# Optional environment variables:
#   BMK_STAGES_DIR     - Directory containing stage scripts (default: directory of this script)
#
# This script coordinates execution in STAGED PARALLEL BATCHES:
# - Stage 01: Run all {prefix}_01_*.sh in parallel, wait for all to complete
# - Stage 02: Run all {prefix}_02_*.sh in parallel, wait for all to complete
# - Continue for each stage found
#
# Behavior: Fail-fast BETWEEN stages, parallel WITHIN each stage.
# Single-script stages run with output directly to console.

set -Eeu -o pipefail
IFS=$'\n\t'

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
: "${BMK_COMMAND_PREFIX:?BMK_COMMAND_PREFIX environment variable must be set}"
export BMK_PROJECT_DIR BMK_COMMAND_PREFIX

# Default stages directory is the directory containing this script
BMK_STAGES_DIR="${BMK_STAGES_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
export BMK_STAGES_DIR

TEMP_DIR=""
TOTAL_SCRIPTS=0

# ═══════════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════════

die() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

explain_exit_code() {
    local code=$1
    case $code in
        0) ;;
        1) printf 'Exit code 1: One or more stages failed\n' >&2 ;;
        *) printf 'Exit code %d: unknown\n' "$code" >&2 ;;
    esac
}

derive_package_name() {
    # Derive BMK_PACKAGE_NAME from pyproject.toml if not already set
    # Uses Python to parse TOML and extract the import package name
    if [[ -n "${BMK_PACKAGE_NAME:-}" ]]; then
        export BMK_PACKAGE_NAME
        return 0
    fi

    local pyproject_path="${BMK_PROJECT_DIR}/pyproject.toml"

    if [[ ! -f "$pyproject_path" ]]; then
        die "pyproject.toml not found in ${BMK_PROJECT_DIR}"
    fi

    BMK_PACKAGE_NAME=$(python3 -c '
import sys
import rtoml
from pathlib import Path

pyproject_path = Path(sys.argv[1])
with pyproject_path.open("r", encoding="utf-8") as f:
    data = rtoml.load(f)

# Try to derive import package from hatch wheel packages
tool = data.get("tool", {})
hatch = tool.get("hatch", {})
build = hatch.get("build", {})
targets = build.get("targets", {})
wheel = targets.get("wheel", {})
packages = wheel.get("packages", [])

if packages:
    print(Path(packages[0]).name)
    sys.exit(0)

# Try to derive from project.scripts entry points
project = data.get("project", {})
scripts = project.get("scripts", {})

for spec in scripts.values():
    if ":" in spec:
        module = spec.split(":", 1)[0]
        print(module.split(".", 1)[0])
        sys.exit(0)

# Fallback to project name with hyphens replaced by underscores
name = project.get("name", "")
if name:
    print(name.replace("-", "_"))
    sys.exit(0)

sys.exit(1)
' "$pyproject_path") || die "Failed to derive package name from pyproject.toml"

    export BMK_PACKAGE_NAME
}

setup_temp_dir() {
    TEMP_DIR=$(mktemp -d)
    trap 'rm -rf "$TEMP_DIR"' EXIT
}

extract_stage_number() {
    # Usage: extract_stage_number "test_01_foo.sh" -> "1"
    # Pattern: {prefix}_N+_*.sh where N+ is 2-6 digits, returned as integer
    local script_name="$1"
    local stage
    stage=$(printf '%s\n' "$script_name" | sed -n "s/^${BMK_COMMAND_PREFIX}_\\([0-9]\\{2,6\\}\\)_.*\\.sh\$/\\1/p")
    # Remove leading zeros to get integer value
    [[ -n "$stage" ]] && printf '%d\n' "$((10#$stage))"
}

discover_stages() {
    # Prints unique stage numbers found in {prefix}_N+_*.sh scripts, sorted numerically
    local stage
    for script in "${BMK_STAGES_DIR}/${BMK_COMMAND_PREFIX}_"[0-9]*_*.sh; do
        [[ -f "$script" ]] || continue
        stage=$(extract_stage_number "$(basename "$script")")
        [[ -n "$stage" ]] && printf '%s\n' "$stage"
    done | sort -n -u
}

gather_scripts_for_stage() {
    # Usage: gather_scripts_for_stage "1" -> prints script paths matching stage 1
    # Matches any zero-padded version: 01, 001, 0001, etc.
    local stage="$1"
    local script script_stage
    for script in "${BMK_STAGES_DIR}/${BMK_COMMAND_PREFIX}_"[0-9]*_*.sh; do
        [[ -f "$script" ]] || continue
        script_stage=$(extract_stage_number "$(basename "$script")")
        [[ "$script_stage" == "$stage" ]] && printf '%s\n' "$script"
    done
}

print_header() {
    local title="$1"
    printf '═══════════════════════════════════════════════════════════════════════════════\n'
    printf '%s\n' "$title"
    printf '═══════════════════════════════════════════════════════════════════════════════\n'
}

print_separator() {
    printf '───────────────────────────────────────────────────────────────────────────────\n'
}

run_single_script() {
    # Runs a single script with output directly to console
    local stage="$1"
    local script="$2"
    local script_name exit_code

    script_name="$(basename "$script")"

    TOTAL_SCRIPTS=$((TOTAL_SCRIPTS + 1))

    printf '\n'
    print_header "${BMK_COMMAND_PREFIX^^} STAGE $stage: $script_name"
    printf '\n'

    # Run script directly, output goes to console
    "$script"
    exit_code=$?

    printf '\n'

    if [[ "$exit_code" -eq 0 ]]; then
        printf '  ✓ %s\n\n' "$script_name"
        return 0
    else
        printf '  ✗ %s (exit code: %s)\n\n' "$script_name" "$exit_code"
        return 1
    fi
}

run_stage_parallel() {
    # Runs all scripts for a stage in parallel, returns 0 if all pass
    local stage="$1"
    local -a scripts=()
    local -A pids=()
    local -A exit_codes=()
    local -a failed=()
    local -a passed=()
    local script script_name output_file exit_file pid exit_code

    # Gather scripts for this stage
    while IFS= read -r script; do
        scripts+=("$script")
    done < <(gather_scripts_for_stage "$stage")

    [[ ${#scripts[@]} -eq 0 ]] && return 0

    # If only one script, run it directly with output to console
    if [[ ${#scripts[@]} -eq 1 ]]; then
        run_single_script "$stage" "${scripts[0]}"
        return $?
    fi

    TOTAL_SCRIPTS=$((TOTAL_SCRIPTS + ${#scripts[@]}))

    printf '\n'
    print_header "${BMK_COMMAND_PREFIX^^} STAGE $stage (${#scripts[@]} scripts in parallel)"
    printf '\n'

    # Start all scripts in parallel
    for script in "${scripts[@]}"; do
        script_name="$(basename "$script")"
        output_file="$TEMP_DIR/${script_name}.out"
        exit_file="$TEMP_DIR/${script_name}.exit"

        {
            "$script" > "$output_file" 2>&1
            printf '%s\n' "$?" > "$exit_file"
        } &

        pids[$script_name]=$!
    done

    # Wait and collect results
    for script_name in "${!pids[@]}"; do
        pid="${pids[$script_name]}"
        wait "$pid" 2> /dev/null || true

        exit_file="$TEMP_DIR/${script_name}.exit"
        if [[ -f "$exit_file" ]]; then
            exit_code=$(cat "$exit_file")
        else
            exit_code=1
        fi

        exit_codes[$script_name]=$exit_code

        if [[ "$exit_code" -eq 0 ]]; then
            passed+=("$script_name")
            printf '  ✓ %s\n' "$script_name"
        else
            failed+=("$script_name")
            printf '  ✗ %s (exit code: %s)\n' "$script_name" "$exit_code"
        fi
    done

    printf '\n'

    # Print output of failed scripts
    if [[ ${#failed[@]} -gt 0 ]]; then
        print_header "FAILED ${BMK_COMMAND_PREFIX^^} OUTPUT (Stage $stage)"

        for script_name in "${failed[@]}"; do
            output_file="$TEMP_DIR/${script_name}.out"
            printf '\n'
            print_separator
            printf '[%s] (exit code: %s)\n' "$script_name" "${exit_codes[$script_name]}"
            print_separator
            if [[ -f "$output_file" ]]; then
                cat "$output_file"
            else
                printf '(no output captured)\n'
            fi
        done
        printf '\n'
        return 1
    fi

    return 0
}

print_no_scripts_message() {
    print_header "NO SCRIPTS FOUND FOR '${BMK_COMMAND_PREFIX}'"
    printf 'Create %s_NN_*.sh scripts where NN is a two-digit stage number.\n' "$BMK_COMMAND_PREFIX"
    printf 'Example: %s_01_step1.sh, %s_01_step2.sh, %s_02_final.sh\n' "$BMK_COMMAND_PREFIX" "$BMK_COMMAND_PREFIX" "$BMK_COMMAND_PREFIX"
    printf '\n'
    printf 'Scripts within the same stage run in parallel.\n'
    printf 'Stages run sequentially (stage 02 waits for stage 01 to complete).\n'
}

run() {
    cd "$BMK_PROJECT_DIR" || die "Cannot change to directory '$BMK_PROJECT_DIR'"
    derive_package_name
    setup_temp_dir

    local -a stages=()
    while IFS= read -r stage; do
        [[ -n "$stage" ]] && stages+=("$stage")
    done < <(discover_stages)

    if [[ ${#stages[@]} -eq 0 ]]; then
        print_no_scripts_message
        exit 0
    fi

    # Run each stage sequentially; within each stage, scripts run in parallel
    for stage in "${stages[@]}"; do
        if ! run_stage_parallel "$stage"; then
            print_header "STOPPED: ${BMK_COMMAND_PREFIX^^} stage $stage failed"
            explain_exit_code 1
            exit 1
        fi
    done

    # Summary
    print_header "ALL ${BMK_COMMAND_PREFIX^^} SCRIPTS PASSED ($TOTAL_SCRIPTS scripts)"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

run
