# IronLedger

Local-first, single-operator financial OS. Beancount is the accounting
authority; SQLite is a disposable projection.

Requires Python 3.12+. Mutators need `config/safe-mode.json` with
`{"enabled": false}` (a missing file means safe mode is on). From the
repo root after a successful compile:

```text
$env:PYTHONPATH='src'

python -m ironledger.cli project --db ironledger.db --ledger-dir ledger --confirm "authorize project"
python -m ironledger.cli search --ledger-dir ledger coffee
python -m ironledger.cli balances --ledger-dir ledger
```

`search` prints date, payee, account, integer minor units, and currency.
`ironledger` on PATH is optional; tests and this README call `python -m ironledger.cli`.
