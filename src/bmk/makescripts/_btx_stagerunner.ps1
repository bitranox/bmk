# Generic staged command runner - executes scripts in staged parallel batches
#
# Required environment variables (set by Python CLI):
#   BMK_PROJECT_DIR    - Path to the project directory
#   BMK_COMMAND_PREFIX - Command prefix to match (e.g., "test", "build", "deploy")
#
# Optional environment variables:
#   BMK_STAGES_DIR     - Directory containing stage scripts (default: directory of this script)
#   BMK_OVERRIDE_DIR   - Per-project override directory for stage scripts
#                        (default: $BMK_PROJECT_DIR/makescripts)
#                        If scripts matching the command prefix exist here,
#                        they replace the bundled scripts entirely for that command.
#
# This script coordinates execution in STAGED PARALLEL BATCHES:
# - Stage 01: Run all {prefix}_01_*.ps1 in parallel, wait for all to complete
# - Stage 02: Run all {prefix}_02_*.ps1 in parallel, wait for all to complete
# - Continue for each stage found
#
# Behavior: Fail-fast BETWEEN stages, parallel WITHIN each stage.
# Single-script stages run with output directly to console.

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Environment validation
# ---------------------------------------------------------------------------

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}
if (-not $env:BMK_COMMAND_PREFIX) {
    throw "BMK_COMMAND_PREFIX environment variable must be set"
}

if (-not $env:BMK_STAGES_DIR) {
    $env:BMK_STAGES_DIR = $PSScriptRoot
}

if (-not $env:BMK_OVERRIDE_DIR) {
    $env:BMK_OVERRIDE_DIR = Join-Path $env:BMK_PROJECT_DIR "makescripts"
}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

$script:TotalScripts = 0
$script:ScriptArgs = $args
$script:FailedScripts = [System.Collections.Generic.List[string]]::new()

# ANSI color codes
$ColorGreen = "`e[32m"
$ColorRed = "`e[31m"
$ColorReset = "`e[0m"

# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

function Write-Die {
    param([string]$Message)
    Write-Error "Error: $Message"
    exit 1
}

function Resolve-StagesDir {
    # If the override directory contains scripts matching the command prefix,
    # use it exclusively instead of the bundled stages directory.
    $overridePattern = Join-Path $env:BMK_OVERRIDE_DIR "$($env:BMK_COMMAND_PREFIX)_*_*.ps1"
    $overrideScripts = @(Get-ChildItem -Path $overridePattern -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "^$([regex]::Escape($env:BMK_COMMAND_PREFIX))_\d{2,6}_.*\.ps1$" })

    if ($overrideScripts.Count -gt 0) {
        $env:BMK_STAGES_DIR = $env:BMK_OVERRIDE_DIR
    }
}

function Get-PackageName {
    # Derive BMK_PACKAGE_NAME from pyproject.toml if not already set
    if ($env:BMK_PACKAGE_NAME) { return }

    $pyprojectPath = Join-Path $env:BMK_PROJECT_DIR "pyproject.toml"
    if (-not (Test-Path $pyprojectPath)) {
        Write-Die "pyproject.toml not found in $($env:BMK_PROJECT_DIR)"
    }

    $pythonCode = @'
import sys
import rtoml
from pathlib import Path

pyproject_path = Path(sys.argv[1])
with pyproject_path.open("r", encoding="utf-8") as f:
    data = rtoml.load(f)

# Try to derive import package from hatch wheel packages
tool = data.get("tool", {})
hatch = tool.get("hatch", {})
build = hatch.get("build", {})
targets = build.get("targets", {})
wheel = targets.get("wheel", {})
packages = wheel.get("packages", [])

if packages:
    print(Path(packages[0]).name)
    sys.exit(0)

# Try to derive from project.scripts entry points
project = data.get("project", {})
scripts = project.get("scripts", {})

for spec in scripts.values():
    if ":" in spec:
        module = spec.split(":", 1)[0]
        print(module.split(".", 1)[0])
        sys.exit(0)

# Fallback to project name with hyphens replaced by underscores
name = project.get("name", "")
if name:
    print(name.replace("-", "_"))
    sys.exit(0)

sys.exit(1)
'@

    $result = python3 -c $pythonCode $pyprojectPath 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Die "Failed to derive package name from pyproject.toml"
    }
    $env:BMK_PACKAGE_NAME = ($result | Out-String).Trim()
}

function Get-StageNumber {
    param([string]$ScriptName)
    # Extract stage number from script name: {prefix}_NN_*.ps1
    $escapedPrefix = [regex]::Escape($env:BMK_COMMAND_PREFIX)
    if ($ScriptName -match "^${escapedPrefix}_(\d{2,6})_.*\.ps1$") {
        return [int]$Matches[1]
    }
    return $null
}

function Get-UniqueStages {
    # Discover unique stage numbers from matching scripts, sorted numerically
    $pattern = Join-Path $env:BMK_STAGES_DIR "$($env:BMK_COMMAND_PREFIX)_*_*.ps1"
    $scripts = @(Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue)

    $stages = [System.Collections.Generic.SortedSet[int]]::new()
    foreach ($s in $scripts) {
        $num = Get-StageNumber $s.Name
        if ($null -ne $num) {
            [void]$stages.Add($num)
        }
    }
    return $stages
}

function Get-ScriptsForStage {
    param([int]$Stage)
    # Return script paths matching a specific stage number
    $pattern = Join-Path $env:BMK_STAGES_DIR "$($env:BMK_COMMAND_PREFIX)_*_*.ps1"
    $allScripts = @(Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue)

    $matched = [System.Collections.Generic.List[System.IO.FileInfo]]::new()
    foreach ($s in $allScripts) {
        $num = Get-StageNumber $s.Name
        if ($num -eq $Stage) {
            $matched.Add($s)
        }
    }
    return $matched
}

function Invoke-SingleScript {
    param([int]$Stage, [System.IO.FileInfo]$Script)

    $script:TotalScripts++

    & $Script.FullName @script:ScriptArgs
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Write-Host "${ColorGreen}  $([char]0x2713) $($Script.Name)${ColorReset}"
        return 0
    }
    else {
        $script:FailedScripts.Add("$($Script.Name):$exitCode")
        return $exitCode
    }
}

function Invoke-StageParallel {
    param([int]$Stage)

    $scripts = @(Get-ScriptsForStage $Stage)
    if ($scripts.Count -eq 0) { return 0 }

    # Single script: run directly with output to console
    if ($scripts.Count -eq 1) {
        return (Invoke-SingleScript -Stage $Stage -Script $scripts[0])
    }

    $script:TotalScripts += $scripts.Count

    # Build ordered name list and announce parallel execution
    $scriptNames = [System.Collections.Generic.List[string]]::new()
    $friendlyNames = [System.Collections.Generic.List[string]]::new()
    foreach ($s in $scripts) {
        $scriptNames.Add($s.Name)
        $friendly = $s.Name -replace "^$([regex]::Escape($env:BMK_COMMAND_PREFIX))_\d+_", "" -replace "\.ps1$", ""
        $friendlyNames.Add($friendly)
    }
    $joined = $friendlyNames -join ', '
    Write-Host "  $([char]0x25B6) running $($scripts.Count) tasks in parallel: $joined"

    # Start all scripts as PowerShell jobs
    $jobs = @{}
    foreach ($s in $scripts) {
        $scriptPath = $s.FullName
        $scriptName = $s.Name
        $jobArgs = $script:ScriptArgs

        $job = Start-Job -ScriptBlock {
            param($Path, $Args_)
            & $Path @Args_
            exit $LASTEXITCODE
        } -ArgumentList $scriptPath, $jobArgs

        $jobs[$scriptName] = $job
    }

    # Wait for ALL jobs to complete before printing results
    $exitCodes = @{}
    $failed = [System.Collections.Generic.List[string]]::new()
    $failedOutput = @{}
    $firstFailureCode = $null

    foreach ($scriptName in $scriptNames) {
        $job = $jobs[$scriptName]
        $null = Wait-Job $job
        $exitCode = $job.ChildJobs[0].ExitCode
        if ($null -eq $exitCode) { $exitCode = if ($job.State -eq 'Failed') { 1 } else { 0 } }
        $output = Receive-Job $job 2>&1
        $exitCodes[$scriptName] = $exitCode

        if ($exitCode -ne 0) {
            $failed.Add($scriptName)
            $failedOutput[$scriptName] = $output
            $script:FailedScripts.Add("${scriptName}:${exitCode}")
            if ($null -eq $firstFailureCode) { $firstFailureCode = $exitCode }
        }

        Remove-Job $job -Force
    }

    # Print all results together
    foreach ($scriptName in $scriptNames) {
        $exitCode = $exitCodes[$scriptName]
        if ($exitCode -eq 0) {
            Write-Host "${ColorGreen}  $([char]0x2713) $scriptName${ColorReset}"
        }
        else {
            Write-Host "${ColorRed}  $([char]0x2717) $scriptName (exit code: $exitCode)${ColorReset}"
        }
    }

    # Print output of failed scripts
    if ($failed.Count -gt 0) {
        foreach ($scriptName in $failed) {
            Write-Host ""
            Write-Host "${ColorRed}[$scriptName] (exit code: $($failedOutput[$scriptName]))${ColorReset}"
            $output = $failedOutput[$scriptName]
            if ($output) {
                $output | ForEach-Object { Write-Host $_ }
            }
            else {
                Write-Host "(no output captured)"
            }
        }
        Write-Host ""
        return $(if ($firstFailureCode) { $firstFailureCode } else { 1 })
    }

    return 0
}

function Invoke-Run {
    Set-Location $env:BMK_PROJECT_DIR
    Resolve-StagesDir
    Get-PackageName

    $stages = @(Get-UniqueStages)

    if ($stages.Count -eq 0) {
        Write-Host "No scripts found for $($env:BMK_COMMAND_PREFIX). Create $($env:BMK_COMMAND_PREFIX)_NN_*.ps1 scripts where NN is a two-digit stage number."
        exit 0
    }

    # Run each stage sequentially; within each stage, scripts run in parallel
    foreach ($stage in $stages) {
        $result = Invoke-StageParallel -Stage $stage
        if ($result -ne 0) {
            foreach ($entry in $script:FailedScripts) {
                $parts = $entry -split ':', 2
                $sname = $parts[0]
                $scode = $parts[1]
                Write-Host "${ColorRed}  $([char]0x2717) $sname (exit code: $scode)${ColorReset}"
            }
            $firstCode = ($script:FailedScripts[0] -split ':', 2)[1]
            exit $(if ($firstCode) { [int]$firstCode } else { 1 })
        }
    }
}

Invoke-Run
