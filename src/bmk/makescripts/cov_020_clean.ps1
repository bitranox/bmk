#Requires -Version 7.0
# Stage 02: Clean build artifacts after coverage
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_resolve_python.ps1"
& $BMK_PYTHON_CMD "$PSScriptRoot\_clean.py" --project-dir $env:BMK_PROJECT_DIR
