# IronLedger Phase 18 Roadmap & Open Items

## Strategic Direction: Automated Ingestion & Split Intelligence

Phase 17 established the core multi-leg compiler contract, schema migration 0021, RFC 822 email unwrapper, Amazon/Venmo normalizers, and REST/MCP split endpoints. Phase 18 focuses on closing the operational loop: automated mail background polling, visual split proposal triage in the React workbench, multi-shipment charge reconciliation, and user-configurable taxonomy.

---

## Phase 18 Work Breakdown Structure (WBS)

```
Phase 18 Delivery Roadmap
├── 1. Background IMAP / Mail Poller Daemon (P1)
│   ├── Multi-account credential store (`config/email_connectors.json`)
│   ├── Scheduled IMAP poller (`src/ironledger/ingest/imap_poller.py`)
│   ├── Automatic .eml extraction & inbox staging
│   └── Ingestion pipeline trigger & duplicate message suppression
│
├── 2. Operator Workbench Split Proposal UI (P1)
│   ├── React split proposal visual review card in `RegisterGrid.tsx`
│   ├── Itemized breakdown table (lines, prices, taxes, shipping, confidence)
│   ├── Inline category override typeaheads per line
│   └── 1-click "Apply Split" & "Reject Split" actions in `InspectorSidecar.tsx`
│
├── 3. Multi-Shipment Combinatorial Reconciliation (P2)
│   ├── Subset-sum solver for partial Amazon credit card charges
│   ├── Prorated tax & shipping distribution across shipment splits
│   └── Partial order linking in `split_linker.py`
│
├── 4. Configurable Keyword Taxonomy (`config/taxonomy.json`) (P2)
│   ├── Externalize hardcoded Tier 2 regex rules to JSON
│   ├── Workbench UI taxonomy rule editor
│   └── Custom account mapping validation
│
└── 5. Inbound Email HTTP Webhook Endpoint (P3)
    ├── `POST /api/webhooks/inbound-email` for real-time Sigil / agent push
    └── HMAC signature verification & direct staging
```

---

## Deliverable Specifications

### 1. Background IMAP / Mail Poller Daemon
- **Objective**: Eliminate manual file dropping for email receipts.
- **Module**: `src/ironledger/ingest/imap_poller.py`.
- **Config**: `config/email_connectors.json` (supports multiple accounts: Gmail, Outlook/Hotmail, iCloud with app passwords).
- **Behavior**:
  - Connects securely via SSL/TLS IMAP.
  - Queries `(UNSEEN (OR FROM "auto-confirm@amazon.com" (OR FROM "venmo@venmo.com" (OR FROM "no_reply@email.apple.com" FROM "uber.us@uber.com"))))` or `SINCE <date>` for backfill.
  - Fetches RFC 822 `.eml` payloads directly into `C:\Users\soren\IronLedger\InBox`.
  - Automatically runs `run_import()` and triggers split linking against staged transactions.

### 2. Operator Workbench Split Proposal Review UI
- **Objective**: Full interactive visual triage in browser at `http://127.0.0.1:8000/`.
- **Components**:
  - `web/src/components/SplitProposalModal.tsx` & `web/src/components/InspectorSidecar.tsx`.
  - Line-item breakdown table displaying: Item Title, Quantity, Price, Tax, Category Account with `AccountTypeahead`, Confidence score badge.
  - Single-action Approve/Confirm button calling `/api/staging/splits/proposals/{id}/confirm`.

### 3. Multi-Shipment Combinatorial Matcher
- **Objective**: Reconcile Amazon orders where items ship across multiple days and generate separate credit card transactions.
- **Module**: `src/ironledger/ingest/split_linker.py`.
- **Algorithm**: Integer subset-sum matching where:
  $$\sum_{i \in \text{subset}} \text{unit\_price}_i + \text{prorated\_tax} + \text{prorated\_shipping} = |\text{staged\_charge\_minor}|$$

### 4. User-Configurable Taxonomy
- **Objective**: Allow users to define custom keywords and expense mappings without code edits.
- **Config**: `config/taxonomy.json`.
- **Integration**: Dynamic reload in `categorize_order_line()`.

---

## Invariants & Compliance Requirements

1. **Zero Float Math**: All split calculations, taxes, shipping, and discounts remain strict integer minor units.
2. **Beancount Immutability**: All mutations target disposable staging; plaintext Beancount remains accounting ground truth.
3. **Decoupled Runtime**: Zero runtime `import beancount` (verified via AST static analysis).
4. **Balanced Multi-Leg Verification**: Compiler guarantees $\sum \text{minor\_units} = 0$ across all transactions.
