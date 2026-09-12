<#
.SYNOPSIS
    Register IronLedger Background Scheduled Tasks in Windows Task Scheduler.
.DESCRIPTION
    Creates scheduled tasks for:
    1. IronLedger-PriceFeed-Sync: Hourly price scraper polling.
    2. IronLedger-Bank-Sync: Daily bank transaction synchronization via SimpleFIN.
#>
[CmdletBinding()]
param(
    [switch]$Unregister,
    [string]$PriceInterval = "01:00:00",
    [string]$BankDailyTime = "06:00:00"
)

$PriceTaskName = "IronLedger-PriceFeed-Sync"
$BankTaskName = "IronLedger-Bank-Sync"

if ($Unregister) {
    Write-Host "Unregistering IronLedger scheduled tasks..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $PriceTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $BankTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Scheduled tasks unregistered." -ForegroundColor Green
    return
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$PwshPath = (Get-Process -Id $PID).Path

$PriceScript = Join-Path $ScriptDir "poll-prices.ps1"
$BankScript = Join-Path $ScriptDir "poll-simplefin.ps1"

Write-Host "Registering IronLedger Scheduled Tasks..." -ForegroundColor Cyan

# 1. Price Feed Polling Task (Runs hourly)
$PriceAction = New-ScheduledTaskAction -Execute $PwshPath -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PriceScript`"" -WorkingDirectory $RepoRoot
$PriceTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration ([TimeSpan]::MaxValue)
$PriceSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $PriceTaskName -Action $PriceAction -Trigger $PriceTrigger -Settings $PriceSettings -Description "IronLedger Governed Multi-Provider Commodity Price Feed Daemon" -Force | Out-Null
Write-Host "  [OK] Registered '$PriceTaskName' (Hourly)" -ForegroundColor Green

# 2. Bank Transaction Sync Task (Runs daily at 06:00 AM)
$BankAction = New-ScheduledTaskAction -Execute $PwshPath -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$BankScript`"" -WorkingDirectory $RepoRoot
$BankTrigger = New-ScheduledTaskTrigger -Daily -At (Get-Date "06:00:00")
$BankSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $BankTaskName -Action $BankAction -Trigger $BankTrigger -Settings $BankSettings -Description "IronLedger SimpleFIN Bank Transaction Synchronizer" -Force | Out-Null
Write-Host "  [OK] Registered '$BankTaskName' (Daily at 06:00)" -ForegroundColor Green

Write-Host "`nAll background scheduling tasks configured successfully." -ForegroundColor Cyan
