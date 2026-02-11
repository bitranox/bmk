# Shared helper: resolve the Python interpreter command.
# Dot-source this from any makescript that needs to call Python:
#
#   . "$PSScriptRoot\_resolve_python.ps1"
#   & $BMK_PYTHON_CMD "$PSScriptRoot\_somescript.py" ...
#
# On Windows the Microsoft Store registers an "App Execution Alias" stub at
# %LOCALAPPDATA%\Microsoft\WindowsApps\python.exe. This stub writes directly
# to the console (bypassing PowerShell's output streams) and returns exit
# code 9009 — it cannot be suppressed with redirections or try/catch.
#
# We detect the stub by path and skip it, using Get-Command -All to find
# a real interpreter even when the stub shadows it in PATH.
#
# Sets the module-level variable $BMK_PYTHON_CMD to the resolved command path.

# Honour the interpreter passed down from the Python CLI (e.g. uv-managed venv).
if ($env:BMK_PYTHON_CMD -and (Test-Path $env:BMK_PYTHON_CMD)) {
    $BMK_PYTHON_CMD = $env:BMK_PYTHON_CMD
}
else {
    $BMK_PYTHON_CMD = $null

    foreach ($candidate in @("python", "python3")) {
        $commands = @(Get-Command $candidate -All -ErrorAction SilentlyContinue)
        foreach ($cmd in $commands) {
            # Skip the Windows Store execution alias stub
            if ($cmd.Source -match '\\Microsoft\\WindowsApps\\') { continue }
            $BMK_PYTHON_CMD = $cmd.Source
            break
        }
        if ($BMK_PYTHON_CMD) { break }
    }

    if (-not $BMK_PYTHON_CMD) {
        Write-Error "Neither 'python' nor 'python3' found in PATH (or only the Windows Store stub is present)"
        exit 1
    }
}
