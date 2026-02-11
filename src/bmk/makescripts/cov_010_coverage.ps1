# Stage 01: Run tests with coverage and upload to Codecov
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_resolve_python.ps1"
& $BMK_PYTHON_CMD "$PSScriptRoot\_coverage.py" --run --project-dir $env:BMK_PROJECT_DIR
