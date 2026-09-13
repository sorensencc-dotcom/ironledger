# Phase 13 Design Specification: Portfolio Lot Matching, Cost Basis & Capital Gains Subsystem

**Date:** 2026-09-12  
**Target Milestone:** IronLedger `v0.13.0`  
**Status:** Approved Specification (Final Sign-Off Ready)  
**Governance Scope:** Multi-Asset Inventory, Rational Valuation, Tax & Capital Gains Accounting

---

## 1. Executive Summary & Problem Definition

IronLedger requires a deterministic, local-first inventory and valuation engine capable of computing exact lot cost basis, multi-asset portfolio market values, and realized capital gains/losses.

Beancount plaintext files remain the sole accounting ground truth; SQLite serves as a deterministic, disposable projection. This specification establishes mathematical invariants, conservation laws, multi-currency valuation rules, tenant authorization boundaries, and auditable lineage.

---

## 2. Core Architectural Invariants & Conservation Laws

### 2.1 Pure Integer Rational Invariant (Zero-Float)
All monetary quantities, unit amounts, exchange rates, and cost basis allocations are evaluated using exact integer numerator/denominator pairs and Banker''s half-even integer rounding (`convert_amount_rational`). Zero floating-point arithmetic is permitted in any valuation or lot calculation path.

### 2.2 Cost Basis Conservation Law
For any open lot liquidated across $n$ disposal allocation slices:
$$\sum_{i=1}^{n} \text{functional\_cost\_basis\_minor}_i + \text{remaining\_functional\_cost\_basis\_minor} = \text{original\_functional\_cost\_basis\_minor}$$
The final allocation slice disposing of the remaining units absorbs any $\pm 1$ minor unit rounding residue, guaranteeing zero basis leakage across partial fills.

### 2.3 Realized Gain Invariant
$$\text{functional\_realized\_gain\_minor} = \text{functional\_proceeds\_minor} - \text{functional\_cost\_basis\_minor}$$
Evaluated on rounded functional integer minor units to guarantee consistency between individual allocation records and aggregate financial reports.

### 2.4 Partitioned Inventory & Tenant Boundary
Lot inventory queues are partitioned strictly by `(ledger_id, account, commodity)`. Inventory cannot leak across ledger tenants or account boundaries.

### 2.5 Fail-Closed Inventory Integrity
Dispositions exceeding available lot inventory immediately abort the transaction and raise `InsufficientInventoryError`. Negative inventory states (short positions) are prohibited in Phase 13.

### 2.6 Global Zero-Beancount AST Invariant
Zero runtime `import beancount` across the entire codebase, including ingestion, projection, valuation, and web modules. Ingestion uses IronLedger''s native zero-dependency AST parser and token scanner. Enforced by `tests/test_ast_beancount_isolation.py`.

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

## 4. Multi-Currency, Fees, and Normalization Rules

### 4.1 Cost Annotation Parsing
* **Per-Unit Cost (`{cost CURRENCY}`)**:
  $$N_{\text{native}} = \text{cost\_minor}, \quad D_{\text{native}} = 10^{\text{cost\_scale}}$$
* **Total Cost (`{{total_cost CURRENCY}}`)**:
  $$N_{\text{native}} = \text{total\_cost\_minor} \cdot 10^{\text{unit\_scale}}$$
  $$D_{\text{native}} = \text{posting\_units\_minor} \cdot 10^{\text{cost\_scale}}$$
  Normalized via $\gcd(N_{\text{native}}, D_{\text{native}})$. Missing cost dates default to posting date. Malformed annotations with zero units raise `MalformedLotAnnotationError`.

### 4.2 Brokerage Fees & Net Proceeds Treatment
When a disposal transaction includes brokerage commissions (e.g. `Expenses:Brokerage:Commissions`):
1. **Gross Proceeds**: $\text{units\_disposed} \times \text{disposal\_price}$.
2. **Allocated Fee**: Brokerage expense allocated pro-rata across disposed commodities in the transaction.
3. **Net Proceeds**: $\text{functional\_proceeds\_minor} = \text{gross\_proceeds\_minor} - \text{allocated\_fee\_minor}$.
4. Tax reporting utilizes Net Proceeds in accordance with IRS Form 8949 standards.

### 4.3 Multi-Currency Gain/Loss Semantics
* **Native Proceeds & Cost**: Stored in transaction currencies (`native_proceeds_currency`, `native_cost_currency`).
* **Native Realized Gain**: Populated **only** when `native_proceeds_currency == native_cost_currency`; otherwise stored as `NULL`.
* **Functional Valuation & Provenance**: Converted to `functional_currency` via `price_history`. The price directive ID, directive date, and staleness in days are recorded in the allocation record for audit provenance.

---

## 5. Stable Identifiers, Transfer Lineage & Schema Models

### 5.1 Content-Addressed Lot & Allocation Keys
* **Acquisition Lot Key**:
  $$\text{lot\_key} = \text{sha256}(\text{ledger\_id} : \text{account} : \text{commodity} : \text{acquisition\_date} : N_{\text{native}} : D_{\text{native}} : \text{curr} : \text{created\_posting\_id})$$
* **Transfer Destination Lot Key**:
  $$\text{transfer\_lot\_key} = \text{sha256}(\text{ledger\_id} : \text{source\_lot\_key} : \text{dest\_account} : \text{transfer\_posting\_id} : \text{units\_minor})$$
* **Disposal Allocation Key**:
  $$\text{allocation\_key} = \text{sha256}(\text{ledger\_id} : \text{open\_lot\_key} : \text{closing\_posting\_id} : \text{allocation\_ordinal} : \text{units\_disposed\_minor})$$

### 5.2 `open_lots` Table
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
    original_functional_cost_basis_minor INTEGER NOT NULL,
    remaining_functional_cost_basis_minor INTEGER NOT NULL,
    lot_label TEXT,
    source_lot_key TEXT,
    origin_account TEXT,
    created_posting_id INTEGER NOT NULL REFERENCES ledger_postings(id),
    created_tx_id INTEGER NOT NULL REFERENCES ledger_transactions(id),
    CONSTRAINT chk_positive_units CHECK (remaining_units_minor >= 0),
    CONSTRAINT chk_positive_basis CHECK (remaining_functional_cost_basis_minor >= 0),
    CONSTRAINT chk_valid_denominator CHECK (native_cost_denominator > 0 AND functional_unit_cost_denominator > 0)
);

CREATE INDEX IF NOT EXISTS idx_open_lots_search 
ON open_lots (ledger_id, account, commodity, remaining_units_minor, acquisition_date);
```

### 5.3 `lot_disposal_allocations` Table
```sql
CREATE TABLE IF NOT EXISTS lot_disposal_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_key TEXT NOT NULL UNIQUE,
    allocation_ordinal INTEGER NOT NULL DEFAULT 0,
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
    gross_functional_proceeds_minor INTEGER NOT NULL,
    allocated_fee_minor INTEGER NOT NULL DEFAULT 0,
    functional_proceeds_minor INTEGER NOT NULL,
    functional_cost_basis_minor INTEGER NOT NULL,
    functional_realized_gain_minor INTEGER NOT NULL,
    functional_currency TEXT NOT NULL,
    
    -- Audit Provenance & Directive Lineage
    strategy_applied TEXT NOT NULL CHECK(strategy_applied IN ('FIFO', 'LIFO', 'HIFO', 'SPEC_ID', 'SPEC_ID_PARTIAL_FIFO')),
    requested_lot_identifier TEXT,
    open_lot_key TEXT NOT NULL REFERENCES open_lots(lot_key),
    closing_posting_id INTEGER NOT NULL REFERENCES ledger_postings(id),
    closing_tx_id INTEGER NOT NULL REFERENCES ledger_transactions(id),
    disposal_price_directive_id INTEGER,
    acquisition_price_directive_id INTEGER,
    rate_staleness_days INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    CONSTRAINT chk_positive_disposed CHECK (units_disposed_minor > 0)
);

CREATE INDEX IF NOT EXISTS idx_allocations_tax 
ON lot_disposal_allocations (ledger_id, disposal_date, term_classification, commodity);
```

### 5.4 Materialized `portfolio_holdings_cache` Table
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

## 6. Specific Identification & Matching Algorithms

### 6.1 Specific Identification (`SPEC_ID`) Rule & Ambiguity Resolution
1. **Exact `lot_key`**: If a SHA-256 `lot_key` is provided in posting metadata, resolve the unique lot directly.
2. **Descriptor Match (`lot_label` or Date/Cost)**:
   * If the query matches **exactly one** open lot with `remaining_units_minor > 0`: allocate from this lot.
   * If the query matches **multiple** open lots:
     * `spec_id_strict = true` (default): Raise `AmbiguousLotSpecificationError` (fails closed; does not guess).
     * `spec_id_strict = false`: Disambiguate using secondary strategy (FIFO among candidates).
3. **Deficit Handling**:
   * If candidate lot has fewer units than requested:
     * `spec_id_strict = true`: Raise `InsufficientLotInventoryError`.
     * `spec_id_strict = false`: Allocate candidate units; allocate remainder via FIFO, marking residual slice `strategy_applied = 'SPEC_ID_PARTIAL_FIFO'`.

### 6.2 Deterministic Chronological Replay
Postings are processed in strict deterministic sequence:
$$\text{Order Key} = (\text{tx\_date ASC}, \text{tx\_sequence\_num ASC}, \text{posting\_index ASC}, \text{posting\_id ASC})$$

---

## 7. Authorization, REST API & Form 8949 CSV Contract

### 7.1 Tenant Authorization & Privacy (404 Policy)
All analytics endpoints verify caller authentication and ledger permissions via `ironledger.auth`. If the caller is not authorized to access `ledger_id`, the API returns `404 Not Found` (rather than `403`) to prevent tenant existence enumeration.

### 7.2 REST Endpoints (`src/ironledger/web/routers/analytics.py`)
* `GET /api/analytics/gains`:
  * Query parameters: `ledger_id`, `year` (`YYYY`), `term` (`SHORT_TERM` | `LONG_TERM` | `ALL`), `commodity`, `account`, `limit` (max 1000), `offset`.
* `GET /api/analytics/lots`: Returns active open lots with `remaining_units_minor` and `remaining_functional_cost_basis_minor`.
* `GET /api/analytics/gains/export`: Streams CSV export.

### 7.3 Form 8949 CSV Contract & Formula Injection Sanitization
**Columns**:
`Description,Date_Acquired,Date_Sold,Proceeds,Cost_Basis,Gain_Loss,Functional_Currency,Holding_Period_Days,Term_Classification,Adjustment_Code,Adjustment_Amount,Form_8949_Box,Covered_Status`

* **Coverage Semantics**:
  * Default `Covered_Status = "UNKNOWN"`, `Form_8949_Box = "UNKNOWN"` unless explicit `covered: true/false` tag exists.
  * If `covered: true`: Short-term = Box `A`, Long-term = Box `D`, `Covered_Status = "COVERED"`.
  * If `covered: false`: Short-term = Box `B`, Long-term = Box `E`, `Covered_Status = "NONCOVERED"`.
  * If `covered` omitted: Short-term = Box `C`, Long-term = Box `F`, `Covered_Status = "UNKNOWN"`.
* **Formula Injection Sanitization**:
  * **Numeric columns** (`Proceeds`, `Cost_Basis`, `Gain_Loss`, `Adjustment_Amount`, `Holding_Period_Days`): Formatted as standard decimal numbers (e.g., `-450.25`, `1250.00`). Negative numbers are **not** escaped.
  * **Text columns** (`Description`, `Functional_Currency`, `Term_Classification`, `Adjustment_Code`, `Form_8949_Box`, `Covered_Status`): Prepend single quote `'` if value begins with `=`, `+`, `-`, `@`, `\t`, or `\r`.

---

## 8. Verification Strategy

1. **Unit Tests (`tests/test_valuation_lots.py`)**:
   * Exact Banker''s rounding and cross-multiplication for HIFO.
   * Basis conservation law verification across multiple partial liquidations.
   * Multi-currency cost basis conversions and NULL native gain checks.
   * Strict SPEC_ID rejection on ambiguous lot matching or inventory deficits.
   * Brokerage fee allocation reducing net proceeds.
   * Day boundary conditions (365 vs 366 days).
2. **Security & Integration Tests (`tests/test_api_capital_gains.py`)**:
   * Tenant isolation verifying `404 Not Found` for unauthorized `ledger_id`.
   * CSV export format validation and formula injection sanitization without corrupting negative numbers.
3. **AST Isolation**:
   * Static AST verification enforcing zero runtime `beancount` imports across all packages.
4. **UI Compilation**:
   * Verify clean Vite bundle compilation with zero TypeScript errors.
