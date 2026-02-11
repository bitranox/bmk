# Stage 01: Update dependencies before push

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) { throw "BMK_PROJECT_DIR environment variable must be set" }
if (-not $env:BMK_STAGES_DIR) { throw "BMK_STAGES_DIR environment variable must be set" }

Write-Host "push_010_update_deps -> deps pipeline"
$savedPrefix = $env:BMK_COMMAND_PREFIX
$env:BMK_COMMAND_PREFIX = "deps"
& "$env:BMK_STAGES_DIR\_btx_stagerunner.ps1" --update @args
$stageExitCode = $LASTEXITCODE
$env:BMK_COMMAND_PREFIX = $savedPrefix
exit $stageExitCode
