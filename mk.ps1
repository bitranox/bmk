# Thin wrapper - delegates to mk.py
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& python "$scriptDir\mk.py" @args
exit $LASTEXITCODE
