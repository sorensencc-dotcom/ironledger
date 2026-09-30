# IronLedger Project Status

## Active Goal
Phase 17 — Multi-Leg Order-Level Splitter & Multi-Account Receipt Ingestion Engine: Automated itemized transaction breakdown (Amazon/Venmo CSVs & forwarded RFC 822 email receipts via Sigil Relay) with integer zero-float precision, 3-tier categorization, and safe-mode review workflows.

## Milestone Status: Multi-Leg Order Splitter Engine v0.17.0
- **Preceding Baseline:** Phase 16 Subscriptions & Recurring Intelligence Engine v0.16.0 (1095 passed, 4 skipped).
- **Regression Invariant:** 1122 passed, 4 skipped.
- **Current Milestone:** Phase 17 Multi-Leg Order Splitter.
  - Forward-only migration 0021 (`itemized_orders`, `itemized_order_lines`, `split_proposals`).
  - Compiler Multi-Leg Contract (`validate_approved_set` in `src/ironledger/compile/model.py` and deterministic contra rendering in `src/ironledger/compile/render.py`).
  - Normalizers: Amazon Order History CSV (`src/ironledger/ingest/formats/amazon_order_normalizer.py`), Venmo statement CSV (`src/ironledger/ingest/formats/venmo_normalizer.py`), and Email Receipt Engine (`src/ironledger/ingest/formats/email_receipt_engine.py`).
  - Ingestion Split Linker & 3-Tier Categorization (`src/ironledger/ingest/split_linker.py`).
  - Operator Workbench Web API (`/api/staging/splits/proposals`, `/confirm`, `/reject` in `src/ironledger/web/routers/staging.py`).
  - MCP Split Tools (`preview_order_split`, `confirm_order_split` in `src/ironledger/mcp/tools.py`).
  - Full AST Invariant & Exit Contract Seal (`tests/test_phase17_exit_contract.py`).

## Completed Work
1. **Compiler Multi-Leg Contract (`src/ironledger/compile/model.py`, `src/ironledger/compile/render.py`)**:
   - Upgraded `validate_approved_set` to assert exactly one `imported` leg and $N \ge 1$ `contra` legs while strictly enforcing same-currency balance ($\sum \text{minor\_units} = 0$).
   - Ensured deterministic ordering in Beancount export (imported leg first, then contra legs sorted deterministically by account, minor units, and source record ID).

2. **Schema Migration `0021_split_proposals.sql`**:
   - Added `itemized_orders`, `itemized_order_lines`, and `split_proposals` with `STRICT` enforcement, foreign key constraints, total balance check formulas, and performance indexes.

3. **CSV & Email Receipt Normalizers (`src/ironledger/ingest/formats/`)**:
   - Zero-float integer minor unit currency parser with strict fraction rejection.
   - Amazon Order History CSV and Venmo Statement CSV normalizers with multi-line item grouping.
   - Forwarded email unwrapper for RFC 822 `.eml` files supporting Gmail, Outlook/Hotmail, Apple Mail/iCloud, and Resent-* envelope headers.

4. **Multi-Leg Split Linker & 3-Tier Item Categorization (`src/ironledger/ingest/split_linker.py`)**:
   - Tier 1: Deterministic Review Rules (`resolve_rule_row`).
   - Tier 2: Keyword taxonomy heuristic (Books, Electronics, Food, Household, Transport, Software).
   - Tier 3: Uncategorized fallback (`Expenses:Uncategorized`).
   - Transactional split confirmation mutating staged postings with full balance validation and audit trails.

5. **Operator Workbench Web API & MCP Tool Integration (`src/ironledger/web/routers/staging.py`, `src/ironledger/mcp/tools.py`)**:
   - Added `/api/staging/splits/proposals` list, `/confirm`, and `/reject` endpoints guarded by operator token auth.
   - Registered and exposed `preview_order_split` and `confirm_order_split` MCP tools with comprehensive parameter validation and audit logging.

6. **Phase 17 Exit Contract & AST Invariant Suite (`tests/test_phase17_exit_contract.py`)**:
   - Verified zero `ast.Div` and zero `import beancount` across all Phase 17 modules.
   - Full regression suite passing: 1122 passed, 4 skipped (100% green).

7. **Receipt Automation & Unattended S4U Task Scheduler Daemon Suite (`scripts/`)**:
   - `scripts/sweep_receipts.py`: Gmail IMAP receipt sweeper using `X-GM-RAW` queries, UID deduplication, and optional dynamic Gmail label tagging (`+X-GM-LABELS`).
   - `scripts/ingest_receipts.py`: Ingestion runner parsing `.eml` files into `itemized_orders` and `itemized_order_lines`, generating `split_proposals` in `ironledger.db`.
   - `scripts/poll-receipts.ps1`: Unified PowerShell pipeline runner with headless `.env` configuration support.
   - `scripts/setup-scheduled-tasks.ps1`: Windows Task Scheduler harness upgraded to `S4U` unattended execution mode (`IronLedger-PriceFeed-Sync`, `IronLedger-Bank-Sync`, `IronLedger-Receipt-Sync`).

## Core Architectural Invariants Maintained
- **Plaintext Ground Truth:** Plaintext Beancount files remain the sole financial authority.
- **Decoupled Runtime:** Zero runtime `import beancount` enforced via static AST visitor.
- **Pure Integer Arithmetic:** Exact integer minor units without float representation or drift (zero `ast.Div`).
- **Balanced Multi-Leg Postings:** Single parent imported leg with $N \ge 1$ contra postings guaranteed $\sum \text{minor\_units} = 0$.
- **Append-Only Immutability:** SQLite triggers guarding outbox, audit, mutation, and governance event streams.
- **Multi-Tenant Boundaries:** Relational composite keys and tenant registries enforcing strict ledger isolation.

## Next Action
Execute Phase 18 deliverables as defined in [Phase 18 Roadmap](docs/meta/roadmap.md):
1. **Background IMAP / Mail Poller Daemon** (`src/ironledger/ingest/imap_poller.py` & multi-account config).
2. **Operator Workbench Split Proposal UI** (`RegisterGrid.tsx` & `InspectorSidecar.tsx` visual line-item split table).
3. **Multi-Shipment Combinatorial Matcher** (subset-sum partial charge reconciliation).
4. **Configurable Keyword Taxonomy** (`config/taxonomy.json`).

## Local Workbench Runtime
- Compose default: `http://127.0.0.1:8000`.
- Current Windows fallback: `http://127.0.0.1:8765` via `IRONLEDGER_HOST_PORT=8765 docker compose up -d` (host port `8765` mapped to container port `8000`).

