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

    try {
        python3 "$ScriptDir\_bump_version.py" $BumpType --project-dir $env:BMK_PROJECT_DIR
        $exitCode = $LASTEXITCODE
    }
    catch {
        Write-Error "Version bump failed: $_"
        exit 1
    }

    if ($exitCode -ne 0) {
        Write-Error "Version bump failed with exit code $exitCode"
    }
    exit $exitCode
}
