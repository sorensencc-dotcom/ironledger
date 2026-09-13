# Phase 13 Design Specification: Portfolio Lot Matching, Cost Basis & Capital Gains Subsystem

**Date:** 2026-09-12  
**Target Milestone:** IronLedger `v0.13.0`  
**Status:** Draft / In Review (Incorporating Tier 1 Review Changes)  
**Governance Scope:** Multi-Asset Inventory, Rational Valuation, Tax & Capital Gains Accounting

---

## 1. Executive Summary & Problem Definition

IronLedger requires a deterministic, local-first inventory and valuation engine capable of computing exact lot cost basis, multi-asset portfolio market values, and realized capital gains/losses.

### 1.1 Core Objectives
1. **Deterministic Beancount Lot Extraction**: Parse per-unit and total-cost Beancount lot annotations (`{cost CURRENCY, date, "label"}` or `{{total_cost CURRENCY}}`) into normalized integer rational components.
2. **Immutable Disposal Allocation Model**: Record dispositions as immutable many-to-one allocation records linking each closing posting to specific acquired lot slices.
3. **Configurable Matching Strategies**: Support First-In First-Out (`FIFO`, default), Last-In First-Out (`LIFO`), Highest-In First-Out (`HIFO`), and Specific Identification (`SPEC_ID`).
4. **Pure Integer Rational Accounting**: Enforce zero floating-point arithmetic across all currency conversions, cost basis calculations, and cross-multiplication comparisons.
5. **Dual Currency Tracking**: Maintain native lot currencies alongside functional reporting currency (e.g., USD) anchored by historical exchange rates.
6. **Auditable Tax & Form 8949 Reporting**: Provide holding period calculations, configurable jurisdiction tax boundaries, injection-safe CSV export, and an interactive Operator Workbench interface.

---

## 2. Core Architectural Invariants

1. **Zero-Float Invariant**: All monetary values, unit quantities, exchange rates, and cost basis allocations are evaluated using integer numerator/denominator pairs and Banker''s half-even integer rounding (`convert_amount_rational`).
2. **AST Isolation Invariant**: Zero runtime `import beancount` across the codebase. Enforced by `tests/test_ast_beancount_isolation.py`.
3. **Partitioned Inventory Boundary**: Lot inventory queues are partitioned strictly by `(ledger_id, account, commodity)`. Inventory cannot leak across ledger tenants or account boundaries.
4. **Deterministic Total Replay**: Given an identical set of ledger postings and price directives, replay produces identical `open_lots` and `lot_disposal_allocations` tables.
5. **Fail-Closed Inventory Integrity**: Dispositions exceeding available lot inventory immediately abort the transaction and raise `InsufficientInventoryError`. Negative inventory states are prohibited.

---

## 3. Quantity, Scale, and Rational Arithmetic Conventions

### 3.1 Scaled Integer Representation
All quantities and monetary amounts are stored as scaled integer minor units:
* **Currencies (Fiat)**: Standard `currency_scale = 2` (e.g., cents for USD/EUR) or `currency_scale = 4` (FX).
* **Commodities / Equities / Cryptocurrencies**: Configured per commodity in `config/commodities.json` (e.g., `AAPL` scale = 4, `BTC` scale = 8, `ETH` scale = 8). Default fallback is `unit_scale = 4`.
* **Quantity Conversion Formula**:
  $$\text{Units}_{\text{minor}} = \text{round\_half\_even}(\text{Units}_{\text{decimal}} \times 10^{\text{unit\_scale}})$$

### 3.2 Canonical Rational Fractions
Every price or per-unit cost is stored as a normalized fraction $\frac{N}{D}$:
* **Normalization**: $\gcd(N, D) = 1$ computed via Euclid''s algorithm on ingestion.
* **Positive Denominator**: $D > 0$ strictly enforced; the sign is held entirely in the numerator $N$.
* **Integer Bounds**: $N, D \in [-2^{63}, 2^{63}-1]$ for SQLite storage; Python evaluation utilizes arbitrary-precision integers to prevent overflow during intermediate products.

### 3.3 Zero-Float Exact Ratio Comparison (HIFO)
To order lots by per-unit cost without floating-point division:
$$\frac{N_a}{D_a} > \frac{N_b}{D_b} \iff N_a \cdot D_b > N_b \cdot D_a \quad (\text{since } D_a, D_b > 0)$$
Deterministic tie-breaking sorts by:
1. Cross-multiplied unit cost descending: $(N_a \cdot D_b > N_b \cdot D_a)$
2. Acquisition date ascending: `acquisition_date ASC`
3. Posting sequence / lot ID ascending: `id ASC`

### 3.4 Scale-Aware Money Conversion Formula
When multiplying a scaled quantity by a rational rate to produce money minor units in a target scale:
$$\text{Money}_{\text{minor}} = \text{div\_round\_even}\left( \text{Units}_{\text{minor}} \cdot N_{\text{rate}} \cdot 10^{\Delta \text{scale}}, D_{\text{rate}} \right)$$
where $\Delta \text{scale} = \text{target\_scale} - \text{unit\_scale}$, evaluated via `convert_amount_rational`.

---

## 4. Multi-Currency and Functional Cost Basis Model

Each ledger tenant defines a canonical `functional_currency` in `config/ledger.json` (e.g., `"USD"`).

1. **Native Lot Cost**: Represents the price per unit in the transaction currency (e.g., $150.00\text{ EUR}$ per share of SAP).
2. **Functional Cost Basis**: The acquisition cost converted to the ledger''s functional currency at the exact historical acquisition date:
   $$\text{Functional Unit Cost} = \text{Native Unit Cost} \times \text{Rate}_{\text{Native}\to\text{Functional}}(\text{acquisition\_date})$$
3. **Disposal Proceeds**:
   * Native Proceeds: $\text{Units Disposed} \times \text{Disposal Price}_{\text{Native}}$
   * Functional Proceeds: Converted to functional currency at disposal date exchange rate.
4. **Realized Capital Gain**:
   $$\text{Realized Gain}_{\text{Functional}} = \text{Functional Proceeds} - \text{Functional Cost Basis}$$

If no price directive exists on `acquisition_date`, the engine checks `max_staleness_days` (default: 30 days). If no valid directive is found within the threshold, it raises `MissingPriceDirectiveError`.

---

## 5. Database Schema & Projection Models

### 5.1 `ledger_postings` Extensions
```sql
ALTER TABLE ledger_postings ADD COLUMN cost_numerator INTEGER;
ALTER TABLE ledger_postings ADD COLUMN cost_denominator INTEGER;
ALTER TABLE ledger_postings ADD COLUMN cost_currency TEXT;
ALTER TABLE ledger_postings ADD COLUMN lot_date TEXT;
ALTER TABLE ledger_postings ADD COLUMN lot_label TEXT;
```

### 5.2 `open_lots` Table
Represents active unliquidated inventory slices:
```sql
CREATE TABLE IF NOT EXISTS open_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id TEXT NOT NULL DEFAULT 'default',
    account TEXT NOT NULL,
    commodity TEXT NOT NULL,
    acquisition_date TEXT NOT NULL,
    original_units_minor INTEGER NOT NULL,
    remaining_units_minor INTEGER NOT NULL,
    unit_scale INTEGER NOT NULL DEFAULT 4,
    native_cost_numerator INTEGER NOT NULL,
    native_cost_denominator INTEGER NOT NULL,
    native_cost_currency TEXT NOT NULL,
    functional_currency TEXT NOT NULL DEFAULT 'USD',
    functional_unit_cost_numerator INTEGER NOT NULL,
    functional_unit_cost_denominator INTEGER NOT NULL,
    functional_cost_basis_minor INTEGER NOT NULL,
    lot_label TEXT,
    created_posting_id INTEGER NOT NULL REFERENCES ledger_postings(id),
    created_tx_id INTEGER NOT NULL REFERENCES ledger_transactions(id),
    CONSTRAINT chk_positive_units CHECK (remaining_units_minor >= 0),
    CONSTRAINT chk_valid_denominator CHECK (native_cost_denominator > 0 AND functional_unit_cost_denominator > 0)
);

CREATE INDEX IF NOT EXISTS idx_open_lots_search 
ON open_lots (ledger_id, account, commodity, remaining_units_minor, acquisition_date);
```

### 5.3 `lot_disposal_allocations` Table (Realized Capital Gains)
Immutable record of each allocation matching a disposal posting to an acquired lot slice:
```sql
CREATE TABLE IF NOT EXISTS lot_disposal_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id TEXT NOT NULL DEFAULT 'default',
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
    native_cost_basis_minor INTEGER NOT NULL,
    native_realized_gain_minor INTEGER NOT NULL,
    native_currency TEXT NOT NULL,
    
    -- Functional reporting currency values
    functional_proceeds_minor INTEGER NOT NULL,
    functional_cost_basis_minor INTEGER NOT NULL,
    functional_realized_gain_minor INTEGER NOT NULL,
    functional_currency TEXT NOT NULL DEFAULT 'USD',
    
    -- Audit & Provenance
    strategy_applied TEXT NOT NULL CHECK(strategy_applied IN ('FIFO', 'LIFO', 'HIFO', 'SPEC_ID')),
    requested_lot_identifier TEXT,
    open_lot_id INTEGER NOT NULL REFERENCES open_lots(id),
    closing_posting_id INTEGER NOT NULL REFERENCES ledger_postings(id),
    closing_tx_id INTEGER NOT NULL REFERENCES ledger_transactions(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    CONSTRAINT chk_positive_disposed CHECK (units_disposed_minor > 0)
);

CREATE INDEX IF NOT EXISTS idx_allocations_tax_reporting 
ON lot_disposal_allocations (ledger_id, disposal_date, term_classification, commodity);
```

---

## 6. Lot Matching & Reduction Algorithm (`src/ironledger/valuation/lots.py`)

### 6.1 Transaction Ordering & Deterministic Replay
Postings are processed in strict deterministic sequence:
$$\text{Order Key} = (\text{tx\_date ASC}, \text{tx\_sequence\_num ASC}, \text{posting\_index ASC}, \text{posting\_id ASC})$$

### 6.2 Specific Identification (`SPEC_ID`) Specification
When a disposition posting specifies an explicit lot reference (via posting metadata `lot_label: "..."` or date/cost matching):
1. **Query Candidate Lot**: Locate matching `open_lots` with `ledger_id = ? AND account = ? AND commodity = ? AND remaining_units_minor > 0 AND (lot_label = ? OR (acquisition_date = ? AND native_cost_numerator = ?))`.
2. **Validation**:
   * If candidate lot is found and `candidate.remaining_units_minor >= disposal_units`: allocate fully from specified lot.
   * If candidate lot is found but `candidate.remaining_units_minor < disposal_units`: allocate all available units from candidate lot; allocate remainder using secondary fallback strategy (e.g., FIFO) and log `SPEC_ID_PARTIAL_FALLBACK` in audit metadata.
   * If no candidate lot matches: if strict mode is ON, raise `UnresolvedLotSpecificationError`; if strict mode is OFF, fall back to default strategy and log warning.

### 6.3 In-Memory Reducer & Atomic Database Replay
During projection sync:
1. `BEGIN IMMEDIATE` transaction.
2. `DELETE FROM lot_disposal_allocations WHERE ledger_id = ?` and `DELETE FROM open_lots WHERE ledger_id = ?`.
3. Process chronological postings in memory:
   * **Acquisitions ($Q > 0$)**: Insert `open_lots` row.
   * **Internal Account Transfers ($A_1 \to A_2$)**: Preserve lot acquisition date, original cost basis, and provenance ID while moving remaining units from source queue to destination queue.
   * **Disposals ($Q < 0$)**: Execute lot selection, decrement `remaining_units_minor`, and insert immutable `lot_disposal_allocations` rows.
4. `COMMIT` transaction.

---

## 7. Holdings Valuation Table & Refresh Procedure

Because SQLite lacks native banker''s rounding in standard SQL `CAST`, portfolio holdings are materialized into a dedicated query table `portfolio_holdings_cache` refreshed by the valuation engine after every projection sync:

```sql
CREATE TABLE IF NOT EXISTS portfolio_holdings_cache (
    ledger_id TEXT NOT NULL DEFAULT 'default',
    account TEXT NOT NULL,
    commodity TEXT NOT NULL,
    total_units_minor INTEGER NOT NULL,
    unit_scale INTEGER NOT NULL DEFAULT 4,
    functional_currency TEXT NOT NULL DEFAULT 'USD',
    total_cost_basis_minor INTEGER NOT NULL,
    latest_price_numerator INTEGER NOT NULL,
    latest_price_denominator INTEGER NOT NULL,
    market_value_minor INTEGER NOT NULL,
    unrealized_gain_minor INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    PRIMARY KEY (ledger_id, account, commodity)
);
```

The refresh procedure executes in Python using `convert_amount_rational` to guarantee 100% exact Banker''s rounding without SQL truncation errors.

---

## 8. REST API & Export Specification

### 8.1 API Endpoints
* `GET /api/analytics/gains`:
  * Query parameters: `ledger_id`, `year` (optional `YYYY`), `term` (`SHORT_TERM` | `LONG_TERM` | `ALL`), `commodity`, `account`, `limit` (default: 100, max: 1000), `offset`.
  * Response Schema:
    ```json
    {
      "ledger_id": "default",
      "functional_currency": "USD",
      "summary": {
        "total_realized_gain_minor": 145020,
        "short_term_gain_minor": 45020,
        "long_term_gain_minor": 100000,
        "total_proceeds_minor": 1250000,
        "total_cost_basis_minor": 1104980
      },
      "allocations": [
        {
          "id": 101,
          "account": "Assets:Brokerage:Schwab",
          "commodity": "AAPL",
          "disposal_date": "2026-08-15",
          "acquisition_date": "2025-02-10",
          "units_disposed_minor": 100000,
          "unit_scale": 4,
          "holding_period_days": 551,
          "term_classification": "LONG_TERM",
          "functional_proceeds_minor": 220000,
          "functional_cost_basis_minor": 180000,
          "functional_realized_gain_minor": 40000,
          "strategy_applied": "FIFO"
        }
      ]
    }
    ```
* `GET /api/analytics/gains/export`: Returns RFC 4180 CSV attachment.

### 8.2 Form 8949 CSV Column Contract & Formula Injection Mitigation
CSV columns:
`Description,Date_Acquired,Date_Sold,Proceeds_USD,Cost_Basis_USD,Gain_Loss_USD,Holding_Period_Days,Term_Classification,Adjustment_Code,Adjustment_Amount_USD,Form_8949_Box,Covered_Status`

**Formula Injection Mitigation**: Any string value starting with `=`, `+`, `-`, `@`, `\t`, or `\r` is sanitized by prefixing a single quote `'` before CSV serialization.

---

## 9. Verification & Test Plan

1. **Unit Tests (`tests/test_valuation_lots.py`)**:
   * Exact rational Banker''s rounding and cross-multiplication for HIFO.
   * Multi-currency cost basis conversions across historical exchange rates.
   * Exact FIFO, LIFO, HIFO, and SPEC_ID lot reduction permutations.
   * Partial lot splits and remainder precision tracking.
   * Day boundary conditions (365 vs 366 days) with configurable tax threshold policy.
   * Insufficient inventory fail-closed assertions.
2. **Integration & API Tests (`tests/test_api_capital_gains.py`)**:
   * Multi-tenant query isolation (`ledger_id`).
   * CSV export format validation and CSV formula injection sanitizer checks.
3. **AST Isolation & Static Analysis**:
   * Zero floating-point division verification (`/` on non-integers).
   * Zero runtime `beancount` imports verification.
4. **UI Compilation Verification**:
   * `npm run build` in `web/` with zero TypeScript errors.
