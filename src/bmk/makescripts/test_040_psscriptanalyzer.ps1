#Requires -Version 7.0
# Stage 05: PowerShell linting (PSScriptAnalyzer)
$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) { throw "BMK_PROJECT_DIR environment variable must be set" }

. "$PSScriptRoot\_resolve_python.ps1"

$outputFormat = if ($env:BMK_OUTPUT_FORMAT) { $env:BMK_OUTPUT_FORMAT } else { "json" }
$pssaArgs = @()
if ($outputFormat -eq "json") {
    $pssaArgs += "--output-format", "json"
}

& $BMK_PYTHON_CMD "$PSScriptRoot\_psscriptanalyzer.py" --project-dir $env:BMK_PROJECT_DIR @pssaArgs $args
