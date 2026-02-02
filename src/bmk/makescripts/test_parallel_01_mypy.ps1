# Parallel test: Type checking with mypy

param([string]$ProjectDir = ".")

Set-Location $ProjectDir

Write-Host "Running mypy..."
mypy .
exit $LASTEXITCODE
