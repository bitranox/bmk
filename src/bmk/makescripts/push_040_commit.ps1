# Stage 04: Commit changes via stagerunner

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) { throw "BMK_PROJECT_DIR environment variable must be set" }
if (-not $env:BMK_STAGES_DIR) { throw "BMK_STAGES_DIR environment variable must be set" }

Write-Host "Committing changes..."

$env:BMK_COMMAND_PREFIX = "commit"
& "$env:BMK_STAGES_DIR\_btx_stagerunner.ps1" @args
exit $LASTEXITCODE
