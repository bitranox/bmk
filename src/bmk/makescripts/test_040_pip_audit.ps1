# Stage 03: pip-audit dependency vulnerability scan
# Reads ignore-vulns from [tool.pip-audit] in pyproject.toml

$ErrorActionPreference = "Stop"

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
    $pythonCode = @'
import sys
import rtoml
from pathlib import Path

pyproject = Path("pyproject.toml")
if not pyproject.exists():
    sys.exit(0)

data = rtoml.load(pyproject.open("r", encoding="utf-8"))
ignores = data.get("tool", {}).get("pip-audit", {}).get("ignore-vulns", [])

for vuln_id in ignores:
    print(f"--ignore-vuln={vuln_id}")
'@
    $result = python3 -c $pythonCode 2>$null
    if ($result) {
        $ignoreFlags = @($result -split "`n" | Where-Object { $_ })
    }
}

Write-Host "Running pip-audit..."

pip-audit @ignoreFlags
$exitCode = $LASTEXITCODE

Explain-ExitCode $exitCode
exit $exitCode
