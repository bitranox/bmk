# Sequential test: Ruff formatting check
# Runs before parallel tests - must pass before continuing

param([string]$ProjectDir = ".")

Set-Location $ProjectDir

Write-Host "Running ruff format check..."
ruff format --check .
exit $LASTEXITCODE
