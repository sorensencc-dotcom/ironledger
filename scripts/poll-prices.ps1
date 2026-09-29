<#
.SYNOPSIS
    IronLedger Price Feed Polling Daemon Runner.
.DESCRIPTION
    Executes automated commodity and foreign exchange price polling using the
    governed PriceScraperDaemon. Reads target symbols from config/prices.json.
#>
[CmdletBinding()]
param(
    [string]$DbPath = "ironledger.db",
    [string]$ConfigDir = "config",
    [string]$LedgerDir = "ledger"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

Set-Location $RepoRoot

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

# Load .env if present
$EnvFile = Join-Path $RepoRoot ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            $k = $parts[0].Trim()
            $v = $parts[1].Trim()
            if (-not [System.Environment]::GetEnvironmentVariable($k)) {
                [System.Environment]::SetEnvironmentVariable($k, $v, "Process")
            }
        }
    }
}

Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting IronLedger Price Polling..." -ForegroundColor Cyan

& $PythonExe -m ironledger.cli prices poll --db $DbPath --config-dir $ConfigDir --ledger-dir $LedgerDir
$ExitCode = $LASTEXITCODE

if ($ExitCode -eq 0) {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Price polling completed successfully." -ForegroundColor Green
} else {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Price polling finished with code $ExitCode." -ForegroundColor Yellow
}

exit $ExitCode
