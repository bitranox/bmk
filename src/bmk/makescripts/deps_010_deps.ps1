# Stage 01: Check project dependencies against PyPI
$ErrorActionPreference = "Stop"
python3 "$PSScriptRoot\_dependencies.py" --project-dir $env:BMK_PROJECT_DIR $args
