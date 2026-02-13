#Requires -Version 7.0
# Stage 01: Bump patch version
. "$PSScriptRoot\_bump_lib.ps1"; Initialize-Bump; Invoke-Bump -BumpType patch -ScriptDir $PSScriptRoot
