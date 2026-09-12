# IronLedger Project Status

## Active Goal
Phase 12: High-Availability Failover Fabric, Cross-Region Disaster Recovery & Tenant Key Rotation (`C:\dev\IronLedger`).

## Milestone Status: Governed Price Feed Daemon & Analytics Suite Delivered
- **Preceding Baseline:** Phase 12 core engineering complete (version `v0.12.0`).
- **Regression Invariant:** 963 passed, 5 skipped (100% pass rate in 56.33s).
- **Current Milestone:** Governed Multi-Provider Price Feed Daemon, Dual-Persistence Engine, Cash-Flow Sankey, Portfolio Holdings View, and Shared FastMCP Registration Delivered.

## Completed Work
1. **Governed Multi-Provider Commodity Price Feed Daemon (`src/ironledger/prices/`)**:
   - `models.py`: Exact rational price directive parser (`PriceDirectiveRecord`) using pure $(N/D)$ integer representation, GCD canonicalization, and zero IEEE-754 floats.
   - `providers/`: Decoupled `BasePriceProvider` with token bucket rate limiters, circuit breakers, and `safe_json_loads(parse_float=str)` ingress protection.
   - `router.py`: `PriceCascadeRouter` with deterministic tiered fallbacks, reciprocal rate calculation, and 7-day UTC staleness boundaries.
   - `scraper_daemon.py`: `PriceScraperDaemon` managing portfolio discovery, atomic plain-text `prices.beancount` `fsync`, and SQLite `price_history` projection commits.
   - `0016_price_feed_audit.sql`: Audit trail logging outbound quote resolution statuses and latencies.
2. **Cash-Flow & Portfolio Analytics Suite**:
   - SQL views `0014_cash_flow_sankey.sql` and `0015_investment_portfolio.sql` for directed cash flow streams and multi-asset cost basis vs. mark-to-market valuation.
   - Frontend components `CashFlowSankey.tsx` (D3 visualizer) and `HoldingsView.tsx` (asset allocation table) mounted in Operator Workbench shell and Command Palette (`Ctrl+K`).
3. **Shared FastMCP Registration (`src/ironledger/mcp/tools.py` & `C:\dev\.mcp.json`)**:
   - Registered `get_cash_flow_sankey`, `get_portfolio_holdings`, and `trigger_price_sync` FastMCP tools for shared use across Helix and coding agents.

## Core Architectural Invariants Maintained
- **Plaintext Ground Truth:** Plaintext Beancount files remain the sole financial authority.
- **Decoupled Runtime:** Zero runtime `import beancount` enforced via static AST visitor.
- **Pure Integer Arithmetic:** Exact rational arithmetic without float representation or drift.
- **Envelope Encryption:** AES-256-GCM with separate IV/auth tags and zero plaintext payload leakage.
- **Append-Only Immutability:** SQLite triggers guarding outbox, audit, mutation, and governance event streams.
- **Multi-Tenant Boundaries:** Relational composite keys and tenant registries enforcing strict ledger isolation.
- **Fenced HA Quorum:** Monotonic terms and randomized fence tokens preventing split-brain dual primary operations.

## Next Action
Sealed release of Phase 12 milestone (`v0.12.0`) and price feed daemon integration.
