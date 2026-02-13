#Requires -Version 7.0
# Stage 01: Check project dependencies against PyPI
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_resolve_python.ps1"
& $BMK_PYTHON_CMD "$PSScriptRoot\_dependencies.py" --project-dir $env:BMK_PROJECT_DIR $args
