# IronLedger Project Status

## Active Goal
Portfolio Lot Matching, Cost Basis Tracking, and Capital Gains Valuation Subsystem (`C:\dev\IronLedger`).

## Milestone Status: Portfolio Lot Matching & Capital Gains Subsystem v0.13.0
- **Preceding Baseline:** Operator Workbench v0.12.0 Multi-Asset Valuation & Watchlist Lock Guard.
- **Regression Invariant:** 978 passed, 5 skipped (100% pass rate in 54.41s).
- **Current Milestone:** Phase 13 complete with exact rational cost basis tracking, FIFO/LIFO/HIFO lot matching reducers, SQLite projection tables (`open_lots`, `lot_disposal_allocations`), analytics REST endpoints, Form 8949 CSV export, and Operator Workbench Capital Gains Ledger UI.

## Completed Work
1. **Database Schema & Lot Matching Projections (`src/ironledger/db/schema/0017_lot_matching.sql`)**:
   - Added `open_lots` tracking remaining inventory quantity, unit cost numerator/denominator, basis residue, and source posting IDs.
   - Added `lot_disposal_allocations` recording immutable allocation records linking closing postings to liquidated lots with exact recognized gain/loss calculations.
   - Created `idx_open_lots_account_commodity_date` index for deterministic chronological traversal.

2. **Normalized Rational Lot Parser (`src/ironledger/valuation/models.py`)**:
   - Implemented `LotAnnotation` and `PostingLotSpec` models parsing exact unit costs (`{200.00 USD}`), total costs (`{{2000.00 USD}}`), and lot dates (`[2026-01-15]`).
   - Validates ISO-8601 calendar dates with leap-year handling and rejects negative or zero cost denominators.

3. **Deterministic Lot Matching Engine (`src/ironledger/valuation/lots.py`)**:
   - Built `LotProcessor` supporting `FIFO`, `LIFO`, and `HIFO` (cross-multiplication ordering without float division) matching strategies.
   - Preserves basis residue conservation ($\sum \text{allocated} + \text{remaining} = \text{original}$) across partial lot liquidations.
   - Enforces fail-closed validation on insufficient inventory.
   - Persists open lots and allocation records into SQLite projection tables.

4. **Portfolio Cache Invalidation & Valuation Engine (`src/ironledger/valuation/engine.py`)**:
   - Added `ValuationEngine.refresh_portfolio_cache` to recompute cost basis and unrealized gains from live open lots.
   - Formatted minor units with integer round-half-to-even tie-breaking.

5. **Analytics & Form 8949 Export Endpoints (`src/ironledger/web/routers/analytics.py`)**:
   - `GET /api/analytics/gains`: Realized gain/loss breakdown filterable by tax year, term (short-term vs long-term), account, and commodity.
   - `GET /api/analytics/lots`: Open lot inventory inspection with unrealized gain calculations.
   - `GET /api/analytics/gains/export`: Form 8949 CSV report generator with spreadsheet formula-injection sanitization (`=`, `+`, `-`, `@`, `\t`, `\r`).

6. **Operator Workbench Capital Gains Ledger UI (`web/src/components/CapitalGainsLedger.tsx`, `web/src/App.tsx`)**:
   - Created interactive Capital Gains Ledger view featuring summary KPI cards (Total Realized Gain, Short-Term Gain, Long-Term Gain, Open Basis).
   - Realized Gains table with holding period calculation, disposal date, proceeds, cost basis, and gain/loss status badges.
   - Open Tax Lots table displaying acquisition dates, open quantities, unit costs, and current basis.
   - On-demand Form 8949 CSV export button and tax year selector.
   - Wired navigation via Sidebar, TopHUD, and routing state.

7. **Phase 13 Exit Contract & AST Invariant Verification (`tests/test_phase13_exit_contract.py`)**:
   - Verified strict zero runtime `import beancount` across the entire codebase.
   - Verified zero floating-point division (`ast.Div`) across all valuation modules.
   - Validated end-to-end multi-lot disposal lifecycle and basis residue conservation.
   - Clean Vite production build verified (`✓ built in 23.32s`).

## Core Architectural Invariants Maintained
- **Plaintext Ground Truth:** Plaintext Beancount files remain the sole financial authority.
- **Decoupled Runtime:** Zero runtime `import beancount` enforced via static AST visitor.
- **Pure Integer Arithmetic:** Exact rational arithmetic without float representation or drift.
- **Cost Basis Conservation:** Exact integer balance conservation across partial lot liquidations.
- **Envelope Encryption:** AES-256-GCM with separate IV/auth tags and zero plaintext payload leakage.
- **Append-Only Immutability:** SQLite triggers guarding outbox, audit, mutation, and governance event streams.
- **Multi-Tenant Boundaries:** Relational composite keys and tenant registries enforcing strict ledger isolation.

## Next Action
Production deployment and continuous live monitoring.


