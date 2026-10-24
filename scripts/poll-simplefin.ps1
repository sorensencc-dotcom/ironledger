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

Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting IronLedger SimpleFIN Bank Sync..." -ForegroundColor Cyan

# Default scheduled writes use the same native-volume database as the workbench.
if ($DbPath -eq "ironledger.db") {
    & docker exec --workdir /data ironledger-workbench python -m ironledger.cli sync poll --db /var/lib/ironledger/ironledger.db --lookback $LookbackDays
} else {
    & $PythonExe -m ironledger.cli sync poll --db $DbPath --lookback $LookbackDays
}
$ExitCode = $LASTEXITCODE

if ($ExitCode -eq 0) {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] SimpleFIN sync completed successfully." -ForegroundColor Green
} else {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] SimpleFIN sync finished with code $ExitCode." -ForegroundColor Yellow
}

exit $ExitCode
