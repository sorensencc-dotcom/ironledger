# IronLedger Project Status

## Active Goal
Stabilize the shipped Phase 18 workbench: verify runtime/database health, finish the split-line total UI repair, and refresh the regression baseline. Live database health is failing as of 2026-10-07; recovery remains operator work.

## Milestone Status: Phase 18 Shipped; Runtime Stabilization Open
- **Preceding Baseline:** Phase 16 Subscriptions & Recurring Intelligence Engine v0.16.0 (1095 passed, 4 skipped).
- **Current isolated regression baseline (2026-10-07):** 1146 passed, 5 skipped (1151 collected); UI 6 passed; production UI build passed. Live runtime checks failed separately.
- **Shipped milestone:** Phase 18 ingestion and split proposal workbench, building on Phase 17 Multi-Leg Order Splitter.
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
   - Historical Phase 17 regression result: 1122 passed, 4 skipped. Current baseline is recorded above.

7. **Receipt Automation & Unattended S4U Task Scheduler Daemon Suite (`scripts/`)**:
   - `scripts/sweep_receipts.py`: Gmail IMAP receipt sweeper using `X-GM-RAW` queries, UID deduplication, and optional dynamic Gmail label tagging (`+X-GM-LABELS`).
   - `scripts/ingest_receipts.py`: Ingestion runner parsing `.eml` files into `itemized_orders` and `itemized_order_lines`, generating `split_proposals` in `ironledger.db`.
   - `scripts/poll-receipts.ps1`: Unified PowerShell pipeline runner with headless `.env` configuration support.
   - `scripts/setup-scheduled-tasks.ps1`: Windows Task Scheduler harness upgraded to `S4U` unattended execution mode (`IronLedger-PriceFeed-Sync`, `IronLedger-Bank-Sync`, `IronLedger-Receipt-Sync`).

8. **Phase 18 Reduced P1 IMAP Poller Lane (`src/ironledger/ingest/imap_poller.py`)**:
   - Added stdlib multi-account IMAP polling with `password_env` secret references, JSON UID state, RFC 822 `.eml` staging, and focused mocked tests.

9. **Phase 18 P2 foundations** (src/ironledger/ingest/split_linker.py, config/taxonomy.json):
   - Added mtime-aware external taxonomy reload with account validation.
   - Added deterministic integer subset-sum shipment matcher with prorated tax, shipping, and discount arithmetic.

10. **Phase 18 Partial Shipment Proposal Persistence** (src/ironledger/db/schema/0022_partial_shipment_proposals.sql, src/ironledger/ingest/split_linker.py):
   - Persisted selected line indices and prorated tax, shipping, and discount allocations.
   - Confirmation now applies only selected shipment lines while preserving full-order compatibility.

11. **Phase 18 Taxonomy Editor** (src/ironledger/web/routers/taxonomy.py, web/src/App.tsx):
   - Added operator-authenticated validated taxonomy read/write API and rules-view editor.
   - Category edits persist to config/taxonomy.json and reload dynamically.

## Core Architectural Invariants Maintained
- **Plaintext Ground Truth:** Plaintext Beancount files remain the sole financial authority.
- **Decoupled Runtime:** Zero runtime `import beancount` enforced via static AST visitor.
- **Pure Integer Arithmetic:** Exact integer minor units without float representation or drift (zero `ast.Div`).
- **Balanced Multi-Leg Postings:** Single parent imported leg with $N \ge 1$ contra postings guaranteed $\sum \text{minor\_units} = 0$.
- **Append-Only Immutability:** SQLite triggers guarding outbox, audit, mutation, and governance event streams.
- **Multi-Tenant Boundaries:** Relational composite keys and tenant registries enforcing strict ledger isolation.

## Verification Snapshot — 2026-10-07
- Source baseline: main `fde1262`, plus the scoped split-total helper and tests in an isolated worktree. No live financial writes or deployment performed.
- Backend: `python -m pytest -q` passed; 1151 tests collected, five skipped (1146 passed). One upstream Starlette TestClient deprecation warning.
- UI: focused and full `npm test` both passed (6 tests); `npm run build` passed, including docs generation, TypeScript, and Vite.
- Runtime: `ironledger-workbench` reports healthy, but `/api/staging` and authenticated `/api/sync/status` return 500. `/healthz` does not establish database health.
- Database: normal read-only SQLite open fails (`unable to open database file`). Immutable read-only `quick_check` reports malformed btree pages; foreign-key check raises `database disk image is malformed`. Immutable inspection is diagnostic only, not a healthy/live consistency proof.
- Container config has `IRONLEDGER_JOURNAL_MODE=DELETE`; actual database journal mode could not be verified after integrity failure.
- Version authority: root `VERSION` remains `0.15.0` and supplies app/docs version. Python package `0.0.0` and private web package `0.1.0` are packaging metadata; phase milestones are not release versions. No release bump approved here.

## Next Action
Investigate and recover the malformed live database under a separately reviewed recovery plan. Preserve damaged files and verify receipt/evidence losses before replacing data; do not write from the host while compose runs. Then repeat integrity and authenticated endpoint checks. Conflicting categorization targets and a real PDF statement profile remain operator work. Inbound email webhook stays dark until `IRONLEDGER_INBOUND_EMAIL_SECRET` is set. See `docs/meta/roadmap.md`.

## Verification Process Note
- Windows ACLs permit writes under this checkout. If Codex restricted process reports Permission denied, classify as sandbox enforcement; rerun repo-writing build/test steps elevated. Use PYTHONDONTWRITEBYTECODE=1 for syntax checks to avoid __pycache__ writes.

## Local Workbench Runtime
- Compose default: `http://127.0.0.1:8000`.
- Documented Windows fallback (not verified in this check): `http://127.0.0.1:8765` via `IRONLEDGER_HOST_PORT=8765 docker compose up -d` (host port `8765` mapped to container port `8000`).

