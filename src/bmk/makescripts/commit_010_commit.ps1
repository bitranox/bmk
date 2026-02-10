# Git commit with timestamp prefix

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}

Set-Location $env:BMK_PROJECT_DIR

function Explain-ExitCode {
    param([int]$Code)
    switch ($Code) {
        0 { }
        1 { Write-Error "Exit code 1: Commit failed (nothing to commit or pre-commit hook failed)" }
        128 { Write-Error "Exit code 128: Fatal git error" }
        129 { Write-Error "Exit code 129: Git usage error" }
        default { Write-Error "Exit code ${Code}: unknown" }
    }
}

# Resolve commit message:
# 1. Command line arguments
# 2. BMK_COMMIT_MESSAGE environment variable
# 3. Prompt interactively (only if terminal available)
$commitMessage = ($args -join " ").Trim()

if (-not $commitMessage) {
    $commitMessage = $env:BMK_COMMIT_MESSAGE
}

if (-not $commitMessage) {
    if ([Environment]::UserInteractive) {
        $commitMessage = Read-Host "Commit message"
        if (-not $commitMessage) {
            Write-Error "Commit message cannot be empty"
            exit 1
        }
    }
    else {
        # Non-interactive, use default
        $commitMessage = "chores"
    }
}

# Create timestamp prefix (local time)
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$fullMessage = "$timestamp - $commitMessage"

# Stage all changes
Write-Host "Staging changes..."
git add -A

# Warn about potentially sensitive files being staged
$sensitiveFiles = git diff --cached --name-only | Select-String -Pattern '\.env$|\.env\.|credentials|secret|\.key$|\.pem$|id_rsa' -CaseSensitive:$false
if ($sensitiveFiles) {
    Write-Warning "Potentially sensitive files staged:"
    foreach ($f in $sensitiveFiles) {
        Write-Warning "  $f"
    }
    Write-Warning "These files will be committed. Ensure .gitignore is correct."
}

# Build commit arguments
$commitArgs = @()
$stagedChanges = git diff --cached --quiet 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "No staged changes detected; creating empty commit"
    $commitArgs += "--allow-empty"
}

# Commit with timestamped message
Write-Host "Committing: $fullMessage"

git commit @commitArgs -m $fullMessage
$exitCode = $LASTEXITCODE

Explain-ExitCode $exitCode
exit $exitCode
