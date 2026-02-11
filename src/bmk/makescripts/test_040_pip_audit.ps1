# Stage 03: pip-audit dependency vulnerability scan
# Reads ignore-vulns from [tool.pip-audit] in pyproject.toml

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_resolve_python.ps1"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}

Set-Location $env:BMK_PROJECT_DIR

function Explain-ExitCode {
    param([int]$Code)
    switch ($Code) {
        0 { }
        1 { Write-Error "Exit code 1: Vulnerabilities found" }
        default { Write-Error "Exit code ${Code}: unknown" }
    }
}

# Extract ignore-vulns from pyproject.toml and build CLI flags
$ignoreFlags = @()
if (Test-Path "pyproject.toml") {
    $result = & $BMK_PYTHON_CMD "$PSScriptRoot\_extract_pip_audit_ignores.py" 2>$null
    if ($result) {
        $ignoreFlags = @($result -split "`n" | Where-Object { $_ })
    }
}

Write-Host "Running pip-audit..."

pip-audit @ignoreFlags
$exitCode = $LASTEXITCODE

Explain-ExitCode $exitCode
exit $exitCode
