<#
.SYNOPSIS
    IronLedger SimpleFIN Bank Transaction Polling Runner.
.DESCRIPTION
    Executes automated bank transaction synchronization via SimpleFIN bridge.
#>
[CmdletBinding()]
param(
    [string]$DbPath = "ironledger.db",
    [int]$LookbackDays = 30
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

Set-Location $RepoRoot

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting IronLedger SimpleFIN Bank Sync..." -ForegroundColor Cyan

& $PythonExe -m ironledger.cli sync poll --db $DbPath --lookback $LookbackDays
$ExitCode = $LASTEXITCODE

if ($ExitCode -eq 0) {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] SimpleFIN sync completed successfully." -ForegroundColor Green
} else {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] SimpleFIN sync finished with code $ExitCode." -ForegroundColor Yellow
}

exit $ExitCode
