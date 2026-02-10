# Stage 01: Run project CLI via uvx with local dependencies

$ErrorActionPreference = "Stop"

python3 "$PSScriptRoot\_run.py" $args
exit $LASTEXITCODE
