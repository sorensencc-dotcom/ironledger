# IronLedger Project Status

## Active Goal
Operator Workbench Production Hardening: Multi-Asset Valuation, Watchlist Lock Guard, Automated Docs Build Pipeline, and Standardized Port 8000 (`C:\dev\IronLedger`).

## Milestone Status: Operator Workbench v0.12.0 Live on Port 8000
- **Preceding Baseline:** Governed Multi-Provider Price Feed Daemon & Scheduled Polling Pipeline.
- **Regression Invariant:** 966 passed, 4 skipped (100% pass rate in 36.01s).
- **Current Milestone:** Local Operator Workbench (`python -m ironledger.cli web --port 8000`) actively serving live analytics with interactive Watchlist GUI, Lock Guard protection, on-demand price synchronization, and automated Diataxis documentation build pipeline.

## Completed Work
1. **Watchlist Configuration & Polling Automation (`config/prices.json`, `scripts/`)**:
   - `config/prices.json`: Configured target watchlist commodities (`AAPL`, `MSFT`, `GOOGL`, `BTC`, `ETH`, `EUR`) and quote currency (`USD`) with polling interval and fallback quotes.
   - `src/ironledger/prices/scraper_daemon.py`: Added `load_config_watchlist` to load targets directly from configuration or fallback to active portfolio ledger postings.
   - `src/ironledger/cli/__main__.py`: Added `ironledger prices poll` subcommand supporting `--symbols`, `--quote-currency`, `--config-dir`, and `--json`.
   - `scripts/poll-prices.ps1`: Automated price feed scraper execution script.
   - `scripts/poll-simplefin.ps1`: Automated SimpleFIN bank transaction sync script.
   - `scripts/setup-scheduled-tasks.ps1`: Windows Task Scheduler registration script managing hourly price sync and daily bank sync.

2. **Watchlist GUI, Lock Guard & Symbol Deletion (`web/src/`)**:
   - `WatchlistPanel.tsx`: Dedicated React component displaying all watchlist target pairs, exact rational fractions $(N/D)$, effective decimal rates, quote timestamps, provider badges, and live resolution status badges (`SUCCESS`, `RECIPROCAL`, `CIRCUIT_OPEN`).
   - **Lock Guard (Protected Mode):** Added safe-by-default Lock toggle preventing accidental symbol additions or deletions. Unlocking enables Edit Mode with visual indicators.
   - **Symbol Deletion:** Added delete actions per symbol row and wired `DELETE /api/analytics/watchlist/{symbol}` endpoint updating `config/prices.json`.
   - Integrated on-demand "Sync Watchlist" trigger button with spinner animation and live notification feedback.
   - Built inline "Add Symbol" form with custom base symbol, quote currency, and optional fallback rates.
   - Exposed `price_feed_audit` telemetry drawer rendering real-time resolution latencies and execution logs.

3. **Navigation & Cache Invalidation Hardening (`web/src/components/`, `src/ironledger/web/`)**:
   - `TopHUD.tsx`: Added quick navigation pills for `Staging`, `Holdings & Watchlist`, and `Cash Flow`.
   - `Sidebar.tsx`: Elevated `Portfolio & Watchlist` navigation under *Ledger & Valuation*.
   - `app.py`: Registered `NoCacheHtmlMiddleware` emitting `Cache-Control: no-cache, no-store, must-revalidate` on all HTML routes so browser cache never serves stale SPA bundles.

4. **Automated Documentation Build Pipeline (`scripts/build-docs.py`, `web/package.json`)**:
   - Created `scripts/build-docs.py` generating canonical Diataxis HTML documentation (`web/public/docs/index.html`).
   - Chained documentation build into `web/package.json` (`npm run build:docs && tsc && vite build`) so documentation is automatically validated and refreshed on every Vite build.
   - Live docs accessible at `/docs/index.html` via the TopHUD Docs button.

5. **Port 8000 Migration & Daemon Verification**:
   - Terminated legacy orphaned `ironledger-workbench` Docker container on port 8000.
   - Verified live server daemon running on `http://127.0.0.1:8000/`.
   - Verified REST endpoints (`/healthz`, `/readyz`, `/docs/index.html`, `/api/analytics/sankey`, `/api/analytics/portfolio`, `/api/analytics/watchlist`, `/api/analytics/prices/sync`).

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

