# IronLedger

Local-first, single-operator financial OS. Beancount is the accounting
authority; SQLite is a disposable projection.

Requires Python 3.12+ (or Docker). Mutators need `config/safe-mode.json` with
`{"enabled": false}` (a missing file means safe mode is on).

---

## Operator Workbench (Web UI)

IronLedger provides a local-first React 19 operator workbench for visual staging review, rule drift monitoring, plain-text Beancount previews, dry-run simulation, and hash-chained meta-ledger auditing.

### 1. Automatic Background Execution (Docker)

To run the full workbench stack automatically in the background with auto-restart:

```powershell
# Start container in background
docker compose up -d

# View live server logs
docker compose logs -f

# Stop background service
docker compose down
```

The workbench UI will be accessible at **`http://localhost:8000`** (or `http://127.0.0.1:8000`). Local database files (`ironledger.db`, `projection.db`, `evidence/`) are mounted directly from the repository root for host persistence.

### 2. Direct CLI Execution

To run directly on the host using Python:

```powershell
$env:PYTHONPATH='src'

# Launch server and automatically open default web browser
python -m ironledger.cli web --db ironledger.db --open-browser
```

---

## Command-Line Usage

From the repo root after a successful compile:

```powershell
$env:PYTHONPATH='src'

python -m ironledger.cli project --db ironledger.db --ledger-dir ledger --confirm "authorize project"
python -m ironledger.cli search --ledger-dir ledger coffee
python -m ironledger.cli balances --ledger-dir ledger
```

`search` prints date, payee, account, integer minor units, and currency.
`ironledger` on PATH is optional; tests and this README call `python -m ironledger.cli`.
