# IronLedger

Local-first, single-operator financial OS. Beancount is the accounting
authority; SQLite is a disposable projection.

Requires Python 3.12+. From the repo root after a successful compile:

```text
$env:PYTHONPATH='src'

python -m ironledger.cli project --db <db> --ledger-dir ledger --confirm "authorize project"

python -m ironledger.cli search --ledger-dir ledger coffee

python -m ironledger.cli balances --ledger-dir ledger
```

`ironledger` on PATH is optional; tests and this README call `python -m ironledger.cli`.
