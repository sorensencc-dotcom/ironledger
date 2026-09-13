# Phase 13 Design Specification: Portfolio Lot Matching, Cost Basis & Capital Gains Subsystem

**Date:** 2026-09-12  
**Target Milestone:** IronLedger `v0.13.0`  
**Status:** Draft / Complete Design Resolution (Ready for Sign-Off)  
**Governance Scope:** Multi-Asset Inventory, Rational Valuation, Tax & Capital Gains Accounting

---

## 1. Executive Summary & Problem Definition

IronLedger requires a deterministic, local-first inventory and valuation engine capable of computing exact lot cost basis, multi-asset portfolio market values, and realized capital gains/losses.

Beancount plaintext files remain the sole accounting ground truth; SQLite serves as a deterministic, disposable projection. This specification establishes mathematical invariants, conservation laws, multi-currency valuation rules, and tenant authorization boundaries for lot accounting.

---

## 2. Core Architectural Invariants & Conservation Laws

### 2.1 Pure Integer Rational Invariant (Zero-Float)
All monetary quantities, unit amounts, exchange rates, and cost basis allocations are evaluated using exact integer numerator/denominator pairs and Banker''s half-even integer rounding (`convert_amount_rational`). Zero floating-point arithmetic is permitted in any valuation or lot calculation path.

### 2.2 Cost Basis Conservation Law
For any open lot partially liquidated across $n$ disposal allocations:
$$\sum_{i=1}^{n} \text{functional\_cost\_basis\_minor}_i + \text{remaining\_lot\_basis\_minor} = \text{original\_functional\_cost\_basis\_minor}$$
The final allocation slice absorbs any $\pm 1$ minor unit rounding residue, guaranteeing zero basis leakage.

### 2.3 Realized Gain Invariant
$$\text{functional\_realized\_gain\_minor} = \text{functional\_proceeds\_minor} - \text{functional\_cost\_basis\_minor}$$
Evaluated on rounded functional integer minor units to guarantee consistency between individual allocation records and aggregate financial reports.

### 2.4 Partitioned Inventory & Tenant Boundary
Lot inventory queues are partitioned strictly by `(ledger_id, account, commodity)`. Inventory cannot leak across ledger tenants or account boundaries.

### 2.5 Fail-Closed Inventory Integrity
Dispositions exceeding available lot inventory immediately abort the transaction and raise `InsufficientInventoryError`. Negative inventory states (short positions) are prohibited in Phase 13.

### 2.6 AST Isolation
Zero runtime `import beancount` across the codebase, enforced by static AST analysis.

---

## 3. Quantity, Scale, and Rational Arithmetic Conventions

### 3.1 Scaled Integer Representation
* **Currencies (Fiat)**: Standard `currency_scale = 2` (cents for USD/EUR) or `currency_scale = 4` (FX).
* **Commodities / Equities / Cryptocurrencies**: Configured per commodity in `config/commodities.json` (e.g., `AAPL` scale = 4, `BTC` scale = 8). Default fallback is `unit_scale = 4`.
* **Quantity Conversion Formula**:
  $$\text{Units}_{\text{minor}} = \text{round\_half\_even}(\text{Units}_{\text{decimal}} \times 10^{\text{unit\_scale}})$$

### 3.2 Canonical Rational Fractions
Every price or per-unit cost is stored as a normalized fraction $\frac{N}{D}$:
* **Normalization**: $\gcd(N, D) = 1$ via Euclid''s algorithm on ingestion.
* **Positive Denominator**: $D > 0$ strictly enforced; sign is held entirely in $N$.
* **Integer Bounds**: Stored as 64-bit signed integers in SQLite; evaluated as arbitrary-precision integers in Python.

### 3.3 Zero-Float Ratio Comparison (HIFO Ordering)
For multi-currency lots, HIFO sorts by **functional per-unit cost** at acquisition date without division:
$$\frac{N_{a, \text{func}}}{D_{a, \text{func}}} > \frac{N_{b, \text{func}}}{D_{b, \text{func}}} \iff N_{a, \text{func}} \cdot D_{b, \text{func}} > N_{b, \text{func}} \cdot D_{a, \text{func}}$$
Deterministic tie-breaking:
1. Cross-multiplied functional unit cost descending
2. Acquisition date ascending (`acquisition_date ASC`)
3. Stable `lot_key` ascending (`lot_key ASC`)

### 3.4 Scale-Aware Money Conversion
$$\text{Money}_{\text{minor}} = \text{div\_round\_even}\left( \text{Units}_{\text{minor}} \cdot N_{\text{rate}} \cdot 10^{\Delta \text{scale}}, D_{\text{rate}} \right)$$
where $\Delta \text{scale} = \text{target\_scale} - \text{unit\_scale}$.

---

## 4. Multi-Currency and Cost Annotation Normalization

### 4.1 Cost Annotation Parsing
* **Per-Unit Cost (`{cost CURRENCY}`)**:
  $$N_{\text{native}} = \text{cost\_minor}, \quad D_{\text{native}} = 10^{\text{cost\_scale}}$$
* **Total Cost (`{{total_cost CURRENCY}}`)**:
  $$N_{\text{native}} = \text{total\_cost\_minor} \cdot 10^{\text{unit\_scale}}$$
  $$D_{\text{native}} = \text{posting\_units\_minor} \cdot 10^{\text{cost\_scale}}$$
  Normalized via $\gcd(N_{\text{native}}, D_{\text{native}})$. Missing cost dates default to posting date. Malformed annotations with zero units raise `MalformedLotAnnotationError`.

### 4.2 Multi-Currency Gain/Loss Semantics
* **Native Proceeds & Cost**: Stored in their respective transaction currencies (`native_proceeds_currency`, `native_cost_currency`).
* **Native Realized Gain**: Populated **only** when `native_proceeds_currency == native_cost_currency`; otherwise stored as `NULL` to avoid nonsensical cross-currency subtraction.
* **Functional Valuation**: All lots and disposals are converted to `functional_currency` (configured per ledger in `config/ledger.json`, e.g., `USD`) using historical directives from `price_history`. Missing exchange rates within `max_staleness_days` raise `MissingPriceDirectiveError`.

---

## 5. Stable Identifiers, Lineage & Disposable Projections

To preserve auditability while treating SQLite as a disposable projection:

### 5.1 Content-Addressed Lot & Allocation Keys
* **Stable Lot Key**:
  $$\text{lot\_key} = \text{sha256}(\text{ledger\_id} : \text{account} : \text{commodity} : \text{acquisition\_date} : N_{\text{native}} : D_{\text{native}} : \text{curr} : \text{created\_posting\_id})$$
* **Stable Allocation Key**:
  $$\text{allocation\_key} = \text{sha256}(\text{ledger\_id} : \text{lot\_key} : \text{closing\_posting\_id} : \text{units\_disposed\_minor})$$

### 5.2 Transfer Lineage
When moving assets between internal accounts ($A_1 \to A_2$), the destination lot in $A_2$ inherits:
* `source_lot_key = A_1.lot_key`
* `origin_account = A_1.account`
* Original `acquisition_date`, `functional_unit_cost_numerator`, and `functional_unit_cost_denominator`.

---

## 6. Database Schema

### 6.1 `open_lots` Table
```sql
CREATE TABLE IF NOT EXISTS open_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_key TEXT NOT NULL UNIQUE,
    ledger_id TEXT NOT NULL,
    account TEXT NOT NULL,
    commodity TEXT NOT NULL,
    acquisition_date TEXT NOT NULL,
    original_units_minor INTEGER NOT NULL,
    remaining_units_minor INTEGER NOT NULL,
    unit_scale INTEGER NOT NULL DEFAULT 4,
    native_cost_numerator INTEGER NOT NULL,
    native_cost_denominator INTEGER NOT NULL,
    native_cost_currency TEXT NOT NULL,
    functional_currency TEXT NOT NULL,
    functional_unit_cost_numerator INTEGER NOT NULL,
    functional_unit_cost_denominator INTEGER NOT NULL,
    functional_cost_basis_minor INTEGER NOT NULL,
    lot_label TEXT,
    source_lot_key TEXT,
    origin_account TEXT,
    created_posting_id INTEGER NOT NULL REFERENCES ledger_postings(id),
    created_tx_id INTEGER NOT NULL REFERENCES ledger_transactions(id),
    CONSTRAINT chk_positive_units CHECK (remaining_units_minor >= 0),
    CONSTRAINT chk_valid_denominator CHECK (native_cost_denominator > 0 AND functional_unit_cost_denominator > 0)
);

CREATE INDEX IF NOT EXISTS idx_open_lots_search 
ON open_lots (ledger_id, account, commodity, remaining_units_minor, acquisition_date);
```

### 6.2 `lot_disposal_allocations` Table
```sql
CREATE TABLE IF NOT EXISTS lot_disposal_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_key TEXT NOT NULL UNIQUE,
    ledger_id TEXT NOT NULL,
    account TEXT NOT NULL,
    commodity TEXT NOT NULL,
    disposal_date TEXT NOT NULL,
    acquisition_date TEXT NOT NULL,
    units_disposed_minor INTEGER NOT NULL,
    unit_scale INTEGER NOT NULL DEFAULT 4,
    holding_period_days INTEGER NOT NULL,
    term_classification TEXT NOT NULL CHECK(term_classification IN ('SHORT_TERM', 'LONG_TERM')),
    
    -- Native currency values
    native_proceeds_minor INTEGER NOT NULL,
    native_proceeds_currency TEXT NOT NULL,
    native_cost_basis_minor INTEGER NOT NULL,
    native_cost_currency TEXT NOT NULL,
    native_realized_gain_minor INTEGER, -- NULL if proceeds and cost currencies differ
    
    -- Functional reporting currency values
    functional_proceeds_minor INTEGER NOT NULL,
    functional_cost_basis_minor INTEGER NOT NULL,
    functional_realized_gain_minor INTEGER NOT NULL,
    functional_currency TEXT NOT NULL,
    
    -- Provenance & Strategy
    strategy_applied TEXT NOT NULL CHECK(strategy_applied IN ('FIFO', 'LIFO', 'HIFO', 'SPEC_ID', 'SPEC_ID_PARTIAL_FIFO')),
    requested_lot_identifier TEXT,
    open_lot_key TEXT NOT NULL REFERENCES open_lots(lot_key),
    closing_posting_id INTEGER NOT NULL REFERENCES ledger_postings(id),
    closing_tx_id INTEGER NOT NULL REFERENCES ledger_transactions(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    CONSTRAINT chk_positive_disposed CHECK (units_disposed_minor > 0)
);

CREATE INDEX IF NOT EXISTS idx_allocations_tax 
ON lot_disposal_allocations (ledger_id, disposal_date, term_classification, commodity);
```

### 6.3 Materialized `portfolio_holdings_cache` Table
Refreshed after each projection sync via Python `ValuationEngine` with exact Banker''s rounding:
```sql
CREATE TABLE IF NOT EXISTS portfolio_holdings_cache (
    ledger_id TEXT NOT NULL,
    account TEXT NOT NULL,
    commodity TEXT NOT NULL,
    total_units_minor INTEGER NOT NULL,
    unit_scale INTEGER NOT NULL DEFAULT 4,
    functional_currency TEXT NOT NULL,
    total_cost_basis_minor INTEGER NOT NULL,
    latest_price_numerator INTEGER NOT NULL,
    latest_price_denominator INTEGER NOT NULL,
    market_value_minor INTEGER NOT NULL,
    unrealized_gain_minor INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    PRIMARY KEY (ledger_id, account, commodity)
);
```

---

## 7. Matching Algorithms & Specific Identification Strictness

### 7.1 Specific Identification (`SPEC_ID`) Rule
* **Strict Mode (Default: `spec_id_strict = true`)**: If a posting references a specific lot label or date/cost annotation:
  1. The engine attempts to match the exact `open_lot`.
  2. If the candidate lot has insufficient units or cannot be resolved, projection sync **aborts immediately** with `UnresolvedLotSpecificationError` or `InsufficientLotInventoryError`.
* **Permissive Fallback Mode (`spec_id_strict = false`)**: If enabled in configuration, any remaining unallocated units fall back to FIFO, and `strategy_applied` is explicitly set to `SPEC_ID_PARTIAL_FIFO` on the resulting allocation record.

### 7.2 Deterministic Ordering Sequence
Postings are processed in strict chronological order:
$$\text{Order Key} = (\text{tx\_date ASC}, \text{tx\_sequence\_num ASC}, \text{posting\_index ASC}, \text{posting\_id ASC})$$

---

## 8. Authorization, REST API & Tax Export Contracts

### 8.1 API Authorization
All analytics endpoints enforce tenant boundary checks via `ironledger.auth` / `ironledger.rbac`. The caller''s authenticated context must possess read permissions for the specified `ledger_id`. Arbitrary client requests for unauthorized `ledger_id` values return `403 Forbidden`.

### 8.2 Endpoints (`src/ironledger/web/routers/analytics.py`)
* `GET /api/analytics/gains`:
  * Query parameters: `ledger_id`, `year` (optional `YYYY`), `term` (`SHORT_TERM` | `LONG_TERM` | `ALL`), `commodity`, `account`, `limit` (max 1000), `offset`.
* `GET /api/analytics/lots`: Returns active open lots filtered by `ledger_id`, `account`, and `commodity`.
* `GET /api/analytics/gains/export`: Streams CSV export.

### 8.3 Form 8949 CSV Contract & Formula Injection Sanitization
**Columns**:
`Description,Date_Acquired,Date_Sold,Proceeds,Cost_Basis,Gain_Loss,Functional_Currency,Holding_Period_Days,Term_Classification,Adjustment_Code,Adjustment_Amount,Form_8949_Box,Covered_Status`

* **Default Classifications**:
  * `Adjustment_Code`: `""`
  * `Adjustment_Amount`: `0.00`
  * `Form_8949_Box`: `"B"` (Short-term noncovered) / `"E"` (Long-term noncovered)
  * `Covered_Status`: `"NONCOVERED"`
* **Formula Injection Mitigation**: Any field value beginning with `=`, `+`, `-`, `@`, `\t`, or `\r` is sanitized by prepending a single quote `'`.

---

## 9. Operational & Edge-Case Constraints

1. **Concurrency**: SQLite `BEGIN IMMEDIATE` locks the database during projection refresh, preventing concurrent sync races.
2. **Missing Valuation Data**: If disposal date exchange rate is missing, checks `max_staleness_days`; fails closed with `MissingPriceDirectiveError` if outside window.
3. **Pagination & Limits**: REST queries enforce `limit <= 1000`; CSV export streams up to 100,000 rows.
4. **Corporate Actions & Fees**: Brokerage fee postings are booked to expense accounts; lot basis is tracked net or gross based on posting structure. Stock splits/mergers must be booked as disposal/reacquisition transactions in Beancount source files.

---

## 10. Verification Strategy

1. **Unit Tests (`tests/test_valuation_lots.py`)**:
   * Exact Banker''s rounding and cross-multiplication for HIFO.
   * Basis conservation law across multi-lot partial splits ($\sum \text{allocations} + \text{remaining} = \text{original}$).
   * Multi-currency cost basis conversions and NULL native gain checks.
   * Strict SPEC_ID rejection on insufficient lot inventory.
   * Day boundary conditions (365 vs 366 days).
2. **Integration & Security Tests (`tests/test_api_capital_gains.py`)**:
   * RBAC / tenant isolation checks on `ledger_id`.
   * CSV export format validation and formula injection sanitization.
3. **AST Isolation**:
   * Static AST verification enforcing zero runtime `beancount` imports.
4. **UI Compilation**:
   * Verify clean Vite bundle compilation with zero TypeScript errors.
