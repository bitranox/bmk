# Stage 02: Clean build artifacts after coverage
$ErrorActionPreference = "Stop"
python3 "$PSScriptRoot\_clean.py" --project-dir $env:BMK_PROJECT_DIR
