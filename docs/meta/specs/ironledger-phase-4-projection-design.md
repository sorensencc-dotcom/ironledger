# IronLedger Phase 4 analytics and search projection design

Status: design for operator review; no implementation approval.
Scope: rebuild a disposable SQLite projection by parsing the compiled Beancount ledger, activate it atomically, and expose a local `search` and `balances` CLI. MCP, network listeners, date/account filters, category rollups, runway, and health stay out of scope.

Locked in the Phase 4 brainstorm (2026-09-08): local search/balances CLI; parse Beancount files as authority; search + per-account balances only; separate `ironledger project` command; sibling `projection/` tree; phrase + safe mode like compile; dialect parser dual of `render.py` with single-file `os.replace`.

## 1. Why this phase exists

Phase 3 writes the accounting record (`ledger/main.beancount`, `ledger/accounts.beancount`, `ledger/txns/YYYY.beancount`) and a workflow index inside the operational `--db`. That index is not the analytical store. Architecture already says SQLite is a disposable, rebuildable projection and that FTS is maintained by explicit rebuild logic. Phase 4 is that projection: parse the files we just compiled, load a separate SQLite file, and let the operator search and read balances without standing up MCP.

Deleting the projection must not delete accounting truth. Rebuilding it from the same ledger bytes must reproduce the same accounts, postings, balances, and FTS hits.

## 2. Fixed invariants inherited

- Beancount plus retained source evidence is the sole accounting authority. The projection is a cache.
- Monetary values are signed integer minor units with an explicit currency and scale from `src/ironledger/reference/iso4217.v2026-01.json`. No floating-point accounting arithmetic. Unlike currencies are never netted.
- Timestamps are ISO-8601 UTC with a trailing `Z`.
- Every posting in the projection carries the source and identity metadata emitted by the Phase 3 renderer.
- Mutation-capable operations require an explicit operator-authorization phrase, are blocked by safe mode, and emit an append-only audit event.
- Mutation-capable processes are serialized with an exclusive lock.
- `beancount` is never imported under `src/ironledger`. `bean-check` remains the Phase 3 validator; this phase does not shell out to it.
- Windows is a first-class host. Activation is `os.replace` of a checkpointed SQLite file, not a symlink flip.

## 3. Layout

`--ledger-dir` names the Beancount tree (the same path compile already uses). The live projection is the sibling:

```
<parent>/
  ledger/          # --ledger-dir
    main.beancount
    accounts.beancount
    txns/YYYY.beancount
    .staging/
    .compile.lock
  projection/      # sibling; override with --projection-dir
    projection.sqlite
    projection.manifest.json
    .staging/<build_id>/
    .project.lock
```

`--projection-dir` overrides the sibling default. Search and balances open `projection/projection.sqlite` only. They do not open `--db`.

## 4. Parser

Module: `ironledger.project.parse`.

It reads only the Phase 3 dialect:

- `main.beancount`: `option "title" "…"`, one or more `option "operating_currency" "CUR"`, `include "accounts.beancount"`, `include "txns/YYYY.beancount"` for each year file present. Includes are relative to `ledger/`.
- `accounts.beancount`: `YYYY-MM-DD open Account:Name CUR` (LF, one account per line, sorted as the renderer emits; parser does not require sort, rebuild will store sorted).
- `txns/YYYY.beancount`: entries of the form Phase 3 §4.1. Flag is `*`. Entry metadata: `staged-transaction-id`. Posting order: imported then contra. Posting metadata: `source-document-id`, `source-record-id`, `identity-algo-version`, `identity-method`. Amounts are the inverse of `format_amount`: scale comes from the ISO-4217 table for that posting’s currency, not from counting decimal digits (JPY `100` is scale 0; USD `12.34` is scale 2). A fractional string that is not exactly representable at that scale is a parse error.

Closed dialect. No `import beancount`. Unknown directive, missing include, extra metadata key, missing required metadata key, invalid account, unknown currency, or a posting that does not invert cleanly raises `ProjectParseError`. Rebuild aborts. Live projection is untouched.

The parser is tested as a round trip: `render_ledger(approved_set)` written to a temp ledger → parse → same accounts, currencies, `open` dates, entry dates, payee, narration, posting accounts, minor units, scales, and metadata.

`bean-check` is not invoked here. Phase 3 already refused to activate a ledger that failed `bean-check`. Phase 4 refuses a ledger whose bytes do not match the latest successful compile hash (section 6).

## 5. Projection schema

Separate SQLite file. Not a migration on the operational `--db`. Projection schema version 1, applied by a dedicated projector migrator (do not reuse `ironledger.db.migrations` against this file; that runner is bound to 0001–0005 workflow tables).

STRICT tables, integer money, currency on every money row:

- `projection_meta` — exactly one row: `compile_run_id`, `ledger_input_hash`, `ledger_output_hash`, `schema_version`, `built_at_utc`, `beancount_version`, `compiler_version`.
- `proj_accounts` — `account` PRIMARY KEY, `currency`, `open_date`. One currency per account. A second currency for the same account is a rebuild refusal (`ProjectInputError`).
- `proj_entries` — `entry_id` PRIMARY KEY, `entry_date`, `payee`, `narration`, `staged_transaction_id` UNIQUE.
- `proj_postings` — `posting_id` PRIMARY KEY, `entry_id` REFERENCES `proj_entries` ON DELETE CASCADE, `account`, `minor_units` INTEGER, `currency`, `minor_unit_scale`, `source_document_id`, `source_record_id`, `identity_algo_version`, `identity_method`. No FK into the operational DB.
- `proj_balances` — PRIMARY KEY `(account, currency)`, `minor_units` INTEGER, `minor_unit_scale`. Materialized during rebuild as `SUM(minor_units)` of `proj_postings` grouped by `(account, currency)`. `balances` reads this table. Two currencies for one account are two rows; the CLI never adds them.
- `proj_fts` — FTS5 with columns `payee`, `narration`, `account`, `posting_text`. `posting_text` is a plain-text bag: account, formatted amount, currency, identity method, identity algo version. Rows are posting-grained and carry `posting_id` as UNINDEXED for join-back. Filled with explicit INSERTs during rebuild. Triggers are not the correctness authority.

WAL mode is allowed during the staging build. Before activate, `PRAGMA wal_checkpoint(TRUNCATE)` and close the connection so `-wal`/`-shm` are absent.

## 6. Build and activate

`ironledger project` is the only mutator in this phase.

Authorization: `require_operator` with `action="project"`, `subject="project"`. Add `PROJECT_PHRASE = "authorize project"` and `_PREFIX["project"] = "authorize"` in `cli/auth.py` (same pattern as compile). Safe mode denies. Audit `action=project`, `result=ok|denied|error`, `compile_run_id` when known.

Steps:

1. Acquire `projection/.project.lock` with `os.open(O_CREAT|O_EXCL|O_WRONLY)`, self-describing body, same cleanup rules as `acquire_compile_lock`. Held → `ProjectLockedError`, exit 1, live files untouched.
2. Require a latest successful compile run in `--db` (`get_latest_successful_run`). None → refuse.
3. Compute `compute_actual_output_hash(ledger_dir, year_files)` over the files now on disk. Must equal that run’s `actual_output_hash`. Mismatch → refuse (`ProjectHashMismatchError`). The operator’s next move is `compile status` / `compile recover`, not a projection rebuild from a journal/file split brain.
4. Parse. `ProjectParseError` → refuse.
5. Write `projection/.staging/<build_id>/projection.sqlite`. Create schema, insert accounts/entries/postings, build `proj_balances` and `proj_fts`, write `projection_meta`, checkpoint, close.
6. Write `projection/.staging/<build_id>/projection.manifest.json` via `generate_projection_manifest` pointed at the staging DB (`manifest_kind=projection_manifest`, `compile_run_id` and ledger hashes from `projection_meta`).
7. `os.replace` the staging sqlite onto `projection/projection.sqlite`, then `os.replace` the staging manifest onto `projection/projection.manifest.json`. Copy-in-staging, then replace. Crash before the sqlite replace: live projection is the previous complete file or absent. Crash between sqlite replace and manifest replace: `project status` reports mismatch; search/balances fail closed and tell the operator to rebuild.
8. Remove the staging directory. Audit success. Release the lock.

No Phase-4 recovery journal. Re-run `project` is always safe: it only replaces after a complete staging DB exists.

## 7. Freshness

Search and balances never rebuild as a side effect.

They take `--ledger-dir` (and optional `--projection-dir`). They do **not** require `--db`. Freshness is vs the files on disk:

- Live `projection.sqlite` exists.
- Manifest parses and `verify_manifest` succeeds against that file.
- `projection_meta.ledger_output_hash` equals `compute_actual_output_hash` of the current ledger files.

Any failure → exit 1, no rows, message to run `ironledger project`. A successful compile that has not been followed by `project` changes the file hash and fails closed here.

`project status` uses the same file-hash check. With `--db` it also prints whether that hash equals the latest successful compile run (the same comparison rebuild step 3 uses). Missing projection is a valid status, exit 0, “nothing built yet”.

## 8. CLI

| Command | Auth | Opens | Notes |
|---|---|---|---|
| `ironledger project` | phrase `authorize project`, safe mode | `--db`, `--ledger-dir`, projection dest | Rebuild + activate |
| `ironledger project status` | none | `--ledger-dir`, optional `--db` | Read-only. No lock. No `migrations.migrate`. |
| `ironledger search <query>` | none | projection sqlite + ledger files for hash | FTS5 `MATCH` with bound parameter. `--limit` default 50, hard max 500. `--offset` default 0. One output row per matching posting: date, payee, narration, account, minor_units, currency, staged-transaction-id. |
| `ironledger balances` | none | same as search | One line per `proj_balances` row, sorted by account then currency. |

`--json` on status, search, and balances. Exit codes: `0` success, `1` parse/hash/lock/stale/missing projection (for search/balances), `3` authorization or safe-mode denial.

`search` / `balances` / `project status` do not call `require_operator` and do not take the compile lock or the project lock.

## 9. Module layout

```
src/ironledger/project/
  __init__.py
  parse.py       # closed dialect
  schema.sql     # projection schema v1
  migrate.py     # apply schema.sql to a new connection
  builder.py     # staging write, balances, FTS, meta
  activate.py    # lock, hash check, os.replace, checkpoint
  query.py       # search + balances on a live connection
  errors.py      # ProjectParseError, ProjectHashMismatchError, ProjectLockedError, ProjectStaleError, ProjectInputError
```

CLI wiring in `cli/__main__.py` and phrases in `cli/auth.py`. Renderers for human and JSON output in `cli/render.py`. No new runtime dependency. Optional extra `dev` already pins `beancount==3.2.3` for `bean-check`; Phase 4 does not add a package.

## 10. Out of scope

- Read-only MCP and any network listener (Phase 5).
- Date range, account-prefix filters, category rollups, runway, health.
- Folding rebuild into `ironledger compile`.
- `import beancount` or a `bean-query` subprocess.
- Symlink activation.
- Rewriting or deleting the operational `ledger_entries` / `ledger_postings` index.
- Git add/commit/push of `ledger/` or `projection/`.
- Automatic rebuild as a side effect of search.

## 11. Test contract for the Phase 4 exit gate

All items below are gate-blocking. Named tests in `tests/test_phase4_exit_contract.py` plus the focused modules they call.

1. Render → write temp ledger → parse round trip preserves accounts, `open` dates, currencies, entry dates, payee, narration, posting accounts, minor units, scales, and metadata.
2. Unknown directive, extra metadata key, missing required metadata, and a non-inverting amount each raise `ProjectParseError` and leave any pre-existing live projection byte-identical.
3. Rebuild from a valid compiled ledger: `proj_balances.minor_units` equals `SUM(proj_postings.minor_units)` per `(account, currency)`.
4. Seeding a second currency on one account refuses the rebuild (`ProjectInputError` or parse/input error). `balances` never prints a single number for two currencies.
5. Delete `projection/projection.sqlite` (and the manifest) and rebuild: same `proj_accounts` / `proj_entries` / `proj_postings` / `proj_balances` row counts; same FTS hit `posting_id` set for a fixed query; a payload digest over those tables excluding `projection_meta.built_at_utc` is identical. Manifest `created_ts_utc` / self-hash may differ.
6. FTS: payee, narration, account, and posting_text each match the seeded posting; changing narration in the Beancount file and rebuilding changes the hit set.
7. Crash before the sqlite `os.replace`: live file is the previous complete projection, or absent if there was none.
8. Sqlite `os.replace` then crash before manifest replace: `project status` reports mismatch; `search` and `balances` fail closed (exit 1).
9. Safe mode and wrong phrase deny `project` (exit 3, `result=denied` audit). `search`, `balances`, and `project status` do not call `require_operator`.
10. After a new successful compile (new `actual_output_hash`) without `project`: `search` and `balances` exit 1 (stale).
11. No source file under `src/ironledger` contains `import beancount`.
12. Full suite does not drop below the Phase 3 baseline (343 passed / 1 skipped on this host with `bean-check` on PATH; 342 / 2 without). Phase 4 tests only add.

## 12. Open items carried into the plan, not this spec

- FTS5 tokenizer: use SQLite’s default `unicode61` unless a plan task finds a documented reason to pin something else.
- Exact human-readable column layout of `search` / `balances` text (tests lock substrings in the plan, as Phase 3 render tests did).
- Whether `project status --json` includes the latest compile run when `--db` is omitted (it must not; omit that object).

## 13. Approval gate

Phase 4 requires operator review of this design, then a TDD implementation plan, then operator approval of that plan in the transcript before any code. Phase 3 remains the compile authority. Any change to Beancount authority, evidence retention, default read-only access, network exposure, or automatic publication requires a design amendment and renewed approval.
