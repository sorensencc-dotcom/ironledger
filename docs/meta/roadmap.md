# IronLedger roadmap

Checked 2026-10-07 after recovery. Workbench at `http://127.0.0.1:8000`: integrity `ok`, zero foreign-key violations, staging/authenticated sync/split APIs 200, including after restart. Runtime database now lives on native Docker volume `ironledger-database`; root host `ironledger.db` is the preserved damaged copy. See `STATUS.md` for recovery limits and test evidence.

## Database

Historical repair evidence (2026-10-02; superseded by the failed 2026-10-07 check): `PRAGMA quick_check` is `ok` inside the running container, foreign-key check is 0, and `GET /api/staging` and `GET /api/sync/status` return 200. Staged totals survived: 449 approved, 294 pending, 269 categorized. `source_documents` reads (503 rows). Sixteen itemized orders point at stub documents (`provenance=db-recover-20261002`) because those receipt bytes were on corrupt pages.

Current runtime uses native Docker storage and forces `IRONLEDGER_JOURNAL_MODE=DELETE`. WAL on the Docker Desktop bind mount is what corrupted this file on 2026-09-24 and again on the first restart after recover. Snapshots of the bad files are `backup-20261002-malformed/` and `backup-20261002-poststart/`. Host `ironledger.db` is stale/damaged; operational writes must run inside the container against `/var/lib/ironledger/ironledger.db`.

## Shipped — Phase 18

Phase 17 left the multi-leg compiler, migration 0021, and the Amazon, Venmo, and email normalizers. Phase 18 closed the loop below.

| Item | Where it landed |
|---|---|
| IMAP receipt polling | `src/ironledger/ingest/imap_poller.py` (stdlib poller, `password_env` secrets, UID state). The scheduled operator path is `scripts/sweep_receipts.py` plus `scripts/setup-scheduled-tasks.ps1` (`IronLedger-Receipt-Sync`). |
| Split proposal review | Confirm and reject in `web/src/components/InspectorSidecar.tsx`, backed by `/api/staging/splits/proposals`. |
| Partial-shipment matching | Integer subset-sum and prorated tax, shipping, and discount in `src/ironledger/ingest/split_linker.py`. Selected lines persist in `src/ironledger/db/schema/0022_partial_shipment_proposals.sql`. |
| Taxonomy editor | `config/taxonomy.json`, `src/ironledger/web/routers/taxonomy.py`, rules view in the workbench. Edits reload by mtime. |

## Shipped after the repair

| Item | Where it landed |
|---|---|
| Rollback journal on the bind mount | `IRONLEDGER_JOURNAL_MODE=DELETE` in `docker-compose.yml`. `connect()` honors that env var. |
| Compose-guard coverage | Warns before `compliance generate`, `anomaly scan`, `anomaly resolve`, `federation outbox dispatch`, `failover promote`, and `security rotate-key`. List, status, and `compliance verify` stay quiet. |
| Web runtime dependencies | `pyproject.toml` declares FastAPI, uvicorn, pydantic, starlette, cryptography, jsonschema, keyring, psutil, and python-multipart. `beancount` stays a dev extra. |
| Inbound email webhook | `POST /api/webhooks/inbound-email`. Body is the raw RFC 822 message. `X-IronLedger-Signature` is the existing `t,e,d,v1` HMAC with a 300 second window. `d` is stored in `inbound_email_deliveries` (migration 0023) and rejected on replay. A valid receipt is acquired and sent through `propose_splits_for_order`. |
| Identical categorization rules | Ten extra active rows with the same pattern, match type, account, target, and priority were disabled on 2026-10-02. |

The inbound route stays dark until `IRONLEDGER_INBOUND_EMAIL_SECRET` is set. An empty secret returns 503.

## Open

0. **Recovery follow-up (2026-10-07).** Receipt review complete: all eight unsafe proposals rejected with audit records. Shared parser totals corrected; linker/confirmation require merchant agreement and a seven-day date window. Corrected original receipts produce zero current matches; old rejected parsed rows remain historical evidence. Historical completeness of previously unreadable tables is unproven; retained damaged snapshot and recovered lost-and-found support further audit. External Sentinel still checks host file size rather than native-volume integrity.

1. **Conflicting categorization rules.** These patterns still have more than one active target, so rule resolution can pick either one: `hbo max new york ny`, the full SunPass payee, `sunpass`, `paws n rec`, `publix`, `contribution`, `anthropic`, `textmuncher`, `trupanion`, `uber trip help.uber.com ca`, `link.com* simplefin br`, and `royalcaribbean.com (866)562-7625 fl`. Identical copies are already disabled. Choosing the target is an operator decision.

2. **Real PDF statement profile.** The only profile in git is `config/pdf-profiles/example-card.json`. A real statement has not been checked in.

3. **Operator queue, still unread as decisions.** 294 pending and 269 categorized. Pending includes core-account cash sweeps and card or ACH payments that post both sides. Nothing in that queue was auto-categorized during the repair.

## Parked

- OCR. Text-layer PDFs only. Empty text fails closed.
- Packaging. Root `VERSION` (`0.15.0`) supplies app/docs version. Python package `0.0.0` and private web package `0.1.0` remain packaging metadata. Phase numbers do not imply a released version; no bump in this stabilization pass.
- Identity v2. Confirm-attach must leave the target fingerprint, payee, and narration unchanged.
- Auto-attach. A unique hit still requires an operator confirm.

## Invariants

- Plaintext Beancount is the accounting authority. SQLite is a disposable projection.
- Money math stays integer minor units. No float division on the money path.
- Zero runtime `import beancount` in `src/ironledger`.
- One confirmed economic event gets more evidence, never a second posting.
