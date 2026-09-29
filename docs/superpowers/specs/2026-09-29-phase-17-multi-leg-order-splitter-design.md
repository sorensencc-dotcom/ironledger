# Phase 17: Multi-Leg Order Splitter & Multi-Account Receipt Ingestion Design

## 1. Executive Summary

Phase 17 expands IronLedger from single-category bank charge staging into an intelligent, itemized multi-leg order splitting engine. It automatically ingests purchase history (Amazon Order CSVs, Venmo statement exports) and multi-account email receipts (via Sigil Relay forwarding), matches them against single lump-sum credit card and bank charges, and proposes balanced multi-leg postings ($\sum \text{minor\_units} = 0$) for 1-click operator triage and safe-mode Beancount compilation.

---

## 2. Core Architectural Invariants

1. **Beancount Ground Truth Authority:** Plain-text Beancount remains the sole source of financial truth. Itemized split proposals staged in SQLite do not alter the ledger until explicitly confirmed by the operator.
2. **Zero Floating-Point Drift:** All monetary amounts, line items, taxes, shipping, and discount credits use exact integer minor units (cents) with zero `ast.Div` in execution paths.
3. **Decoupled Runtime:** Python memory execution strictly forbids `import beancount`.
4. **Strict Integer Balancing Invariant:** The sum of all itemized legs plus tax, shipping, and discounts MUST equal the parent transaction minor units:
   $$\sum_{i=1}^{k} \text{item\_minor\_units}_i + \text{tax\_minor} + \text{ship\_minor} - \text{promo\_minor} + \text{parent\_charge\_minor} = 0$$
   Any non-zero remainder fails closed and blocks auto-confirmation.
5. **Compiler Multi-Leg Contract:** Amends `src/ironledger/compile/model.py` (`validate_approved_set`) to support exactly one `imported` posting and one-or-more ($N \ge 1$) `contra` postings while preserving strict same-currency zero-sum balance verification (`validate_same_currency_balance`).
6. **Immutable Evidence Chaining:** Raw emails (`.eml`), CSVs, and receipts are stored with `0o444` permissions in `evidence/source_documents/<sha256>.*` and joined to events via `0018_event_evidence.sql` (`event_evidence`).
7. **Safe-Mode Governance:** Confirming or editing a split proposal mutates staging records and requires safe-mode token authorization (`X-IronLedger-Op-Token`) when safe mode is enabled.

---

## 3. Ingestion & Multi-Account Routing

### 3.1 Channels & Adapters

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                   MULTI-ACCOUNT RECEIPT AGGREGATION VIA SIGIL                          │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│  [Hotmail / Outlook] ──► Forwarding Rule: "Order Confirmation" / "Receipt" ────┐      │
│  [Apple Mail / iCloud] ─► Forwarding Rule: "Your receipt from Apple" ───────────┼──►   │
│  [Gmail / Work / Other] ─► Forwarding Rule: "Payment sent" / "Invoice" ─────────┘      │
│                                                                                        │
│                                          │                                             │
│                                          ▼                                             │
│                 [Sigil Relay Ingestion Inbox: `sigil/receipts`]                        │
│                                          │                                             │
│                                          ▼                                             │
│            [Email Header Unwrapper & Original Metadata Extractor]                      │
│            • Unwraps `Forwarded message` & `Resent-From` headers                       │
│            • Extracts true original merchant (e.g., `auto-confirm@amazon.com`)         │
│            • Preserves original purchase timestamp                                     │
│                                          │                                             │
│                                          ▼                                             │
│            [Sandboxed Split Parser ──► `source_documents` & `split_proposals`]         │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Channel A: Local Dropzone (`inbox/receipts/`):**
   * Drag-and-drop Amazon CSV order reports, Venmo CSV statements, or `.eml` files into Workbench or filesystem inbox.
2. **Channel B: Sigil Relay Ingestion (`sigil/receipts`):**
   * Multi-account email forwarding rules (Hotmail, Apple Mail, Outlook, Yahoo) forward order confirmations directly to Sigil's local relay address.
   * `email_receipt_engine.py` detects forwarding wrappers (`Forwarded message`, `Resent-From`), extracts the authentic originating merchant (`auto-confirm@amazon.com`, `no_reply@email.apple.com`), and extracts the authentic order date.
   * Extracted merchant/date metadata is treated as evidence search tokens, never as auto-commit identity authority.

---

## 4. Database Schema Migration: `0021_split_proposals.sql`

```sql
-- Migration 0021: Itemized orders and multi-leg split proposals

CREATE TABLE itemized_orders (
    order_id             TEXT PRIMARY KEY,
    source_document_id   TEXT NOT NULL REFERENCES source_documents(source_document_id) ON DELETE RESTRICT,
    ledger_id            TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    merchant             TEXT NOT NULL,
    merchant_order_ref   TEXT NOT NULL DEFAULT '',
    order_date           TEXT NOT NULL CHECK (order_date GLOB '????-??-??'),
    currency             TEXT NOT NULL CHECK (currency GLOB '[A-Z][A-Z][A-Z]'),
    subtotal_minor_units INTEGER NOT NULL,
    tax_minor_units      INTEGER NOT NULL DEFAULT 0,
    shipping_minor_units INTEGER NOT NULL DEFAULT 0,
    discount_minor_units INTEGER NOT NULL DEFAULT 0,
    total_minor_units    INTEGER NOT NULL,
    created_at_utc       TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    CHECK (total_minor_units = subtotal_minor_units + tax_minor_units + shipping_minor_units - discount_minor_units)
) STRICT;

CREATE TABLE itemized_order_lines (
    line_id              TEXT PRIMARY KEY,
    order_id             TEXT NOT NULL REFERENCES itemized_orders(order_id) ON DELETE CASCADE,
    line_index           INTEGER NOT NULL,
    item_title           TEXT NOT NULL,
    item_description     TEXT NOT NULL DEFAULT '',
    quantity             INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 1),
    unit_price_minor     INTEGER,                  -- Nullable when bundle pricing/discounts apply
    total_price_minor    INTEGER NOT NULL,
    proposed_account     TEXT NOT NULL,
    confidence_score     INTEGER NOT NULL CHECK (confidence_score BETWEEN 0 AND 100),
    created_at_utc       TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    UNIQUE (order_id, line_index)
) STRICT;

CREATE TABLE split_proposals (
    proposal_id          TEXT PRIMARY KEY,
    order_id             TEXT NOT NULL REFERENCES itemized_orders(order_id) ON DELETE CASCADE,
    target_type          TEXT NOT NULL CHECK (target_type IN ('staged_transaction', 'ledger_entry')),
    target_id            TEXT NOT NULL,
    parent_amount_minor  INTEGER NOT NULL,
    match_confidence     INTEGER NOT NULL CHECK (match_confidence BETWEEN 0 AND 100),
    status               TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'confirmed', 'rejected')),
    created_at_utc       TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    decided_at_utc       TEXT CHECK (decided_at_utc IS NULL OR decided_at_utc GLOB '????-??-??T??:??:??*Z'),
    UNIQUE (order_id, target_type, target_id)
) STRICT;

CREATE INDEX idx_itemized_orders_search ON itemized_orders(ledger_id, order_date, total_minor_units);
CREATE INDEX idx_itemized_orders_merchant ON itemized_orders(ledger_id, merchant, order_date);
CREATE INDEX idx_split_proposals_lookup ON split_proposals(target_type, target_id, status);
```

---

## 5. Multi-Tier Item Categorization Engine

For each parsed order line item, the engine assigns an expense account through three tiers:

1. **Tier 1 (Deterministic Rules - 90–100% confidence):**
   * Evaluates line title against regex/substring entries in `categorization_rules`.
2. **Tier 2 (Keyword Taxonomy Heuristic - 70–89% confidence):**
   * Built-in taxonomy matching common e-commerce item keywords:
     * `Hardware`: `usb`, `cable`, `adapter`, `ssd`, `keyboard`, `monitor` $\rightarrow$ `Expenses:Technology:Hardware`
     * `Books`: `kindle`, `paperback`, `hardcover`, `book` $\rightarrow$ `Expenses:Education:Books`
     * `Household`: `soap`, `detergent`, `filter`, `towel`, `shampoo` $\rightarrow$ `Expenses:Home:Supplies`
     * `Groceries`: `coffee`, `tea`, `snack`, `protein` $\rightarrow$ `Expenses:Food:Groceries`
3. **Tier 3 (Fallback - 0% confidence):**
   * Unmatched items default to `Expenses:Uncategorized` and require operator confirmation in the Workbench.

---

## 6. Operator Review UX & Safe-Mode Beancount Compilation

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              OPERATOR WORKBENCH SPLIT HUD                              │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Inbox Grid Row: `2026-03-15  Amazon.com  -$120.50`                                    │
│  Badge: `[Split Available: 3 items | 100% Balanced]`                                   │
│                                                                                        │
│  Inspector Sidecar:                                                                    │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Parent: Liabilities:CreditCard:Amex                    -$120.50 USD              │  │
│  │                                                                                  │  │
│  │ Split Legs:                                                                      │  │
│  │  1. Expenses:Technology:Hardware        $80.00  (Mechanical Keyboard)            │  │
│  │  2. Expenses:Food:Groceries             $35.00  (Coffee Beans)                   │  │
│  │  3. Expenses:Taxes:SalesTax              $5.50                                   │  │
│  │                                                                                  │  │
│  │ Evidence: Sanitized RFC 822 Email Body (Order #114-9876543-1234567)              │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
│  Actions: [Confirm Split (Enter)]  [Edit Legs]  [Reject Split (Esc)]                   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Confirmation Lifecycle:
* **Staged Transaction Target:**
  * Reuses existing staging split mutation primitive (`/api/staging/{stx_id}/split`), replacing single contra posting with $N$ itemized contra postings in `staged_postings`.
  * Inserts record into `event_evidence` linking the receipt document.
  * Updates `split_proposals.status = 'confirmed'`.
* **Compiled Transaction Output:**
  ```beancount
  2026-03-15 * "Amazon.com" "Order #114-9876543-1234567"
    order_ref: "114-9876543-1234567"
    Liabilities:CreditCard:Amex             -120.50 USD
    Expenses:Technology:Hardware              80.00 USD
      item_title: "Mechanical Keyboard"
      quantity: 1
    Expenses:Food:Groceries                   35.00 USD
      item_title: "Coffee Beans (2lb)"
      quantity: 1
    Expenses:Taxes:SalesTax                    5.50 USD
  ```

---

## 7. Test Strategy & Verification

1. **AST Invariant Check:** Verify zero `ast.Div` and zero `import beancount` across all normalizers and split linkers.
2. **Compiler Multi-Leg Contract:**
   * Test `validate_approved_set` with 1 imported + 3 contra postings (assert PASS).
   * Test `validate_approved_set` with unbalanced 1-cent split (assert FAIL).
3. **Deterministic Rounding & Balance Suite:**
   * Assert integer cents balancing across items, tax, shipping, promotional discounts, and gift cards.
   * Verify fail-closed behavior on 1-cent discrepancy (flags `unbalanced_near_miss`).
4. **Forwarded Email Parser Test:**
   * Test RFC 822 messages with Outlook, Apple Mail, and Gmail forwarding headers.
   * Verify correct unwrapping of original merchant, date, and line item amounts.
5. **Workbench API & Safe-Mode Test:**
   * Verify split confirmation requires safe-mode token when enabled.
   * Verify reject/unlink preserves original single posting cleanly.
