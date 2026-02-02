# Stage 01: Clean build artifacts and cache directories
$ErrorActionPreference = "Stop"
python3 "$PSScriptRoot\_clean.py" --project-dir $env:BMK_PROJECT_DIR
