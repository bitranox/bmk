# Sequential test: Ruff linting
# Runs before parallel tests - must pass before continuing

param([string]$ProjectDir = ".")

Set-Location $ProjectDir

Write-Host "Running ruff check..."
ruff check .
exit $LASTEXITCODE
