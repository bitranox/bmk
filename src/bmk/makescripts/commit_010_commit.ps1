# Git commit with timestamp prefix

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    Write-Error "BMK_PROJECT_DIR environment variable must be set"
    exit 1
}

Set-Location $env:BMK_PROJECT_DIR

# Join all arguments as the commit message
$commitMessage = $args -join " "

# If no message provided, prompt for one
if ([string]::IsNullOrWhiteSpace($commitMessage)) {
    $commitMessage = Read-Host "Commit message"
    if ([string]::IsNullOrWhiteSpace($commitMessage)) {
        Write-Error "Commit message cannot be empty"
        exit 1
    }
}

# Create timestamp prefix (local time)
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$fullMessage = "$timestamp - $commitMessage"

# Stage all changes
Write-Host "Staging changes..."
git add -A

# Commit with timestamped message
Write-Host "Committing: $fullMessage"
git commit -m $fullMessage
