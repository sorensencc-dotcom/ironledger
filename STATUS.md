# IronLedger Project Status

## Active Goal
Stabilize the shipped Phase 18 workbench: verify runtime/database health, finish the split-line total UI repair, and refresh the regression baseline. Live database recovered and moved to native Docker storage on 2026-10-07. Integrity and authenticated APIs pass, including after restart.

## Milestone Status: Phase 18 Shipped; Runtime Stabilization Open
- **Preceding Baseline:** Phase 16 Subscriptions & Recurring Intelligence Engine v0.16.0 (1095 passed, 4 skipped).
- **Current isolated regression baseline (2026-10-07):** 1159 passed, 5 skipped (1164 collected); UI 6 passed; production UI build passed. Initial live runtime checks failed; post-recovery checks pass.
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

## Verification Snapshot â€” 2026-10-07
- Initial source baseline: main `fde1262`, plus the scoped split-total helper/tests. Initial checks made no live financial writes; the separately authorized recovery/deployment is recorded below.
- Backend: `python -m pytest -q` passed; 1164 tests collected, five skipped (1159 passed), after the receipt repair. One upstream Starlette TestClient deprecation warning.
- UI: focused and full `npm test` both passed (6 tests); `npm run build` passed, including docs generation, TypeScript, and Vite.
- Initial runtime failure: `ironledger-workbench` reported healthy, but `/api/staging` and authenticated `/api/sync/status` return 500. `/healthz` does not establish database health.
- Initial database failure: normal read-only SQLite open fails (`unable to open database file`). Immutable read-only `quick_check` reports malformed btree pages; foreign-key check raises `database disk image is malformed`. Immutable inspection is diagnostic only, not a healthy/live consistency proof.
- Initial config had `IRONLEDGER_JOURNAL_MODE=DELETE`; actual mode was unverified until recovery. Current mode is confirmed DELETE.
- Version authority: root `VERSION` remains `0.15.0` and supplies app/docs version. Python package `0.0.0` and private web package `0.1.0` are packaging metadata; phase milestones are not release versions. No release bump approved here.

## Recovery and Runtime Fix — 2026-10-07
- Damaged database preserved outside the checkout at `C:/dev/dev-sandbox/ironledger-recovery-20261007/damaged.db`, SHA-256 `0B27D223816BABECE933C51CD452010F7C6DAA22A2AC83D37047B5709F7E8F8C`. Original host `ironledger.db` remains untouched and is not the runtime database.
- SQLite `.recover` produced an offline candidate with the original schema and all readable table counts preserved. Fourteen missing source-document rows were reacquired from original hash-verified receipt bytes with explicit recovery provenance/current acquisition time. Three missing orders and 16 lines were regenerated by the existing parser; restored lines use parser categories or Uncategorized and still require review. Eight existing pending proposals regained their order references. No placeholder evidence was fabricated.
- Staged decisions preserved: 450 approved, 268 categorized, 294 pending. All 722 recovered split proposal identities/statuses preserved. Historical completeness of tables unreadable before recovery cannot be proven; recovered `lost_and_found` entries are retained for forensic inspection.
- Runtime database: Docker volume `ironledger-database`, `/var/lib/ironledger/ironledger.db`, journal mode DELETE. Evidence remains on `/data/evidence`; a volume-local symlink supports receipt ingestion's database-relative evidence directory.
- Consistent post-deployment SQLite backup saved as `C:/dev/dev-sandbox/ironledger-recovery-20261007/deployed-snapshot.db`; recovery SQL, forensic entries, and test XML remain alongside it.
- Full `integrity_check` is `ok`, foreign-key violations are zero, and staging, authenticated sync status, and split proposal APIs return 200. Checks passed again after restart.
- Default scheduled pollers execute inside the container against this same database; explicit alternate `DbPath` still supports isolated host databases. Missing/stopped container fails rather than silently writing the stale host copy. Routing checks pass for all three pollers.
- Readiness now runs SQLite `quick_check(1)` instead of `SELECT 1`; compose health checks readiness. A real corrupt-page regression test proves liveness can remain 200 while readiness returns 503.
- Attempt to pause scheduled tasks was denied by Windows; task settings were not changed. Tasks remain Ready and their scripts now route writes to the container. External Sentinel file-size inspection still observes the stale host copy; use readiness and container integrity checks as database-health evidence.

## Receipt Review and Repair — 2026-10-07
- Three rebuilt orders/16 lines reviewed against original receipts: summary rows became products, a credit became positive, and stale receipts matched unrelated current transactions. Eight proposals rejected through authenticated operator API, with eight audit records. Audit chain passes; staged decisions and postings unchanged.
- Parser recognizes receipt summary variants and discounts, reconciles stated totals/subtotals, and rejects unsupported negative amounts. Order references require digits. Shared linker and confirmation require merchant agreement and dates within seven days; Amazon/AMZN alias applies only to Amazon. Unknown merchants/invalid dates fail closed. Other abbreviated merchants may require evidence-backed aliases later.
- Original receipt totals now $208.00, $124.99, $121.19. November receipt has no inline product prices, so subtotal is one low-confidence Uncategorized aggregate. No product details fabricated. Corrected receipts create zero proposals on an in-memory live-database clone. Old rejected order/line rows retained as historical parse evidence; no ID rewrites or confirmations.
- Focused parser/linker/web/MCP tests: 26 passed. Full suite: 1159 passed, 5 skipped. Live integrity ok, foreign keys zero, readiness/staging/sync 200 after deployment. Logs/XML and before-action snapshot retained in the recovery directory.

## Next Action
Resolve conflicting categorization targets and validate a real PDF statement profile. All eight unsafe recovered proposals are rejected; do not resurrect their old parsed order data. Use `docker compose exec -w /data ironledger` for operational database writes and back up the native-volume database with SQLite backup; host `ironledger.db` is a preserved damaged artifact, not current state. Never delete the database volume as routine cleanup. Inbound email webhook stays dark until `IRONLEDGER_INBOUND_EMAIL_SECRET` is set.

## Verification Process Note
- Windows ACLs permit writes under this checkout. If Codex restricted process reports Permission denied, classify as sandbox enforcement; rerun repo-writing build/test steps elevated. Use PYTHONDONTWRITEBYTECODE=1 for syntax checks to avoid __pycache__ writes.

## Local Workbench Runtime
- Compose default: `http://127.0.0.1:8000`.
- Documented Windows fallback (not verified in this check): `http://127.0.0.1:8765` via `IRONLEDGER_HOST_PORT=8765 docker compose up -d` (host port `8765` mapped to container port `8000`).

