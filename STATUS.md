# IronLedger Project Status

## Active Goal
Scheduled Price Polling Daemon & Interactive Operator Workbench Inspection (`C:\dev\IronLedger`).

## Milestone Status: Price Polling Automation, Watchlist GUI & Operator Workbench Live
- **Preceding Baseline:** Governed Multi-Provider Price Feed Daemon & Scheduled Polling Pipeline.
- **Regression Invariant:** 966 passed, 4 skipped (100% pass rate in 41.46s).
- **Current Milestone:** Scheduled Price Polling Daemon configured, CLI `prices poll` integration, and local Operator Workbench (`python -m ironledger.cli web --port 8080`) actively serving live analytics with interactive Watchlist GUI & on-demand price synchronization.

## Completed Work
1. **Watchlist Configuration & Polling Automation (`config/prices.json`, `scripts/`)**:
   - `config/prices.json`: Configured target watchlist commodities (`AAPL`, `MSFT`, `GOOGL`, `BTC`, `ETH`, `EUR`) and quote currency (`USD`) with polling interval and fallback quotes.
   - `src/ironledger/prices/scraper_daemon.py`: Added `load_config_watchlist` to load targets directly from configuration or fallback to active portfolio ledger postings.
   - `src/ironledger/cli/__main__.py`: Added `ironledger prices poll` subcommand supporting `--symbols`, `--quote-currency`, `--config-dir`, and `--json`.
   - `scripts/poll-prices.ps1`: Automated price feed scraper execution script.
   - `scripts/poll-simplefin.ps1`: Automated SimpleFIN bank transaction sync script.
   - `scripts/setup-scheduled-tasks.ps1`: Windows Task Scheduler registration script managing hourly price sync and daily bank sync.
2. **Watchlist GUI & Feed Resolution Management (`web/src/`)**:
   - `WatchlistPanel.tsx`: Dedicated React component displaying all watchlist target pairs, exact rational fractions $(N/D)$, effective decimal rates, quote timestamps, provider badges, and live resolution status badges (`SUCCESS`, `RECIPROCAL`, `CIRCUIT_OPEN`).
   - Integrated on-demand "Sync Watchlist" trigger button with spinner animation and live notification feedback.
   - Built inline "Add Symbol" form with custom base symbol, quote currency, and optional fallback rates updating `config/prices.json`.
   - Exposed `price_feed_audit` telemetry drawer rendering real-time resolution latencies and execution logs.
3. **Analytics REST Endpoints (`src/ironledger/web/routers/analytics.py`)**:
   - `GET /api/analytics/watchlist`: Returns configured watchlist symbols merged with latest `price_history` and `price_feed_audit` records.
   - `POST /api/analytics/prices/sync`: Triggers on-demand `PriceScraperDaemon` synchronization.
   - `POST /api/analytics/watchlist/add`: Appends new watchlist target pairs to `config/prices.json`.
4. **Interactive Operator Inspection (`python -m ironledger.cli web --port 8080`)**:
   - Web service actively running on `http://127.0.0.1:8080/`.
   - Verified `/healthz`, `/readyz`, `/api/analytics/sankey`, `/api/analytics/portfolio`, and `/api/analytics/watchlist`.
   - Verified SPA root web client mounting with compiled production assets.

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
