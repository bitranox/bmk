# Stage 01: Bump major version
. "$PSScriptRoot\_bump_lib.ps1"; Initialize-Bump; Invoke-Bump -BumpType major -ScriptDir $PSScriptRoot
