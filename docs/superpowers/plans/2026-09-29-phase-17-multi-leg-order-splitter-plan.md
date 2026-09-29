# Phase 17: Multi-Leg Order Splitter & Multi-Account Receipt Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated multi-leg order splitting engine that ingests purchase history (Amazon/Venmo CSVs) and multi-account forwarded email receipts (via Sigil Relay), matches them against single lump-sum card/bank charges, and generates balanced multi-leg postings ($\sum \text{minor\_units} = 0$) for 1-click operator triage and safe-mode Beancount compilation.

**Architecture:** A forward-only migration (`0021_split_proposals.sql`) defines immutable itemized orders, line items, and split proposals. Ingest normalizers parse CSVs and unwrapped forwarded email receipts (`.eml`), applying 3-tier categorization (deterministic rules $\rightarrow$ keyword taxonomy $\rightarrow$ uncategorized fallback). The split linker matches targets within a date window ($\Delta \text{days} \le 3$), while confirmation rewrites `staged_postings` and records evidence in `event_evidence`. The compiler is updated to support 1 imported parent + $N \ge 1$ contra postings with exact same-currency zero-sum balance verification.

**Tech Stack:** Python 3.12, SQLite 3 (WAL mode, STRICT tables), FastAPI, Starlette, Pydantic, pytest, Pure AST static analysis.

## Global Constraints

- Plain-text Beancount is the sole accounting authority; SQLite tables remain an index and workflow cache.
- Exact integer minor units (cents) only; floating-point division (`ast.Div`) is strictly forbidden across all execution modules.
- Decoupled Python runtime: zero `import beancount` in Python memory.
- Strict integer balance invariant: $\sum_{i=1}^{k} \text{item\_cents}_i + \text{tax\_cents} + \text{ship\_cents} - \text{promo\_cents} + \text{parent\_charge\_cents} = 0$.
- Confirming or editing a split proposal mutates staging records and requires safe-mode token authorization (`X-IronLedger-Op-Token`) when enabled.
- All raw evidence files are stored with `0o444` read-only permissions in `evidence/source_documents/<sha256>.*` and linked in `event_evidence`.

---

## File Structure & Responsibilities

| File Path | Role / Responsibility |
|---|---|
| `src/ironledger/compile/model.py` | Amends `validate_approved_set` to support 1 imported + $N \ge 1$ contra postings. |
| `src/ironledger/db/schema/0021_split_proposals.sql` | Schema for `itemized_orders`, `itemized_order_lines`, and `split_proposals`. |
| `src/ironledger/ingest/formats/amazon_order_normalizer.py` | Normalizer parsing Amazon Order History and Itemization CSV exports. |
| `src/ironledger/ingest/formats/venmo_normalizer.py` | Normalizer parsing Venmo transaction CSV statements. |
| `src/ironledger/ingest/formats/email_receipt_engine.py` | Sandboxed RFC 822 email parser with forwarded header unwrapper & HTML sanitizer. |
| `src/ironledger/ingest/split_linker.py` | Core linker matching orders/receipts to transactions and applying 3-tier categorization. |
| `src/ironledger/web/routers/staging.py` | REST endpoints for split proposals list, confirm, and reject. |
| `src/ironledger/mcp/tools.py` | MCP tool definitions & dispatchers for `preview_order_split` and `confirm_order_split`. |
| `tests/test_compile_multileg.py` | Unit tests for multi-leg compiler validation and rendering. |
| `tests/test_migration_0021.py` | Migration, foreign key, and constraint validation tests. |
| `tests/test_order_normalizers.py` | Tests for Amazon and Venmo CSV parsing. |
| `tests/test_email_receipt_engine.py` | Tests for RFC 822 email extraction and header unwrapping. |
| `tests/test_split_linker.py` | Tests for target matching, 3-tier categorization, and integer zero-sum balancing. |
| `tests/test_web_splits.py` | Tests for FastAPI split endpoints and safe-mode authorization. |
| `tests/test_mcp_split_tools.py` | Tests for MCP split tools and audit logging. |
| `tests/test_phase17_exit_contract.py` | Exit contract tests enforcing AST invariants and full regression pass. |

---

### Task 1: Compiler Multi-Leg Approved Set Contract

**Files:**
- Modify: `src/ironledger/compile/model.py:100-140`
- Test: `tests/test_compile_multileg.py`

**Interfaces:**
- Consumes: `ApprovedTransaction`, `ApprovedPosting`, `validate_same_currency_balance`
- Produces: Updated `validate_approved_set()` allowing 1 imported and $N \ge 1$ contra postings

- [ ] **Step 1: Write the failing test for multi-leg compilation**

```python
# tests/test_compile_multileg.py
import pytest
from ironledger.compile.model import ApprovedPosting, ApprovedSet, ApprovedTransaction, validate_approved_set
from ironledger.conventions import ApproveGateError

def test_validate_approved_set_accepts_multileg_split():
    tx = ApprovedTransaction(
        staged_transaction_id="stx-1",
        proposed_date="2026-03-15",
        payee="Amazon.com",
        narration="Order #114",
        postings=(
            ApprovedPosting("p1", "Liabilities:CreditCard:Amex", -12050, "USD", 2, "imported", 0),
            ApprovedPosting("p2", "Expenses:Technology:Hardware", 8000, "USD", 2, "contra", 1),
            ApprovedPosting("p3", "Expenses:Food:Groceries", 3500, "USD", 2, "contra", 2),
            ApprovedPosting("p4", "Expenses:Taxes:SalesTax", 550, "USD", 2, "contra", 3),
        ),
    )
    approved_set = ApprovedSet(ledger_id="default", transactions=(tx,))
    # Must not raise ApproveGateError
    validate_approved_set(approved_set)

def test_validate_approved_set_rejects_unbalanced_multileg_split():
    tx = ApprovedTransaction(
        staged_transaction_id="stx-2",
        proposed_date="2026-03-15",
        payee="Amazon.com",
        narration="Order #114",
        postings=(
            ApprovedPosting("p1", "Liabilities:CreditCard:Amex", -12050, "USD", 2, "imported", 0),
            ApprovedPosting("p2", "Expenses:Technology:Hardware", 8000, "USD", 2, "contra", 1),
            ApprovedPosting("p3", "Expenses:Food:Groceries", 3500, "USD", 2, "contra", 2),
            ApprovedPosting("p4", "Expenses:Taxes:SalesTax", 549, "USD", 2, "contra", 3), # 1 cent off
        ),
    )
    approved_set = ApprovedSet(ledger_id="default", transactions=(tx,))
    with pytest.raises(ApproveGateError) as exc:
        validate_approved_set(approved_set)
    assert "unbalanced" in str(exc.value)
```

- [ ] **Step 2: Run pytest to verify failure**

Run: `uv run pytest tests/test_compile_multileg.py -v` (Expect failure due to `len(postings) != 2` check).

- [ ] **Step 3: Update `validate_approved_set` in `src/ironledger/compile/model.py`**

Modify `src/ironledger/compile/model.py` around line 115:
Replace `if len(postings) != 2:` with:
```python
imported_count = sum(1 for p in postings if p.role == "imported")
contra_count = sum(1 for p in postings if p.role == "contra")
if imported_count != 1 or contra_count < 1 or len(postings) < 2:
    raise ApproveGateError(
        "postings_count",
        f"{tx.staged_transaction_id} must have exactly one imported posting and at least one contra posting (found {len(postings)})",
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_compile_multileg.py -v` (Assert PASS).

---

### Task 2: Forward-Only Schema Migration `0021_split_proposals.sql`

**Files:**
- Create: `src/ironledger/db/schema/0021_split_proposals.sql`
- Test: `tests/test_migration_0021.py`

**Interfaces:**
- Produces: `itemized_orders`, `itemized_order_lines`, and `split_proposals` tables with strict indexes

- [ ] **Step 1: Write the failing test for migration 0021**

```python
# tests/test_migration_0021.py
import sqlite3
from ironledger.db.migrations import migrate_governed

def test_migration_0021_applies_and_creates_tables():
    conn = sqlite3.connect(":memory:")
    migrate_governed(conn)
    cursor = conn.cursor()
    tables = [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "itemized_orders" in tables
    assert "itemized_order_lines" in tables
    assert "split_proposals" in tables

def test_itemized_orders_balancing_constraint():
    conn = sqlite3.connect(":memory:")
    migrate_governed(conn)
    conn.execute("PRAGMA foreign_keys = OFF")
    # Subtotal 1000 + Tax 100 - Discount 50 = Total 1050 (Valid)
    conn.execute("""
        INSERT INTO itemized_orders (order_id, source_document_id, ledger_id, merchant, order_date, currency, subtotal_minor_units, tax_minor_units, shipping_minor_units, discount_minor_units, total_minor_units, created_at_utc)
        VALUES ('ord-1', 'doc-1', 'default', 'Amazon', '2026-03-15', 'USD', 1000, 100, 0, 50, 1050, '2026-03-15T00:00:00Z')
    """)
    # Unbalanced row must fail CHECK
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("""
            INSERT INTO itemized_orders (order_id, source_document_id, ledger_id, merchant, order_date, currency, subtotal_minor_units, tax_minor_units, shipping_minor_units, discount_minor_units, total_minor_units, created_at_utc)
            VALUES ('ord-2', 'doc-1', 'default', 'Amazon', '2026-03-15', 'USD', 1000, 100, 0, 50, 9999, '2026-03-15T00:00:00Z')
        """)
```

- [ ] **Step 2: Create `src/ironledger/db/schema/0021_split_proposals.sql`**

Write SQL schema as specified in Design Section 4 with table triggers and composite indexes.

- [ ] **Step 3: Run migration tests**

Run: `uv run pytest tests/test_migration_0021.py tests/test_governance_migrations.py -v` (Assert PASS).

---

### Task 3: Normalizer Adapters (Amazon & Venmo CSV)

**Files:**
- Create: `src/ironledger/ingest/formats/amazon_order_normalizer.py`
- Create: `src/ironledger/ingest/formats/venmo_normalizer.py`
- Test: `tests/test_order_normalizers.py`

**Interfaces:**
- Produces: `NormalizedOrder(merchant, order_ref, date, currency, subtotal_minor, tax_minor, ship_minor, discount_minor, total_minor, lines: list[NormalizedOrderLine])`

- [ ] **Step 1: Write tests for Amazon and Venmo normalizers**

```python
# tests/test_order_normalizers.py
from ironledger.ingest.formats.amazon_order_normalizer import parse_amazon_order_csv
from ironledger.ingest.formats.venmo_normalizer import parse_venmo_csv

def test_parse_amazon_order_csv():
    sample_csv = """Order Date,Order ID,Title,Category,Item Subtotal,Shipping & Handling,Total Tax,Item Total,Refund Amount
2026-03-15,114-1234567-8901234,Mechanical Keyboard,Computers,$80.00,$0.00,$5.50,$85.50,$0.00
2026-03-15,114-1234567-8901234,Coffee Beans,Grocery,$35.00,$0.00,$0.00,$35.00,$0.00
"""
    orders = parse_amazon_order_csv(sample_csv)
    assert len(orders) == 1
    ord0 = orders[0]
    assert ord0.order_ref == "114-1234567-8901234"
    assert ord0.order_date == "2026-03-15"
    assert ord0.subtotal_minor == 11500
    assert ord0.tax_minor == 550
    assert ord0.total_minor == 12050
    assert len(ord0.lines) == 2
    assert ord0.lines[0].item_title == "Mechanical Keyboard"
    assert ord0.lines[0].total_price_minor == 8000
    assert ord0.lines[1].item_title == "Coffee Beans"
    assert ord0.lines[1].total_price_minor == 3500

def test_parse_venmo_csv():
    sample_csv = """ID,Datetime,Type,Status,Note,From,To,Amount (total)
v-101,2026-03-14 18:30:00,Payment,Complete,Dinner split with Alice,Alice,Bob,-$24.50
"""
    orders = parse_venmo_csv(sample_csv)
    assert len(orders) == 1
    assert orders[0].merchant == "Venmo"
    assert orders[0].total_minor == 2450
```

- [ ] **Step 2: Implement `amazon_order_normalizer.py` and `venmo_normalizer.py`**

Implement deterministic CSV parsing without floating point division (exact cents conversion `int(round(float_val * 100))` or regex integer parsing).

- [ ] **Step 3: Run pytest to verify normalizer tests**

Run: `uv run pytest tests/test_order_normalizers.py -v` (Assert PASS).

---

### Task 4: Email Receipt Engine & Forwarded Header Unwrapper

**Files:**
- Create: `src/ironledger/ingest/formats/email_receipt_engine.py`
- Test: `tests/test_email_receipt_engine.py`

**Interfaces:**
- Produces: `parse_email_receipt(raw_eml_bytes: bytes) -> Optional[NormalizedOrder]`

- [ ] **Step 1: Write tests for email receipt parsing and header unwrapping**

```python
# tests/test_email_receipt_engine.py
from ironledger.ingest.formats.email_receipt_engine import parse_email_receipt, unwrap_forwarded_headers

def test_unwrap_forwarded_headers():
    forwarded_body = """FYI receipt attached.
---------- Forwarded message ---------
From: Amazon.com <auto-confirm@amazon.com>
Date: Sun, Mar 15, 2026 at 2:30 PM
Subject: Your Amazon.com order of Mechanical Keyboard...
To: me@hotmail.com

Order #114-1234567-8901234
Order Total: $120.50
"""
    headers = unwrap_forwarded_headers(forwarded_body)
    assert headers["merchant_email"] == "auto-confirm@amazon.com"
    assert "2026-03-15" in headers["order_date"]
    assert headers["order_ref"] == "114-1234567-8901234"

def test_parse_amazon_email_receipt():
    raw_eml = b"""From: me@hotmail.com
To: receipts@sigil.local
Subject: Fwd: Your Amazon.com order #114-1234567-8901234
Date: Mon, 16 Mar 2026 09:00:00 -0400
Content-Type: text/plain; charset=utf-8

---------- Forwarded message ---------
From: Amazon.com <auto-confirm@amazon.com>
Date: Sun, 15 Mar 2026 14:30:00 -0400
Subject: Your Amazon.com order #114-1234567-8901234
To: me@hotmail.com

Order #114-1234567-8901234
Items Ordered:
1 of: Mechanical Keyboard [Computers] - $80.00
1 of: Coffee Beans [Grocery] - $35.00

Item Subtotal: $115.00
Shipping & Handling: $0.00
Estimated Tax: $5.50
Grand Total: $120.50
"""
    order = parse_email_receipt(raw_eml)
    assert order is not None
    assert order.merchant == "Amazon"
    assert order.order_ref == "114-1234567-8901234"
    assert order.total_minor == 12050
    assert order.tax_minor == 550
    assert len(order.lines) == 2
```

- [ ] **Step 2: Implement `src/ironledger/ingest/formats/email_receipt_engine.py`**

Implement standard library `email` parser, regex un-wrapper for Outlook/Apple Mail/Gmail forwarding markers, and merchant-specific text extractors.

- [ ] **Step 3: Run pytest to verify email receipt engine**

Run: `uv run pytest tests/test_email_receipt_engine.py -v` (Assert PASS).

---

### Task 5: Multi-Leg Split Linker & 3-Tier Categorization

**Files:**
- Create: `src/ironledger/ingest/split_linker.py`
- Test: `tests/test_split_linker.py`

**Interfaces:**
- Consumes: `NormalizedOrder`, `sqlite3.Connection`, `categorization_rules`
- Produces: `evaluate_split_proposals(conn, ledger_id) -> list[SplitProposal]`

- [ ] **Step 1: Write tests for split linking and 3-tier categorization**

```python
# tests/test_split_linker.py
import sqlite3
from ironledger.db.migrations import migrate_governed
from ironledger.ingest.formats.amazon_order_normalizer import NormalizedOrder, NormalizedOrderLine
from ironledger.ingest.split_linker import ingest_normalized_order, evaluate_split_proposals

def test_split_linker_matches_staged_transaction():
    conn = sqlite3.connect(":memory:")
    migrate_governed(conn)
    conn.execute("PRAGMA foreign_keys = OFF")

    # Seed rule
    conn.execute("INSERT INTO categorization_rules (rule_id, ledger_id, priority, target_account, predicate_json, created_at_utc) VALUES ('r1', 'default', 10, 'Expenses:Technology:Hardware', '{\"field\":\"description\",\"op\":\"contains\",\"value\":\"Keyboard\"}', '2026-01-01T00:00:00Z')")

    # Seed staged transaction
    conn.execute("INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, proposed_date, payee, narration, identity_algo_version, identity_method, identity_fingerprint, created_at_utc, ledger_id) VALUES ('stx-1', 'rec-1', 'pending', '2026-03-15', 'Amazon.com', 'AMZN MKTP', 1, 'sha256_fallback', 'a'*64, '2026-03-15T00:00:00Z', 'default')")
    conn.execute("INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, account, minor_units, currency, minor_unit_scale, role, posting_index, created_at_utc, ledger_id) VALUES ('sp-1', 'stx-1', 'rec-1', 'Liabilities:CreditCard:Amex', -12050, 'USD', 2, 'imported', 0, '2026-03-15T00:00:00Z', 'default')")
    conn.execute("INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, account, minor_units, currency, minor_unit_scale, role, posting_index, created_at_utc, ledger_id) VALUES ('sp-2', 'stx-1', 'rec-1', 'Expenses:Uncategorized', 12050, 'USD', 2, 'contra', 1, '2026-03-15T00:00:00Z', 'default')")

    order = NormalizedOrder(
        order_ref="114-1234567-8901234",
        merchant="Amazon",
        order_date="2026-03-15",
        currency="USD",
        subtotal_minor=11500,
        tax_minor=550,
        shipping_minor=0,
        discount_minor=0,
        total_minor=12050,
        source_doc_id="doc-1",
        lines=[
            NormalizedOrderLine(1, "Mechanical Keyboard", 1, 8000, 8000), # Tier 1 match -> Expenses:Technology:Hardware
            NormalizedOrderLine(2, "Organic Coffee Beans", 1, 3500, 3500), # Tier 2 heuristic -> Expenses:Food:Groceries
        ]
    )

    ingest_normalized_order(conn, order, ledger_id="default")
    proposals = evaluate_split_proposals(conn, ledger_id="default")
    assert len(proposals) == 1
    prop = proposals[0]
    assert prop.target_id == "stx-1"
    assert prop.parent_amount_minor == -12050
    assert prop.match_confidence >= 90
```

- [ ] **Step 2: Implement `src/ironledger/ingest/split_linker.py`**

Implement `ingest_normalized_order`, 3-tier categorization resolution, and `evaluate_split_proposals` with fail-closed balancing validation.

- [ ] **Step 3: Run pytest to verify split linker**

Run: `uv run pytest tests/test_split_linker.py -v` (Assert PASS).

---

### Task 6: Split Proposal Confirmation, Staging Mutation & Safe-Mode Governance

**Files:**
- Modify: `src/ironledger/web/routers/staging.py`
- Test: `tests/test_web_splits.py`

**Interfaces:**
- Consumes: `split_proposals`, `staged_postings`, `event_evidence`
- Produces: `POST /api/staging/splits/{proposal_id}/confirm`, `POST /api/staging/splits/{proposal_id}/reject`

- [ ] **Step 1: Write API tests for split confirmation under safe mode**

```python
# tests/test_web_splits.py
from fastapi.testclient import TestClient
from ironledger.web.app import create_app

def test_confirm_split_proposal_rewrites_staged_postings(tmp_path):
    db_path = tmp_path / "ironledger.db"
    # Seed DB with staged transaction and split proposal
    # ...
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    res = client.post("/api/staging/splits/prop-1/confirm")
    assert res.status_code == 200
    # Verify staged_postings has 1 imported + 3 contra legs
    # Verify event_evidence row exists
```

- [ ] **Step 2: Implement split proposal endpoints in `src/ironledger/web/routers/staging.py`**

Add `/api/staging/splits/proposals`, `/api/staging/splits/{proposal_id}/confirm`, and `/api/staging/splits/{proposal_id}/reject` with transactional rewrite of `staged_postings` and `event_evidence` insertion. Enforce safe-mode token validation.

- [ ] **Step 3: Run pytest to verify staging split endpoints**

Run: `uv run pytest tests/test_web_splits.py -v` (Assert PASS).

---

### Task 7: MCP Tool Surface Expansion (`preview_order_split`, `confirm_order_split`)

**Files:**
- Modify: `src/ironledger/mcp/tools.py`
- Test: `tests/test_mcp_split_tools.py`

**Interfaces:**
- Consumes: `split_proposals`, `split_linker`
- Produces: MCP tools `preview_order_split`, `confirm_order_split`

- [ ] **Step 1: Write tests for MCP split tools**

```python
# tests/test_mcp_split_tools.py
from ironledger.mcp.tools import list_tools, call_tool

def test_mcp_split_tools_registered():
    tools = list_tools(include_all=True)
    names = [t["name"] for t in tools]
    assert "preview_order_split" in names
    assert "confirm_order_split" in names
```

- [ ] **Step 2: Add MCP tool schemas and handlers in `src/ironledger/mcp/tools.py`**

Register `SPLIT_TOOL_NAMES = ('preview_order_split', 'confirm_order_split')` in `ALL_TOOL_NAMES` with audit logging and parameter validation.

- [ ] **Step 3: Run pytest to verify MCP split tools**

Run: `uv run pytest tests/test_mcp_split_tools.py -v` (Assert PASS).

---

### Task 8: AST Invariants & Exit Contract Test Suite

**Files:**
- Create: `tests/test_phase17_exit_contract.py`
- Modify: `STATUS.md`

**Interfaces:**
- Produces: Phase 17 exit contract seal

- [ ] **Step 1: Write `tests/test_phase17_exit_contract.py`**

```python
# tests/test_phase17_exit_contract.py
import ast
from pathlib import Path
import pytest

def test_phase17_ast_invariants():
    """Verify zero ast.Div and zero import beancount across all Phase 17 modules."""
    phase17_files = [
        Path("src/ironledger/ingest/formats/amazon_order_normalizer.py"),
        Path("src/ironledger/ingest/formats/venmo_normalizer.py"),
        Path("src/ironledger/ingest/formats/email_receipt_engine.py"),
        Path("src/ironledger/ingest/split_linker.py"),
    ]
    for file_path in phase17_files:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            assert not isinstance(node, ast.Div), f"Forbidden ast.Div in {file_path}"
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names]
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                for mod in names:
                    assert "beancount" not in mod, f"Forbidden import beancount in {file_path}: {mod}"
```

- [ ] **Step 2: Run full regression test suite**

Run: `uv run pytest -q` (Assert 100% PASS across all tests).

- [ ] **Step 3: Update `STATUS.md` with Phase 17 Milestone**

Update [`STATUS.md`](file:///C:/dev/IronLedger/STATUS.md) with active goal, completed work, and test counts.

---

## Verification Commands

```powershell
# Repo context preflight
pwsh -NoProfile -File C:\dev\scripts\verify-repo-context.ps1 -Path C:\dev\IronLedger

# Run Phase 17 specific tests
uv run pytest tests/test_compile_multileg.py tests/test_migration_0021.py tests/test_order_normalizers.py tests/test_email_receipt_engine.py tests/test_split_linker.py tests/test_web_splits.py tests/test_mcp_split_tools.py tests/test_phase17_exit_contract.py -v

# Run full project regression suite
uv run pytest -q
```
