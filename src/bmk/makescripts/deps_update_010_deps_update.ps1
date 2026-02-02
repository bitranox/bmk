# Stage 01: Update outdated dependencies to latest versions
$ErrorActionPreference = "Stop"
python3 "$PSScriptRoot\_dependencies.py" --update --project-dir $env:BMK_PROJECT_DIR
