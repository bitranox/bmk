# Parallel test: Unit tests with pytest

param(
    [string]$ProjectDir = ".",
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$ExtraArgs
)

Set-Location $ProjectDir

Write-Host "Running pytest..."
pytest --tb=short -q @ExtraArgs
exit $LASTEXITCODE
