# Shared library for bump scripts - dot-source this, don't execute directly.
# Prefixed with underscore so stagerunner ignores it.

function Initialize-Bump {
    <#
    .SYNOPSIS
        Initialize bump environment and change to project directory.
    #>
    $ErrorActionPreference = "Stop"
    if (-not $env:BMK_PROJECT_DIR) {
        Write-Error "BMK_PROJECT_DIR environment variable must be set"
        exit 1
    }
    Set-Location $env:BMK_PROJECT_DIR
}

function Explain-BumpExitCode {
    <#
    .SYNOPSIS
        Print human-readable explanation for bump exit codes.
    .PARAMETER Code
        The exit code to explain.
    #>
    param(
        [Parameter(Mandatory=$true)]
        [int]$Code
    )
    switch ($Code) {
        0 { }
        1 { Write-Error "Exit code 1: Version bump failed" }
        default { Write-Error "Exit code ${Code}: unknown" }
    }
}

function Invoke-Bump {
    <#
    .SYNOPSIS
        Run the version bump for the specified part.
    .PARAMETER BumpType
        The version part to bump: major, minor, or patch.
    .PARAMETER ScriptDir
        The directory containing bump_version.py.
    #>
    param(
        [Parameter(Mandatory=$true)]
        [ValidateSet("major", "minor", "patch")]
        [string]$BumpType,

        [Parameter(Mandatory=$true)]
        [string]$ScriptDir
    )

    Write-Host "Bumping $BumpType version..."

    python3 "$ScriptDir\_bump_version.py" $BumpType --project-dir $env:BMK_PROJECT_DIR
    $exitCode = $LASTEXITCODE

    Explain-BumpExitCode $exitCode
    exit $exitCode
}
