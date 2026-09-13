# Phase 13 Implementation Plan: Portfolio Lot Matching, Cost Basis & Capital Gains Subsystem

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a deterministic, zero-float lot matching, cost basis, and capital gains tax reporting subsystem with Beancount lot extraction, FIFO/LIFO/HIFO/SPEC_ID reduction, Form 8949 CSV export, and an interactive Operator Workbench interface.

**Architecture:** A pure integer rational inventory engine (`ironledger.valuation.lots`) processes chronological postings in atomic projection transactions, populating immutable `lot_disposal_allocations`, maintaining `open_lots` with exact basis conservation, and materializing `portfolio_holdings_cache`. FastAPI exposes analytics and CSV endpoints under tenant-safe 404 privacy rules, consumed by a React 19 Operator Workbench UI.

**Tech Stack:** Python 3.12+, SQLite3, FastAPI, Pydantic, React 19, TypeScript, Vite, TailwindCSS, Pytest.

## Global Constraints

- **Strict Zero-Float Arithmetic**: All proceeds, cost basis, and valuations must use `convert_amount_rational` with round-half-to-even integer tie-breaking. No `float` division (`/`).
- **Global AST Invariant**: Zero runtime `import beancount` across the codebase, enforced via static AST inspection.
- **Basis Conservation Law**: For every partial lot liquidation, `sum(allocations) + remaining = original`, absorbing rounding residues into the final allocation slice.
- **Fail-Closed Inventory**: Dispositions exceeding open inventory or ambiguous SPEC_ID matches raise dedicated exceptions and abort projection transactions.
- **Tenant Isolation Privacy**: Unauthorized or nonexistent `ledger_id` requests return `404 Not Found`.

---

### Task 1: Database Schema & Projection Models

**Files:**
- Modify: `src/ironledger/db/schema.py`
- Create: `tests/test_lot_schema.py`

**Interfaces:**
- Produces: `open_lots`, `lot_disposal_allocations`, and `portfolio_holdings_cache` DDL with indexes.

- [ ] **Step 1: Write failing schema migration and table creation test**

```python
# tests/test_lot_schema.py
import sqlite3
from ironledger.db.schema import create_tables

def test_lot_schema_tables_exist():
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    cursor = conn.cursor()
    
    tables = [
        row[0] for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    assert "open_lots" in tables
    assert "lot_disposal_allocations" in tables
    assert "portfolio_holdings_cache" in tables
    
    columns = [
        row[1] for row in cursor.execute("PRAGMA table_info(open_lots)").fetchall()
    ]
    assert "lot_key" in columns
    assert "remaining_functional_cost_basis_minor" in columns
    assert "source_lot_key" in columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_lot_schema.py -v`  
Expected: FAIL (missing tables or columns)

- [ ] **Step 3: Update schema definition in `src/ironledger/db/schema.py`**

Add DDL for `open_lots`, `lot_disposal_allocations`, and `portfolio_holdings_cache`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_lot_schema.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/db/schema.py tests/test_lot_schema.py
git commit -m "feat(db): add lot inventory, disposal allocations, and holdings cache tables"
```

---

### Task 2: Beancount AST Lot Annotation Parsing & Normalization

**Files:**
- Modify: `src/ironledger/valuation/models.py`
- Create: `tests/test_lot_parsing.py`

**Interfaces:**
- Consumes: Raw Beancount posting string and tokens.
- Produces: Normalized `LotCostAnnotation(cost_numerator, cost_denominator, currency, date, label, is_total_cost)` with `gcd(N, D) = 1`.

- [ ] **Step 1: Write failing unit test for per-unit and total-cost lot parsing**

```python
# tests/test_lot_parsing.py
from ironledger.valuation.models import parse_lot_annotation

def test_parse_per_unit_cost():
    ann = parse_lot_annotation('{150.50 USD, 2026-05-01, "lot-1"}', unit_scale=4, posting_units_minor=100000)
    assert ann.native_cost_numerator == 301
    assert ann.native_cost_denominator == 2
    assert ann.native_cost_currency == "USD"
    assert ann.lot_date == "2026-05-01"
    assert ann.lot_label == "lot-1"

def test_parse_total_cost_normalization():
    ann = parse_lot_annotation('{{1500.00 USD}}', unit_scale=4, posting_units_minor=100000)
    assert ann.native_cost_numerator == 150
    assert ann.native_cost_denominator == 1
    assert ann.native_cost_currency == "USD"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_lot_parsing.py -v`  
Expected: FAIL (missing `parse_lot_annotation`)

- [ ] **Step 3: Implement `parse_lot_annotation` in `src/ironledger/valuation/models.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_lot_parsing.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/valuation/models.py tests/test_lot_parsing.py
git commit -m "feat(valuation): implement normalized rational Beancount lot parser"
```

---

### Task 3: Deterministic Lot Matching Engine & Basis Conservation

**Files:**
- Create: `src/ironledger/valuation/lots.py`
- Create: `tests/test_valuation_lots.py`

**Interfaces:**
- Consumes: Chronological postings stream, `ValuationEngine.get_price()`.
- Produces: `LotProcessor.process_posting()`, generating `open_lots` mutations, immutable `LotDisposalAllocation`, and enforcing basis conservation laws.

- [ ] **Step 1: Write failing tests for FIFO, LIFO, HIFO, SPEC_ID, and Basis Conservation**

```python
# tests/test_valuation_lots.py
import sqlite3
from ironledger.db.schema import create_tables
from ironledger.valuation.lots import LotProcessor, InsufficientInventoryError
from ironledger.valuation.engine import ValuationEngine

def test_fifo_partial_disposal_and_basis_conservation():
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    engine = ValuationEngine(conn)
    processor = LotProcessor(conn, engine, functional_currency="USD")
    
    processor.process_acquisition(
        ledger_id="default", account="Assets:Brokerage:AAPL", commodity="AAPL",
        date="2025-01-10", units_minor=100000, unit_scale=4,
        cost_num=150, cost_denom=1, cost_currency="USD",
        posting_id=1, tx_id=1
    )
    
    processor.process_acquisition(
        ledger_id="default", account="Assets:Brokerage:AAPL", commodity="AAPL",
        date="2025-06-10", units_minor=100000, unit_scale=4,
        cost_num=200, cost_denom=1, cost_currency="USD",
        posting_id=2, tx_id=2
    )
    
    allocations = processor.process_disposal(
        ledger_id="default", account="Assets:Brokerage:AAPL", commodity="AAPL",
        date="2026-02-15", units_disposed_minor=150000, unit_scale=4,
        disposal_price_num=220, disposal_price_denom=1, disposal_currency="USD",
        strategy="FIFO", closing_posting_id=3, closing_tx_id=3
    )
    
    assert len(allocations) == 2
    assert allocations[0].units_disposed_minor == 100000
    assert allocations[0].term_classification == "LONG_TERM"
    assert allocations[0].functional_realized_gain_minor == 70000
    assert allocations[1].units_disposed_minor == 50000
    assert allocations[1].term_classification == "SHORT_TERM"
    assert allocations[1].functional_realized_gain_minor == 10000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_valuation_lots.py -v`  
Expected: FAIL (missing `LotProcessor`)

- [ ] **Step 3: Implement `LotProcessor` in `src/ironledger/valuation/lots.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_valuation_lots.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/valuation/lots.py tests/test_valuation_lots.py
git commit -m "feat(valuation): implement deterministic lot reduction engine with basis conservation"
```

---

### Task 4: Valuation Engine Projection & Holdings Cache Refresh

**Files:**
- Modify: `src/ironledger/valuation/engine.py`
- Create: `tests/test_portfolio_holdings_cache.py`

**Interfaces:**
- Consumes: `open_lots`, `price_history`.
- Produces: `ValuationEngine.refresh_portfolio_cache(ledger_id, conn)`.

- [ ] **Step 1: Write test verifying exact Banker's rounding in `portfolio_holdings_cache`**

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_portfolio_holdings_cache.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement `refresh_portfolio_cache` in `src/ironledger/valuation/engine.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_portfolio_holdings_cache.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/valuation/engine.py tests/test_portfolio_holdings_cache.py
git commit -m "feat(valuation): add portfolio holdings cache refresh with exact Banker's rounding"
```

---

### Task 5: REST API Analytics Endpoints & CSV Export

**Files:**
- Modify: `src/ironledger/web/routers/analytics.py`
- Create: `tests/test_api_capital_gains.py`

**Interfaces:**
- Consumes: `lot_disposal_allocations`, `open_lots`, `portfolio_holdings_cache`.
- Produces: `GET /api/analytics/gains`, `GET /api/analytics/lots`, `GET /api/analytics/gains/export`.

- [ ] **Step 1: Write integration tests for API gains, CSV export, and 404 tenant isolation**

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_capital_gains.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement endpoints in `src/ironledger/web/routers/analytics.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_capital_gains.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/web/routers/analytics.py tests/test_api_capital_gains.py
git commit -m "feat(api): add capital gains analytics, lot inspector, and Form 8949 CSV export"
```

---

### Task 6: Operator Workbench UI — Tax & Capital Gains Ledger

**Files:**
- Create: `web/src/components/CapitalGainsLedger.tsx`
- Modify: `web/src/components/TopHUD.tsx`
- Modify: `web/src/components/Sidebar.tsx`
- Modify: `web/src/App.tsx`

**Interfaces:**
- Consumes: `/api/analytics/gains`, `/api/analytics/gains/export`, `/api/analytics/lots`.
- Produces: Interactive React 19 Capital Gains & Tax Ledger view with summary cards, year/term filters, closed lots table, and CSV download.

- [ ] **Step 1: Create `CapitalGainsLedger.tsx` with KPI cards and Form 8949 CSV export button**

- [ ] **Step 2: Wire `CapitalGainsLedger` into `web/src/App.tsx`, `Sidebar.tsx`, and `TopHUD.tsx`**

- [ ] **Step 3: Run Vite build to verify frontend compiles with zero errors**

Run: `cd web && npm run build`  
Expected: `✓ built in ...` with zero TypeScript or bundle errors.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/CapitalGainsLedger.tsx web/src/App.tsx web/src/components/TopHUD.tsx web/src/components/Sidebar.tsx
git commit -m "feat(ui): add Tax & Capital Gains Ledger view in Operator Workbench"
```

---

### Task 7: Static AST Analysis & End-to-End Regression Gate

**Files:**
- Modify: `tests/test_ast_beancount_isolation.py`
- Modify: `STATUS.md`

- [ ] **Step 1: Run static AST analysis enforcing zero runtime beancount imports**

Run: `pytest tests/test_ast_beancount_isolation.py -v`  
Expected: PASS (0 violations across all `src/ironledger/` modules)

- [ ] **Step 2: Run complete Python test suite**

Run: `pytest tests/ -v`  
Expected: 100% PASS rate across all unit and integration tests.

- [ ] **Step 3: Update `STATUS.md` to reflect Phase 13 completion and bump version to `v0.13.0`**

- [ ] **Step 4: Commit**

```bash
git add STATUS.md
git commit -m "chore(status): record Phase 13 portfolio lot matching milestone at v0.13.0"
```