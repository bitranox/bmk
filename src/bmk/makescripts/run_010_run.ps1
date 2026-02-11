# Stage 01: Run project CLI via uvx with local dependencies

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_resolve_python.ps1"

& $BMK_PYTHON_CMD "$PSScriptRoot\_run.py" $args
exit $LASTEXITCODE
