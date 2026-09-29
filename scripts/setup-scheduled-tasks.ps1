<#
.SYNOPSIS
    Register IronLedger Background Scheduled Tasks in Windows Task Scheduler.
.DESCRIPTION
    Creates scheduled tasks for:
    1. IronLedger-PriceFeed-Sync: Hourly price scraper polling.
    2. IronLedger-Bank-Sync: Daily bank transaction synchronization via SimpleFIN.
    3. IronLedger-Receipt-Sync: Daily Gmail receipt sweep and ingestion.
#>
[CmdletBinding()]
param(
    [switch]$Unregister,
    [string]$PriceInterval = "01:00:00",
    [string]$BankDailyTime = "06:00:00",
    [string]$ReceiptDailyTime = "06:15:00"
)

$PriceTaskName = "IronLedger-PriceFeed-Sync"
$BankTaskName = "IronLedger-Bank-Sync"
$ReceiptTaskName = "IronLedger-Receipt-Sync"

if ($Unregister) {
    Write-Host "Unregistering IronLedger scheduled tasks..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $PriceTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $BankTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $ReceiptTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Scheduled tasks unregistered." -ForegroundColor Green
    return
}

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsAdmin) {
    Write-Warning "Registering tasks to run unattended (whether logged on or not) requires an elevated Administrator PowerShell session."
    Write-Host "Please re-run this script in an elevated PowerShell terminal (Run as Administrator)." -ForegroundColor Yellow
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$PwshPath = (Get-Process -Id $PID).Path

$PriceScript = Join-Path $ScriptDir "poll-prices.ps1"
$BankScript = Join-Path $ScriptDir "poll-simplefin.ps1"
$ReceiptScript = Join-Path $ScriptDir "poll-receipts.ps1"

Write-Host "Registering IronLedger Scheduled Tasks (Unattended S4U Mode)..." -ForegroundColor Cyan

# Principal for running unattended without requiring active interactive logon
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Highest

# Common settings: run whether on battery, catch up if missed, 2h max execution limit
$CommonSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)

# 1. Price Feed Polling Task (Runs hourly)
$PriceAction = New-ScheduledTaskAction -Execute $PwshPath -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PriceScript`"" -WorkingDirectory $RepoRoot
$PriceTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1)

try {
    Register-ScheduledTask -TaskName $PriceTaskName -Action $PriceAction -Trigger $PriceTrigger -Settings $CommonSettings -Principal $Principal -Description "IronLedger Governed Multi-Provider Commodity Price Feed Daemon" -Force -ErrorAction Stop | Out-Null
    Write-Host "  [OK] Registered '$PriceTaskName' (Hourly, S4U Unattended)" -ForegroundColor Green
} catch {
    Write-Host "  [FAIL] Failed to register '$PriceTaskName': $_" -ForegroundColor Red
}

# 2. Bank Transaction Sync Task (Runs daily at 06:00 AM)
$BankAction = New-ScheduledTaskAction -Execute $PwshPath -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$BankScript`"" -WorkingDirectory $RepoRoot
$BankTrigger = New-ScheduledTaskTrigger -Daily -At (Get-Date $BankDailyTime)

try {
    Register-ScheduledTask -TaskName $BankTaskName -Action $BankAction -Trigger $BankTrigger -Settings $CommonSettings -Principal $Principal -Description "IronLedger SimpleFIN Bank Transaction Synchronizer" -Force -ErrorAction Stop | Out-Null
    Write-Host "  [OK] Registered '$BankTaskName' (Daily at $BankDailyTime, S4U Unattended)" -ForegroundColor Green
} catch {
    Write-Host "  [FAIL] Failed to register '$BankTaskName': $_" -ForegroundColor Red
}

# 3. Receipt Sweep & Ingestion Task (Runs daily at 06:15 AM)
$ReceiptAction = New-ScheduledTaskAction -Execute $PwshPath -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ReceiptScript`"" -WorkingDirectory $RepoRoot
$ReceiptTrigger = New-ScheduledTaskTrigger -Daily -At (Get-Date $ReceiptDailyTime)

try {
    Register-ScheduledTask -TaskName $ReceiptTaskName -Action $ReceiptAction -Trigger $ReceiptTrigger -Settings $CommonSettings -Principal $Principal -Description "IronLedger Automated Gmail Receipt Sweeper & Split Proposal Ingestor" -Force -ErrorAction Stop | Out-Null
    Write-Host "  [OK] Registered '$ReceiptTaskName' (Daily at $ReceiptDailyTime, S4U Unattended)" -ForegroundColor Green
} catch {
    Write-Host "  [FAIL] Failed to register '$ReceiptTaskName': $_" -ForegroundColor Red
}

Write-Host "`nAll background scheduling tasks configured." -ForegroundColor Cyan
