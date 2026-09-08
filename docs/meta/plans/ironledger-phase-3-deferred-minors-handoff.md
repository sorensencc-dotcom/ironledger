# IronLedger Phase 3 — deferred-minors handoff packet

Hand-off for another CLI (Codex preferred). Picks up the remaining Minor
follow-ups from the Phase 3 whole-branch review. The two Important items
(R-FIN-1, beancount version) and one hardening bundle (R-FIN-2, R-FIN-3,
orphan staging, fail_compile_run guard, live_matches_prev) are already done
and committed by Claude.

## Repo state at hand-off

- Branch `main`, HEAD `aac2270` (`= ac18f55` + this doc's own add commit).
  Work in a writable checkout — `C:\dev\dev-sandbox\ironledger-phase3` — not
  the read-only `C:\dev\IronLedger`.
- Suite: `PYTHONPATH=src python -m pytest -q` → **339 passed, 2 skipped, 0 warnings**.
  Skips: `test_ingest_inbox` (symlinks), exit-contract item 6 (bean-check absent).
- No remote. D-0. All commits authored `Iron-Hammer <iron-hammer@ironledger.local>`
  (repo-local config) — leave that as-is.
- Untracked `.context/` and `.ijfw/` are not ours — do not touch.

## Hard boundary (non-negotiable)

1. Work only in the `C:\dev\dev-sandbox\ironledger-phase3` checkout on `main`.
   No branch, no remote, no push, no rebase, no `reset --hard`, no force-anything.
2. Do only the tasks below. No "while I'm here" edits, no refactors outside
   each task's named files.
3. One commit per task group, messages given below. TDD every behavior change:
   write the failing test, watch it fail, then fix.
4. Do not run a code review. Do not write "approved" / "LGTM" anywhere. Do not
   invoke any finishing / ship / merge / PR tooling.
5. Wrap every pytest run in a timeout: `PYTHONPATH=src timeout 120 python -m pytest -q`.
6. If a brief contradicts the live code in a way not covered here: STOP, write
   what you found, hand back. Do not guess past it.
7. Report back: the commit SHAs, the final suite count, any STOP note.

## Preconditions to verify first

```
pwsh -NoProfile -File C:\dev\scripts\verify-repo-context.ps1 -Path C:\dev\dev-sandbox\ironledger-phase3
```
must print branch `main`, `PREFLIGHT_PASS`. `git rev-parse HEAD` must be
`aac2270` (the tip that carries this doc). Baseline suite must be 339 passed /
2 skipped / 0 warnings before you start.

---

## Task M1 — CLI `compile status` must be read-only

**Files:** `src/ironledger/cli/__main__.py`, `tests/test_cli_compile.py`.

`_cmd_compile_status` (line ~215) calls `migrations.migrate(conn)`. `compile
status` is a read-only inspection command; running migrations as a side effect
of a status check is wrong.

- RED: add a test that opens a DB **already migrated**, then invokes
  `compile status` with `migrations.migrate` patched to raise — it must still
  exit 0. (Or assert `migrate` is not called: `patch(... ) as m; ...;
  m.assert_not_called()`.)
- GREEN: drop the `migrations.migrate(conn)` line from `_cmd_compile_status`
  only. Leave every other command's `migrate` call alone. If the status
  gatherers assume tables exist, guard them (`try/except sqlite3.OperationalError`)
  so a status check against a brand-new DB still returns "nothing compiled yet"
  with exit 0 — there is already a test asserting that behavior; keep it green.

**Commit:** `fix(cli): make compile status read-only (no implicit migrate)`

---

## Task M2 — derive migration count in tests, drop hard-coded 5

**Files:** `tests/test_manifests.py` (line 50), `tests/test_migration_0004.py` (line 51).

Both assert a literal `5`. Migration 0006 will silently break both.

- Replace the literal with a value derived from the migration source of truth.
  The module exposes `discover_migrations()` (there is no `MIGRATIONS`
  constant). E.g. `expected = len(migrations.discover_migrations())` (confirm
  the exact import path and that it takes no required args), then assert
  against `expected`.
- `test_migration_0004.py:51` asserts `current_version(db) == 5` after applying
  through 0004 — that one is genuinely "version after the last known migration
  at the time". Derive it the same way (max version discovered) rather than
  pinning `5`.
- No production change. Pure test hardening; suite count unchanged.

**Commit:** `test(ironledger): derive migration count from discover_migrations`

---

## Task M3 — strengthen exit-contract items 7 and 11

**File:** `tests/test_phase3_exit_contract.py` only.

- **Item 7** (`test_contract_7_bad_inputs_fail`, line ~118): currently calls
  `validate_approved_set(load_approved_set(db))` directly. The Section-14
  contract is about the *compile command* rejecting bad input. Change it to
  drive `compile_approved(db, tmp_path, now_utc=...)` and assert it raises
  `CompileInputError` (match string unchanged). Keep the existing parametrize
  cases. If a case only fails at `validate_approved_set` and not through
  `compile_approved`, note it — do not weaken the assertion.
- **Item 11** (`test_contract_11_recovery_table_rows_covered`, line ~161):
  currently only checks that six test *names* exist in two modules — it would
  pass even if all six were `pass`. Strengthen: import and *run-assert* the
  real recovery entrypoint is exercised, e.g. assert each named test's function
  object has a non-trivial body, OR (better) replace the name-existence check
  with 2-3 direct behavioral assertions on `recover_dangling_compile` covering
  distinct decision-table rows (none / pre-write-abort / staging-mismatch).
  Keep it in this file; do not duplicate the full recover suite.

Suite count rises by however many assertions you add; no drops, no FAILs.

**Commit:** `test(ironledger): tighten Phase 3 exit-contract items 7 and 11`

---

## Task M4 — add CLI exit-1 and `compile recover` coverage

**File:** `tests/test_cli_compile.py` only (new tests).

There is no test that the `compile` CLI returns exit code 1 on
`CompileInputError` / `BeanCheckFailedError` / `CompileError`, and no test of
the `compile recover` subcommand at all.

- RED/GREEN not needed for production (wiring already exists) — these are
  coverage tests, so they pass on first write. That is acceptable *only* here.
- Add: `compile` with a seeded bad approved set → process exit 1.
- Add: `compile recover` with nothing dangling → exit 0, output contains the
  "nothing to recover" line from `render_recovery_report`.
- Add: `compile recover` driving an actual dangling started run to `recovered`
  (reuse the `_seed` + crash-injection pattern from
  `tests/test_compile_recovery_integration.py`).
- Match the existing auth-mocking style in `test_cli_compile.py` (safe-mode
  file / `require_operator`). Do not invent a new pattern.

**Commit:** `test(cli): cover compile exit-1 path and compile recover subcommand`

---

## Task M5 — T1 checksum-frozen test: stop mutating the tracked schema file

**File:** `tests/test_migration_0005.py` (the checksum-frozen test, ~line 186).

It edits `schema/0005*.sql` in place and restores it in a `finally`. A hard
kill mid-test leaves the working tree dirty.

- Rewrite to copy all `schema/*.sql` into `tmp_path`, mutate the copy, and call
  the migrator against that directory: `migrations.migrate(conn,
  directory=tmp_path)` / `discover_migrations(directory=tmp_path)` — confirm the
  real keyword. The tracked file is never touched.
- Same assertion (a tampered migration body is detected), no production change.

**Commit:** `test(ironledger): isolate checksum-frozen test to a tmp schema dir`

---

## Task M6 — lint cluster

**Files:** `src/ironledger/compile/model.py`, `src/ironledger/compile/render.py`,
`src/ironledger/cli/__main__.py`, `tests/test_compile_hashing.py`,
`tests/test_phase3_exit_contract.py` (lines ~26, ~29),
`tests/test_cli_compile.py` (line ~6).

- Remove unused imports / params flagged by the review:
  `from typing import Final` in `model.py` (if still unused);
  unused `import pytest` + unused `ApprovedPosting` import + unused `year`
  param in `render.py`; unused `import pytest` in `test_compile_hashing.py`;
  unused imports at `test_phase3_exit_contract.py:26,29` and
  `test_cli_compile.py:6`.
- Collapse redundant single-element / duplicate `except (...)` tuples at
  `__main__.py:205` and in `_cmd_compile` around lines 220-221.
- Verify each removal with the suite. If removing a param changes a signature
  that a caller or test passes positionally, STOP and note it instead.
- No behavior change; suite count unchanged.

**Commit:** `chore(ironledger): drop unused imports and redundant except tuples`

---

## Not in scope (documented decisions, no action)

- `failed-<run_id>` quarantine dirs under `.staging/` are never auto-cleaned.
  This is deliberate — they hold `bean-check.txt` for operator forensics.
  Leave them; if anything, add a one-line comment near
  `writer.py` where `failed-<run_id>` is created saying so.
- Commit author reconciliation (`Iron-Hammer` → real identity) is deferred
  until the repo gains a remote. Do not rewrite history.

## After all tasks

Hand back with the six commit SHAs and the final `PYTHONPATH=src timeout 120
python -m pytest -q` count. A Claude session runs the reviews and the branch
finish; do not run them yourself.
