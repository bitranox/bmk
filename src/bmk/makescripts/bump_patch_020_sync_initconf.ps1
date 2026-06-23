#Requires -Version 7.0
# Stage 02: Sync __init__conf__.py version after patch bump

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_resolve_python.ps1"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}

Write-Output "Syncing __init__conf__.py version..."
$scriptDir = $PSScriptRoot
& $BMK_PYTHON_CMD "$scriptDir/_sync_initconf.py" --project-dir $env:BMK_PROJECT_DIR
