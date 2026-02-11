# Stage 01: Clean build artifacts and cache directories
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_resolve_python.ps1"
& $BMK_PYTHON_CMD "$PSScriptRoot\_clean.py" --project-dir $env:BMK_PROJECT_DIR $args
