# Stage 05: Git push to remote

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}

Set-Location $env:BMK_PROJECT_DIR

# Configuration: remote and branch
$gitRemote = if ($env:BMK_GIT_REMOTE) { $env:BMK_GIT_REMOTE } else { "origin" }
$gitBranch = if ($env:BMK_GIT_BRANCH) { $env:BMK_GIT_BRANCH } else { (git rev-parse --abbrev-ref HEAD) }

function Explain-ExitCode {
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
Write-Host "Pushing to $gitRemote/$gitBranch..."

git push -u $gitRemote $gitBranch
$exitCode = $LASTEXITCODE

Explain-ExitCode $exitCode
exit $exitCode
