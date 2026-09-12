# IronLedger Project Status

## Active Goal
Scheduled Price Polling Daemon & Interactive Operator Workbench Inspection (`C:\dev\IronLedger`).

## Milestone Status: Price Polling Automation & Operator Workbench Live
- **Preceding Baseline:** Governed Multi-Provider Price Feed Daemon, Dual-Persistence Engine & FastMCP integration.
- **Regression Invariant:** 966 passed, 4 skipped (100% pass rate in 44.60s).
- **Current Milestone:** Scheduled Price Polling Daemon configured (`config/prices.json`, `scripts/poll-prices.ps1`, `scripts/setup-scheduled-tasks.ps1`), CLI `prices poll` integration, and local Operator Workbench (`python -m ironledger.cli web --port 8080`) actively serving live analytics.

## Completed Work
1. **Watchlist Configuration & Polling Automation (`config/prices.json`, `scripts/`)**:
   - `config/prices.json`: Configured target watchlist commodities (`AAPL`, `MSFT`, `GOOGL`, `BTC`, `ETH`, `EUR`) and quote currency (`USD`) with polling interval and fallback quotes.
   - `src/ironledger/prices/scraper_daemon.py`: Added `load_config_watchlist` to load targets directly from configuration or fallback to active portfolio ledger postings.
   - `src/ironledger/cli/__main__.py`: Added `ironledger prices poll` subcommand supporting `--symbols`, `--quote-currency`, `--config-dir`, and `--json`.
   - `scripts/poll-prices.ps1`: Automated price feed scraper execution script.
   - `scripts/poll-simplefin.ps1`: Automated SimpleFIN bank transaction sync script.
   - `scripts/setup-scheduled-tasks.ps1`: Windows Task Scheduler registration script managing hourly price sync and daily bank sync.
2. **Migration Engine Hardening (`src/ironledger/governance/migrations.py`)**:
   - Configured safe SQLite foreign key toggling outside transactions during DDL migrations with `PRAGMA foreign_key_check` validation.
3. **Interactive Operator Inspection (`python -m ironledger.cli web --port 8080`)**:
   - Started Operator Workbench backend daemon on `http://127.0.0.1:8080/`.
   - Verified `/healthz`, `/readyz`, `/api/analytics/sankey`, and `/api/analytics/portfolio` REST endpoints.
   - Verified SPA root web client mounting and D3 visualizer assets.

## Core Architectural Invariants Maintained
- **Plaintext Ground Truth:** Plaintext Beancount files (`ledger/prices.beancount`) remain the sole financial authority.
- **Decoupled Runtime:** Zero runtime `import beancount` enforced via static AST visitor.
- **Pure Integer Arithmetic:** Exact rational arithmetic without float representation or drift.
- **Envelope Encryption:** AES-256-GCM with separate IV/auth tags and zero plaintext payload leakage.
- **Append-Only Immutability:** SQLite triggers guarding outbox, audit, mutation, and governance event streams.
- **Multi-Tenant Boundaries:** Relational composite keys and tenant registries enforcing strict ledger isolation.
- **Fenced HA Quorum:** Monotonic terms and randomized fence tokens preventing split-brain dual primary operations.

## Next Action
Continuous live monitoring and scheduled background execution.
