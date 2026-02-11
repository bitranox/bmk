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
#   BMK_OVERRIDE_DIR   - Per-project override directory for stage scripts
#                        (default: $BMK_PROJECT_DIR/makescripts)
#                        If scripts matching the command prefix exist here,
#                        they replace the bundled scripts entirely for that command.
#   BMK_SHOW_WARNINGS  - Show warnings from passing parallel jobs (default: "1")
#                        Set to "0" to suppress warning output.
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

if ((BASH_VERSINFO[0] < 4)); then
    printf 'Error: bash 4+ required (found %s)\n' "$BASH_VERSION" >&2
    exit 1
fi

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
: "${BMK_COMMAND_PREFIX:?BMK_COMMAND_PREFIX environment variable must be set}"
export BMK_PROJECT_DIR BMK_COMMAND_PREFIX

# Default stages directory is the directory containing this script
BMK_STAGES_DIR="${BMK_STAGES_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
export BMK_STAGES_DIR

# Per-project override directory (checked before bundled stages)
BMK_OVERRIDE_DIR="${BMK_OVERRIDE_DIR:-${BMK_PROJECT_DIR}/makescripts}"
export BMK_OVERRIDE_DIR

TEMP_DIR=""
TOTAL_SCRIPTS=0
SCRIPT_ARGS=()  # Arguments to forward to child scripts
FAILED_SCRIPTS=()  # Track failed script names across stages

# ANSI color codes
COLOR_GREEN='\033[32m'
COLOR_RED='\033[31m'
COLOR_YELLOW='\033[33m'
COLOR_RESET='\033[0m'

die() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

resolve_stages_dir() {
    # If the override directory contains scripts matching the command prefix,
    # use it exclusively instead of the bundled stages directory.
    local -a override_scripts
    override_scripts=("${BMK_OVERRIDE_DIR}/${BMK_COMMAND_PREFIX}_"[0-9]*_*.sh)

    # Check if the glob expanded to at least one real file
    if [[ -f "${override_scripts[0]:-}" ]]; then
        BMK_STAGES_DIR="$BMK_OVERRIDE_DIR"
        export BMK_STAGES_DIR
    fi
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
    trap 'cleanup_on_signal 2' INT
    trap 'cleanup_on_signal 15' TERM
}

cleanup_on_signal() {
    local sig="$1"
    # Kill background jobs spawned by parallel stages
    kill 0 2>/dev/null || true
    wait 2>/dev/null || true
    # Temp dir cleanup handled by EXIT trap
    exit "$((128 + sig))"
}

extract_stage_number() {
    # Usage: extract_stage_number "test_01_foo.sh" -> "1"
    # Pattern: {prefix}_N+_*.sh where N+ is 2-6 digits, returned as integer
    local script_name="$1"
    local stage
    # Escape sed regex metacharacters in the prefix for safe interpolation
    local safe_prefix
    safe_prefix=$(printf '%s' "$BMK_COMMAND_PREFIX" | sed 's/[.[\/*^$\\]/\\&/g')
    stage=$(printf '%s\n' "$script_name" | sed -n "s/^${safe_prefix}_\\([0-9]\\{2,6\\}\\)_.*\\.sh\$/\\1/p")
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

run_single_script() {
    # Runs a single script with output directly to console
    local stage="$1"
    local script="$2"
    local script_name exit_code

    script_name="$(basename "$script")"

    TOTAL_SCRIPTS=$((TOTAL_SCRIPTS + 1))

    # Run script directly, output goes to console
    "$script" "${SCRIPT_ARGS[@]}"
    exit_code=$?

    if [[ "$exit_code" -eq 0 ]]; then
        printf "${COLOR_GREEN}  ✓ %s${COLOR_RESET}\n" "$script_name"
        return 0
    else
        FAILED_SCRIPTS+=("${script_name}:${exit_code}")
        return "$exit_code"
    fi
}

print_warnings_from_passed() {
    local -a passed_names=("$@")
    local show_warnings="${BMK_SHOW_WARNINGS:-1}"

    [[ "$show_warnings" == "0" ]] && return 0
    [[ ${#passed_names[@]} -eq 0 ]] && return 0

    local found_any=false
    local script_name output_file warnings

    for script_name in "${passed_names[@]}"; do
        output_file="$TEMP_DIR/${script_name}.out"
        [[ -f "$output_file" ]] || continue

        warnings=$(grep -i 'warning' "$output_file" 2>/dev/null \
            | grep -v -E '[0-9]+ warnings?' \
            || true)
        [[ -z "$warnings" ]] && continue

        if [[ "$found_any" == false ]]; then
            printf '\n'
            found_any=true
        fi

        printf "${COLOR_YELLOW}  ⚠ %s warnings:${COLOR_RESET}\n" "$script_name"
        while IFS= read -r line; do
            printf "${COLOR_YELLOW}    %s${COLOR_RESET}\n" "$line"
        done <<< "$warnings"
    done

    [[ "$found_any" == true ]] && printf '\n'
    return 0
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

    # Build ordered name list and announce parallel execution
    local -a script_names=()
    local -a friendly_names=()
    local friendly joined
    for script in "${scripts[@]}"; do
        script_name="$(basename "$script")"
        script_names+=("$script_name")
        friendly="${script_name#${BMK_COMMAND_PREFIX}_}"
        friendly="${friendly#[0-9]*_}"
        friendly="${friendly%.sh}"
        friendly_names+=("$friendly")
    done
    joined=$(IFS=', '; printf '%s' "${friendly_names[*]}")
    printf '  ▶ running %d tasks in parallel: %s\n' "${#scripts[@]}" "$joined"

    # Start all scripts in parallel
    for script in "${scripts[@]}"; do
        script_name="$(basename "$script")"
        output_file="$TEMP_DIR/${script_name}.out"
        exit_file="$TEMP_DIR/${script_name}.exit"

        {
            "$script" "${SCRIPT_ARGS[@]}" > "$output_file" 2>&1
            printf '%s\n' "$?" > "$exit_file"
        } &

        pids[$script_name]=$!
    done

    # Wait for ALL jobs to complete before printing results
    for script_name in "${script_names[@]}"; do
        pid="${pids[$script_name]}"
        wait "$pid" 2> /dev/null || true

        exit_file="$TEMP_DIR/${script_name}.exit"
        if [[ -f "$exit_file" ]]; then
            exit_code=$(cat "$exit_file")
            exit_code="${exit_code:-1}"
        else
            exit_code=1
        fi

        exit_codes[$script_name]=$exit_code

        if [[ "$exit_code" -eq 0 ]]; then
            passed+=("$script_name")
        else
            failed+=("$script_name")
        fi
    done

    # Print all results together
    for script_name in "${script_names[@]}"; do
        exit_code="${exit_codes[$script_name]}"
        if [[ "$exit_code" -eq 0 ]]; then
            printf "${COLOR_GREEN}  ✓ %s${COLOR_RESET}\n" "$script_name"
        else
            printf "${COLOR_RED}  ✗ %s (exit code: %s)${COLOR_RESET}\n" "$script_name" "$exit_code"
        fi
    done

    # Show warnings from passed scripts
    print_warnings_from_passed "${passed[@]}"

    # Print output of failed scripts
    if [[ ${#failed[@]} -gt 0 ]]; then
        local first_failure_code=""
        for script_name in "${failed[@]}"; do
            local ecode="${exit_codes[$script_name]}"
            FAILED_SCRIPTS+=("${script_name}:${ecode}")
            [[ -z "$first_failure_code" ]] && first_failure_code="$ecode"
            output_file="$TEMP_DIR/${script_name}.out"
            printf '\n'
            printf "${COLOR_RED}[%s] (exit code: %s)${COLOR_RESET}\n" "$script_name" "$ecode"
            if [[ -f "$output_file" ]]; then
                cat "$output_file"
            else
                printf '(no output captured)\n'
            fi
        done
        printf '\n'
        return "${first_failure_code:-1}"
    fi

    return 0
}

run() {
    cd "$BMK_PROJECT_DIR" || die "Cannot change to directory '$BMK_PROJECT_DIR'"
    resolve_stages_dir
    derive_package_name
    setup_temp_dir

    local -a stages=()
    while IFS= read -r stage; do
        [[ -n "$stage" ]] && stages+=("$stage")
    done < <(discover_stages)

    if [[ ${#stages[@]} -eq 0 ]]; then
        printf 'No scripts found for %s. ' "$BMK_COMMAND_PREFIX"
        printf 'Create %s_NN_*.sh scripts where NN is a two-digit stage number.\n' "$BMK_COMMAND_PREFIX"
        exit 0
    fi

    # Run each stage sequentially; within each stage, scripts run in parallel
    for stage in "${stages[@]}"; do
        if ! run_stage_parallel "$stage"; then
            local first_code="${FAILED_SCRIPTS[0]#*:}"
            for entry in "${FAILED_SCRIPTS[@]}"; do
                local sname="${entry%%:*}"
                local scode="${entry#*:}"
                printf "${COLOR_RED}  ✗ %s (exit code: %s)${COLOR_RESET}\n" "$sname" "$scode"
            done
            exit "${first_code:-1}"
        fi
    done
}

SCRIPT_ARGS=("$@")
run
