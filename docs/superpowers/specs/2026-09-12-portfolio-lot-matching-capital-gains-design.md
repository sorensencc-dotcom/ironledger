# Phase 13 Design Specification: Portfolio Lot Matching, Cost Basis & Capital Gains Subsystem

**Date:** 2026-09-12  
**Target Milestone:** IronLedger `v0.13.0`  
**Status:** APPROVED (Brainstorming Complete)

---

## 1. Executive Summary & Objectives

IronLedger requires comprehensive multi-asset cost-basis valuation, configurable lot tracking (FIFO, LIFO, HIFO, and Specific Identification), and holding period tax reporting (Short-Term vs. Long-Term capital gains/losses). 

This subsystem provides deterministic, pure integer rational accounting without floating-point representations or runtime dependencies on the Beancount core library.

### Core Goals
1. **Beancount Lot Ingestion**: Extract native lot cost annotations (`{cost, date, label}`) into projection tables.
2. **Deterministic Lot Reduction Pipeline**: Support FIFO (default), LIFO, and HIFO disposal strategies using Banker''s integer rational rounding.
3. **Holding Period & Tax Classification**: Track acquisition date, disposal date, holding period duration, and tax classification (Short-Term <= 365 days vs. Long-Term > 365 days).
4. **Dual Currency Tracking**: Anchor cost basis in functional reporting currency (USD) via historical price directives while preserving exact native lot amounts.
5. **Analytics API & Workbench UI**: Expose `/api/analytics/gains`, `/api/analytics/lots`, and `/api/analytics/gains/export` with a dedicated "Tax & Capital Gains" ledger view in the Operator Workbench.

---

## 2. Architectural Invariants

* **Zero-Float Arithmetic**: All proceeds, cost basis, and realized gains evaluate via integer numerator/denominator pairs (`convert_amount_rational`) with round-half-to-even tie-breaking.
* **AST Invariant**: Zero runtime `import beancount` across all modules, verified by AST inspection tests.
* **Deterministic Replay**: Rebuilding projections from plaintext ledger postings produces byte-identical lot allocation tables.
* **Failsafe Inventory Guards**: Disposals exceeding available inventory raise `InsufficientInventoryError` rather than fabricating negative lot states.

---

## 3. Data Model & Database Schema

### 3.1 `ledger_postings` Schema Extension
Add columns to `ledger_postings`:
* `cost_numerator INTEGER`: Exact rational numerator of per-unit acquisition cost.
* `cost_denominator INTEGER`: Exact rational denominator of per-unit acquisition cost.
* `cost_currency TEXT`: Denominated cost currency (e.g., `USD`, `EUR`).
* `lot_date TEXT`: Acquisition date (`YYYY-MM-DD`).
* `lot_label TEXT`: Optional lot identifier/tag.

### 3.2 Projection Tables

```sql
CREATE TABLE IF NOT EXISTS open_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id TEXT NOT NULL DEFAULT 'default',
    account TEXT NOT NULL,
    commodity TEXT NOT NULL,
    acquisition_date TEXT NOT NULL,
    remaining_units INTEGER NOT NULL,
    unit_scale INTEGER NOT NULL DEFAULT 4,
    cost_numerator INTEGER NOT NULL,
    cost_denominator INTEGER NOT NULL,
    cost_currency TEXT NOT NULL,
    functional_cost_basis_minor INTEGER NOT NULL,
    lot_label TEXT,
    created_posting_id INTEGER NOT NULL REFERENCES ledger_postings(id)
);

CREATE INDEX IF NOT EXISTS idx_open_lots_lookup 
ON open_lots (ledger_id, account, commodity, acquisition_date);

CREATE TABLE IF NOT EXISTS realized_capital_gains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id TEXT NOT NULL DEFAULT 'default',
    account TEXT NOT NULL,
    commodity TEXT NOT NULL,
    disposal_date TEXT NOT NULL,
    acquisition_date TEXT NOT NULL,
    units_disposed INTEGER NOT NULL,
    unit_scale INTEGER NOT NULL DEFAULT 4,
    holding_period_days INTEGER NOT NULL,
    term_classification TEXT NOT NULL CHECK(term_classification IN ('SHORT_TERM', 'LONG_TERM')),
    proceeds_minor_units INTEGER NOT NULL,
    cost_basis_minor_units INTEGER NOT NULL,
    realized_gain_minor_units INTEGER NOT NULL,
    currency TEXT NOT NULL,
    strategy_applied TEXT NOT NULL,
    closing_posting_id INTEGER NOT NULL REFERENCES ledger_postings(id)
);

CREATE INDEX IF NOT EXISTS idx_realized_gains_year 
ON realized_capital_gains (ledger_id, disposal_date, term_classification);
```

### 3.3 Enhanced `v_portfolio_holdings` SQL View
```sql
CREATE VIEW IF NOT EXISTS v_portfolio_holdings AS
WITH latest_prices AS (
    SELECT base_currency AS commodity, quote_currency AS currency,
           rate_numerator, rate_denominator, directive_date
    FROM price_history
    WHERE (base_currency, quote_currency, directive_date, id) IN (
        SELECT base_currency, quote_currency, MAX(directive_date), MAX(id)
        FROM price_history GROUP BY base_currency, quote_currency
    )
),
active_lots AS (
    SELECT commodity, cost_currency AS base_currency,
           SUM(remaining_units) AS total_units,
           SUM(functional_cost_basis_minor) AS total_cost_basis_minor_units
    FROM open_lots
    GROUP BY commodity, cost_currency
)
SELECT 
    a.commodity,
    a.total_units,
    a.total_cost_basis_minor_units,
    a.base_currency,
    COALESCE(lp.rate_numerator, 1) AS price_numerator,
    COALESCE(lp.rate_denominator, 1) AS price_denominator,
    CAST((a.total_units * COALESCE(lp.rate_numerator, 1)) / NULLIF(COALESCE(lp.rate_denominator, 1), 1) AS INTEGER) AS market_value_minor_units,
    CAST((a.total_units * COALESCE(lp.rate_numerator, 1)) / NULLIF(COALESCE(lp.rate_denominator, 1), 1) AS INTEGER) - a.total_cost_basis_minor_units AS unrealized_gain_minor_units
FROM active_lots a
LEFT JOIN latest_prices lp ON lp.commodity = a.commodity AND lp.currency = a.base_currency;
```

---

## 4. Lot Matching & Valuation Engine (`src/ironledger/valuation/lots.py`)

### 4.1 Queue Processing Algorithm
1. **Acquisition**: Positive unit movements append an `OpenLot` record with rational cost representation. If multi-currency, resolve historical exchange rate via `ValuationEngine.get_price(acquisition_date)` to populate `functional_cost_basis_minor`.
2. **Disposal**: Negative unit movements select lots based on configured strategy:
   * **`FIFO`**: Ordered by `acquisition_date ASC, id ASC`.
   * **`LIFO`**: Ordered by `acquisition_date DESC, id DESC`.
   * **`HIFO`**: Ordered by `(cost_numerator / cost_denominator) DESC, acquisition_date ASC`.
3. **Reduction & Splitting**: Match units against the queue until the disposition quantity is fully allocated. Partially matched lots decrement `remaining_units` in place.
4. **Calculations**:
   * Holding period: `disposal_date - acquisition_date` in days.
   * Term: `SHORT_TERM` (<= 365) or `LONG_TERM` (> 365).
   * Gains: Realized Gain = Proceeds - Cost Basis.

---

## 5. API Endpoints & Workbench Integration

### 5.1 REST API (`src/ironledger/web/routers/analytics.py`)
* `GET /api/analytics/gains`: Returns summary cards and list of closed lot disposal records with filtering by year, term, account, and commodity.
* `GET /api/analytics/lots`: Returns all active open lots per account and commodity.
* `GET /api/analytics/gains/export`: Generates an RFC 4180 CSV export suitable for tax reconciliation and IRS Form 8949 reporting.

### 5.2 Operator Workbench UI (`web/src/`)
* **Capital Gains & Tax Ledger (`CapitalGainsLedger.tsx`)**:
  * KPI summary cards: Total Net Gain/Loss, Short-Term Ordinary Gain, Long-Term Capital Gain, Total Proceeds.
  * Interactive filters: Tax Year, Term Classification, Search, and CSV Export.
  * Detailed closed lot event table with visual indicators for gain/loss and holding durations.
* **Holdings Table Accordion (`PortfolioPanel.tsx`)**:
  * Expandable rows displaying open lots backing each commodity position with individual cost basis and unrealized gain/loss.

---

## 6. Verification Strategy

1. **Unit Tests**:
   * `tests/test_valuation_lots.py`: Verify FIFO, LIFO, HIFO sorting, fractional lot splits, zero-cost lots, and boundary day calculations (365 vs 366 days).
   * `tests/test_ast_beancount_isolation.py`: Enforce zero runtime `beancount` imports in the valuation subsystem.
2. **Integration Tests**:
   * `tests/test_api_capital_gains.py`: Validate FastAPI endpoints, filters, error handling on inventory deficit, and CSV generation.
3. **Frontend Build Validation**:
   * Execute `npm run build` in `web/` to confirm zero TypeScript and Vite bundle errors.
