# Stage 02: Create git tag and GitHub release

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_resolve_python.ps1"

& $BMK_PYTHON_CMD "$PSScriptRoot\_release.py" --project-dir $env:BMK_PROJECT_DIR $args
exit $LASTEXITCODE
