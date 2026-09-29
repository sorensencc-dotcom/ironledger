<#
.SYNOPSIS
    IronLedger Email Receipt Sweep & Ingestion Runner.
.DESCRIPTION
    Automates:
    1. Sweeping new receipt emails from Gmail via IMAP into inbox/receipts/ and tagging with 'IronLedger-Processed'.
    2. Ingesting saved .eml receipts into itemized_orders and creating split proposals in ironledger.db.
#>
[CmdletBinding()]
param(
    [string]$DbPath = "ironledger.db",
    [string]$ReceiptsDir = "inbox/receipts",
    [string]$AddLabel = "IronLedger/Processed",
    [string]$RemoveLabel = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

Set-Location $RepoRoot

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

# Load .env if present and GMAIL_APP_PASSWORD not already set
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

Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting IronLedger Receipt Sweep & Ingestion..." -ForegroundColor Cyan

# 1. Sweep new receipts from Gmail
$SweepArgs = @("scripts/sweep_receipts.py", "--out-dir", $ReceiptsDir)
if ($AddLabel) {
    $SweepArgs += @("--add-label", $AddLabel)
}
if ($RemoveLabel) {
    $SweepArgs += @("--remove-label", $RemoveLabel)
}

Write-Host "Step 1: Sweeping receipts from Gmail..." -ForegroundColor Cyan
& $PythonExe $SweepArgs
$SweepExitCode = $LASTEXITCODE

if ($SweepExitCode -ne 0) {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Receipt sweep failed with code $SweepExitCode." -ForegroundColor Red
    exit $SweepExitCode
}

# 2. Ingest into IronLedger SQLite database
Write-Host "Step 2: Ingesting receipts into IronLedger..." -ForegroundColor Cyan
& $PythonExe scripts/ingest_receipts.py --receipts-dir $ReceiptsDir --db $DbPath
$IngestExitCode = $LASTEXITCODE

if ($IngestExitCode -eq 0) {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Receipt sweep & ingestion completed successfully." -ForegroundColor Green
} else {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Receipt ingestion finished with code $IngestExitCode." -ForegroundColor Yellow
}

exit $IngestExitCode
