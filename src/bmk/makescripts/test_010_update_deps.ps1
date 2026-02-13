#Requires -Version 7.0
# Stage 01: Update outdated dependencies
# Runs first to ensure pyproject.toml is up-to-date before other checks

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}
if (-not $env:BMK_STAGES_DIR) {
    throw "BMK_STAGES_DIR environment variable must be set"
}

Write-Output "test_010_update_deps -> deps_update pipeline"
$savedPrefix = $env:BMK_COMMAND_PREFIX
$env:BMK_COMMAND_PREFIX = "deps_update"
& "$env:BMK_STAGES_DIR\_btx_stagerunner.ps1" @args
$stageExitCode = $LASTEXITCODE
$env:BMK_COMMAND_PREFIX = $savedPrefix
exit $stageExitCode
