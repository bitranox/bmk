# Stage 02: Create git tag and GitHub release

$ErrorActionPreference = "Stop"

python3 "$PSScriptRoot\_release.py" --project-dir $env:BMK_PROJECT_DIR $args
exit $LASTEXITCODE
