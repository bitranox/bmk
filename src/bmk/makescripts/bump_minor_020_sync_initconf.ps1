# Stage 02: Sync __init__conf__.py version after minor bump

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}

Write-Host "Syncing __init__conf__.py version..."
$scriptDir = $PSScriptRoot
python3 "$scriptDir/_sync_initconf.py" --project-dir $env:BMK_PROJECT_DIR
