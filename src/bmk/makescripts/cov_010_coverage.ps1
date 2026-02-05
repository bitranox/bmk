# Stage 01: Run tests with coverage and upload to Codecov
$ErrorActionPreference = "Stop"
python3 "$PSScriptRoot\_coverage.py" --run --project-dir $env:BMK_PROJECT_DIR
