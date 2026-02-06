#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 02: Build Python wheel and sdist artifacts
set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"

cd "$BMK_PROJECT_DIR"

printf 'Building wheel/sdist via python -m build\n'
python3 -m build
