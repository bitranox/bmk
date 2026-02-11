# Stage 01: Update outdated dependencies to latest versions
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_resolve_python.ps1"
& $BMK_PYTHON_CMD "$PSScriptRoot\_dependencies.py" --update --project-dir $env:BMK_PROJECT_DIR
