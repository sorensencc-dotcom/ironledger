$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = "hostPython"
$LookbackDays = 30
$ConfigDir = "config"
$LedgerDir = "ledger"
$ReceiptsDir = "inbox/receipts"
function docker { $script:Called = "docker"; $script:Captured = @($args); $global:LASTEXITCODE = 0 }
function hostPython { $script:Called = "host"; $script:Captured = @($args); $global:LASTEXITCODE = 0 }
foreach ($name in @("poll-simplefin.ps1", "poll-prices.ps1", "poll-receipts.ps1")) {
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $PSScriptRoot $name), [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw "Invalid PowerShell: $name" }
    $route = $ast.Find({ param($node)
        $node -is [System.Management.Automation.Language.IfStatementAst] -and
        $node.Clauses[0].Item1.Extent.Text -eq '$DbPath -eq "ironledger.db"'
    }, $true)
    if (-not $route) { throw "Missing default database routing: $name" }
    $DbPath = "ironledger.db"
    Invoke-Expression $route.Extent.Text
    if ($script:Called -ne "docker" -or
        $script:Captured -notcontains "ironledger-workbench" -or
        $script:Captured -notcontains "/var/lib/ironledger/ironledger.db") {
        throw "Default writer bypassed container database: $name"
    }
    $DbPath = "isolated-test.db"
    Invoke-Expression $route.Extent.Text
    if ($script:Called -ne "host" -or $script:Captured -notcontains $DbPath) {
        throw "Explicit isolated database override lost: $name"
    }
}
Write-Output "Three poller routing checks passed; no network or database writes."
