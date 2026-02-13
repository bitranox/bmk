#Requires -Version 7.0
# Stage 900: Clean build artifacts and cache directories
# Runs after tests to clean up generated files

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) { throw "BMK_PROJECT_DIR environment variable must be set" }
if (-not $env:BMK_STAGES_DIR) { throw "BMK_STAGES_DIR environment variable must be set" }

Write-Output "test_900_clean -> clean pipeline"
$savedPrefix = $env:BMK_COMMAND_PREFIX
$env:BMK_COMMAND_PREFIX = "clean"
& "$env:BMK_STAGES_DIR\_btx_stagerunner.ps1" @args
$stageExitCode = $LASTEXITCODE
$env:BMK_COMMAND_PREFIX = $savedPrefix
exit $stageExitCode
