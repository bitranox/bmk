#Requires -Version 7.0
# Stage 05: Git push to remote

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}

Set-Location $env:BMK_PROJECT_DIR

# Configuration: remote and branch
$gitRemote = $env:BMK_GIT_REMOTE ? $env:BMK_GIT_REMOTE : "origin"
$gitBranch = $env:BMK_GIT_BRANCH ? $env:BMK_GIT_BRANCH : (git rev-parse --abbrev-ref HEAD)

function Write-ExitCodeError {
    param([int]$Code)
    switch ($Code) {
        0 { }
        1 { Write-Error "Exit code 1: Push failed" }
        128 { Write-Error "Exit code 128: Fatal git error" }
        129 { Write-Error "Exit code 129: Git usage error" }
        default { Write-Error "Exit code ${Code}: unknown" }
    }
}

# Push to remote
Write-Output "Pushing to $gitRemote/$gitBranch..."

git push -u $gitRemote $gitBranch
$exitCode = $LASTEXITCODE

Write-ExitCodeError $exitCode
exit $exitCode
