# Stage 02: Build artifacts (runs parallel with test)

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) { throw "BMK_PROJECT_DIR environment variable must be set" }
if (-not $env:BMK_STAGES_DIR) { throw "BMK_STAGES_DIR environment variable must be set" }

Write-Host "push_020_build -> bld pipeline"
$savedPrefix = $env:BMK_COMMAND_PREFIX
$env:BMK_COMMAND_PREFIX = "bld"
& "$env:BMK_STAGES_DIR\_btx_stagerunner.ps1" @args
$stageExitCode = $LASTEXITCODE
$env:BMK_COMMAND_PREFIX = $savedPrefix
exit $stageExitCode
