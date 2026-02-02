# Default test script - override by placing bmk_makescripts/test.ps1 in your project
#
# Usage: test.ps1 <project_dir> [extra_args...]
#
# This script coordinates test execution:
# 1. Runs test_01.ps1, test_02.ps1, ... SEQUENTIALLY (stops on first failure)
# 2. Runs test_parallel_01.ps1, test_parallel_02.ps1, ... IN PARALLEL
#
# All scripts receive the same arguments: <project_dir> [extra_args...]

param(
    [Parameter(Position=0)]
    [string]$ProjectDir = ".",

    [Parameter(Position=1, ValueFromRemainingArguments=$true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Set-Location $ProjectDir

$OverallExit = 0

# ─────────────────────────────────────────────────────────────────────────────
# SEQUENTIAL SCRIPTS: test_01.ps1, test_02.ps1, ...
# ─────────────────────────────────────────────────────────────────────────────

$SequentialScripts = Get-ChildItem -Path $ScriptDir -Filter "test_[0-9][0-9]*.ps1" -File | Sort-Object Name

if ($SequentialScripts.Count -gt 0) {
    Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "SEQUENTIAL TESTS ($($SequentialScripts.Count) scripts)" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""

    foreach ($script in $SequentialScripts) {
        Write-Host "▶ Running: $($script.Name)" -ForegroundColor White
        Write-Host "───────────────────────────────────────────────────────────────────────────────"

        try {
            & $script.FullName $ProjectDir @ExtraArgs
            if ($LASTEXITCODE -eq 0) {
                Write-Host ""
                Write-Host "  ✓ $($script.Name) passed" -ForegroundColor Green
                Write-Host ""
            } else {
                Write-Host ""
                Write-Host "  ✗ $($script.Name) FAILED (exit code: $LASTEXITCODE)" -ForegroundColor Red
                Write-Host ""
                Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Red
                Write-Host "STOPPED: Sequential test failed" -ForegroundColor Red
                Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Red
                exit $LASTEXITCODE
            }
        } catch {
            Write-Host ""
            Write-Host "  ✗ $($script.Name) FAILED (exception)" -ForegroundColor Red
            Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
            Write-Host ""
            Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Red
            Write-Host "STOPPED: Sequential test failed" -ForegroundColor Red
            Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Red
            exit 1
        }
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# PARALLEL SCRIPTS: test_parallel_01.ps1, test_parallel_02.ps1, ...
# ─────────────────────────────────────────────────────────────────────────────

$ParallelScripts = Get-ChildItem -Path $ScriptDir -Filter "test_parallel_[0-9][0-9]*.ps1" -File | Sort-Object Name

if ($ParallelScripts.Count -gt 0) {
    Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "PARALLEL TESTS ($($ParallelScripts.Count) scripts)" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""

    $Jobs = @{}

    foreach ($script in $ParallelScripts) {
        $job = Start-Job -ScriptBlock {
            param($ScriptPath, $ProjDir, $Args)
            try {
                $output = & $ScriptPath $ProjDir @Args 2>&1 | Out-String
                @{
                    Output = $output
                    ExitCode = $LASTEXITCODE
                }
            } catch {
                @{
                    Output = $_.Exception.Message
                    ExitCode = 1
                }
            }
        } -ArgumentList $script.FullName, $ProjectDir, $ExtraArgs

        $Jobs[$script.Name] = $job
    }

    # Wait and collect results
    $Results = @{}
    $Failed = @()
    $Passed = @()

    foreach ($entry in $Jobs.GetEnumerator()) {
        $scriptName = $entry.Key
        $job = $entry.Value

        $result = Receive-Job -Job $job -Wait
        Remove-Job -Job $job

        $Results[$scriptName] = $result

        if ($result.ExitCode -eq 0) {
            $Passed += $scriptName
            Write-Host "  ✓ $scriptName" -ForegroundColor Green
        } else {
            $Failed += $scriptName
            Write-Host "  ✗ $scriptName (exit code: $($result.ExitCode))" -ForegroundColor Red
            $OverallExit = 1
        }
    }

    Write-Host ""

    # Print output of failed parallel scripts
    if ($Failed.Count -gt 0) {
        Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Red
        Write-Host "FAILED PARALLEL TESTS OUTPUT:" -ForegroundColor Red
        Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Red

        foreach ($scriptName in $Failed) {
            $result = $Results[$scriptName]
            Write-Host ""
            Write-Host "───────────────────────────────────────────────────────────────────────────────" -ForegroundColor Yellow
            Write-Host "[$scriptName] (exit code: $($result.ExitCode))" -ForegroundColor Yellow
            Write-Host "───────────────────────────────────────────────────────────────────────────────" -ForegroundColor Yellow
            if ($result.Output) {
                Write-Host $result.Output
            } else {
                Write-Host "(no output captured)"
            }
        }
        Write-Host ""
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "═══════════════════════════════════════════════════════════════════════════════"
if ($OverallExit -eq 0) {
    $total = $SequentialScripts.Count + $ParallelScripts.Count
    if ($total -eq 0) {
        Write-Host "NO TEST SCRIPTS FOUND" -ForegroundColor Yellow
        Write-Host "Create test_01.ps1, test_02.ps1, ... for sequential tests"
        Write-Host "Create test_parallel_01.ps1, test_parallel_02.ps1, ... for parallel tests"
    } else {
        Write-Host "ALL TESTS PASSED" -ForegroundColor Green
    }
} else {
    Write-Host "SOME TESTS FAILED" -ForegroundColor Red
}
Write-Host "═══════════════════════════════════════════════════════════════════════════════"

exit $OverallExit
