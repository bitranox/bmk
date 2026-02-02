#!/usr/bin/env bash
# Default test script - override by placing bmk_makescripts/test.sh in your project
#
# Usage: test.sh <project_dir> [extra_args...]
#
# This script coordinates test execution:
# 1. Runs test_01.sh, test_02.sh, ... SEQUENTIALLY (stops on first failure)
# 2. Runs test_parallel_01.sh, test_parallel_02.sh, ... IN PARALLEL
#
# All scripts receive the same arguments: <project_dir> [extra_args...]

set -uo pipefail

PROJECT_DIR="${1:-.}"
shift || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR" || { echo "Error: Cannot change to directory '$PROJECT_DIR'"; exit 1; }

# Temporary directory for parallel output capture
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

OVERALL_EXIT=0

# ─────────────────────────────────────────────────────────────────────────────
# SEQUENTIAL SCRIPTS: test_01.sh, test_02.sh, ...
# ─────────────────────────────────────────────────────────────────────────────

SEQUENTIAL_SCRIPTS=()
for script in "$SCRIPT_DIR"/test_[0-9][0-9]*.sh; do
    [[ -f "$script" ]] && SEQUENTIAL_SCRIPTS+=("$script")
done

if [[ ${#SEQUENTIAL_SCRIPTS[@]} -gt 0 ]]; then
    echo "═══════════════════════════════════════════════════════════════════════════════"
    echo "SEQUENTIAL TESTS (${#SEQUENTIAL_SCRIPTS[@]} scripts)"
    echo "═══════════════════════════════════════════════════════════════════════════════"
    echo ""

    for script in "${SEQUENTIAL_SCRIPTS[@]}"; do
        script_name="$(basename "$script")"
        echo "▶ Running: $script_name"
        echo "───────────────────────────────────────────────────────────────────────────────"

        if "$script" "$PROJECT_DIR" "$@"; then
            echo ""
            echo "  ✓ $script_name passed"
            echo ""
        else
            exit_code=$?
            echo ""
            echo "  ✗ $script_name FAILED (exit code: $exit_code)"
            echo ""
            echo "═══════════════════════════════════════════════════════════════════════════════"
            echo "STOPPED: Sequential test failed"
            echo "═══════════════════════════════════════════════════════════════════════════════"
            exit $exit_code
        fi
    done
fi

# ─────────────────────────────────────────────────────────────────────────────
# PARALLEL SCRIPTS: test_parallel_01.sh, test_parallel_02.sh, ...
# ─────────────────────────────────────────────────────────────────────────────

PARALLEL_SCRIPTS=()
for script in "$SCRIPT_DIR"/test_parallel_[0-9][0-9]*.sh; do
    [[ -f "$script" ]] && PARALLEL_SCRIPTS+=("$script")
done

if [[ ${#PARALLEL_SCRIPTS[@]} -gt 0 ]]; then
    echo "═══════════════════════════════════════════════════════════════════════════════"
    echo "PARALLEL TESTS (${#PARALLEL_SCRIPTS[@]} scripts)"
    echo "═══════════════════════════════════════════════════════════════════════════════"
    echo ""

    declare -A PIDS

    # Start all parallel scripts
    for script in "${PARALLEL_SCRIPTS[@]}"; do
        script_name="$(basename "$script")"
        output_file="$TEMP_DIR/${script_name}.out"
        exit_file="$TEMP_DIR/${script_name}.exit"

        {
            "$script" "$PROJECT_DIR" "$@" > "$output_file" 2>&1
            echo $? > "$exit_file"
        } &

        PIDS[$script_name]=$!
    done

    # Wait and collect results
    declare -A EXIT_CODES
    FAILED=()
    PASSED=()

    for script_name in "${!PIDS[@]}"; do
        pid="${PIDS[$script_name]}"
        wait "$pid" 2>/dev/null || true

        exit_file="$TEMP_DIR/${script_name}.exit"
        if [[ -f "$exit_file" ]]; then
            exit_code=$(cat "$exit_file")
        else
            exit_code=1
        fi

        EXIT_CODES[$script_name]=$exit_code

        if [[ "$exit_code" -eq 0 ]]; then
            PASSED+=("$script_name")
            echo "  ✓ $script_name"
        else
            FAILED+=("$script_name")
            echo "  ✗ $script_name (exit code: $exit_code)"
            OVERALL_EXIT=1
        fi
    done

    echo ""

    # Print output of failed parallel scripts
    if [[ ${#FAILED[@]} -gt 0 ]]; then
        echo "═══════════════════════════════════════════════════════════════════════════════"
        echo "FAILED PARALLEL TESTS OUTPUT:"
        echo "═══════════════════════════════════════════════════════════════════════════════"

        for script_name in "${FAILED[@]}"; do
            output_file="$TEMP_DIR/${script_name}.out"
            echo ""
            echo "───────────────────────────────────────────────────────────────────────────────"
            echo "[$script_name] (exit code: ${EXIT_CODES[$script_name]})"
            echo "───────────────────────────────────────────────────────────────────────────────"
            if [[ -f "$output_file" ]]; then
                cat "$output_file"
            else
                echo "(no output captured)"
            fi
        done
        echo ""
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

echo "═══════════════════════════════════════════════════════════════════════════════"
if [[ $OVERALL_EXIT -eq 0 ]]; then
    total=$((${#SEQUENTIAL_SCRIPTS[@]} + ${#PARALLEL_SCRIPTS[@]}))
    if [[ $total -eq 0 ]]; then
        echo "NO TEST SCRIPTS FOUND"
        echo "Create test_01.sh, test_02.sh, ... for sequential tests"
        echo "Create test_parallel_01.sh, test_parallel_02.sh, ... for parallel tests"
    else
        echo "ALL TESTS PASSED"
    fi
else
    echo "SOME TESTS FAILED"
fi
echo "═══════════════════════════════════════════════════════════════════════════════"

exit $OVERALL_EXIT
