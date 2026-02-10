# Stage 05: Clean build artifacts and cache directories
# Runs after tests to clean up generated files

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) { throw "BMK_PROJECT_DIR environment variable must be set" }
if (-not $env:BMK_STAGES_DIR) { throw "BMK_STAGES_DIR environment variable must be set" }

$env:BMK_COMMAND_PREFIX = "clean"
& "$env:BMK_STAGES_DIR\_btx_stagerunner.ps1" @args
exit $LASTEXITCODE
