# IronLedger Phase 3 evidence and exit verification

Status: Phase 3 exit gate approved by the operator in the session transcript on 2026-09-08. Phase 4 may start.
Scope: compile approved staged transactions into canonical Beancount, validate with `bean-check` as a subprocess, write the ledger atomically, journal every run, and recover an interrupted compile deterministically or refuse. Focused-suite evidence only. Analytics projection, FTS, MCP, SimpleFIN, RAG, mobile, backups, and Git publication of `ledger/` stay out of scope.

## 1. Provenance of this evidence

Phase 3 was implemented against `docs/meta/plans/ironledger-phase-3-plan.md` (commit `24f30ad`) and the design spec `docs/meta/specs/ironledger-phase-3-compiler-design.md` (on `C:\dev` branch `ironledger/phase-3-spec`; not present in this checkout). Tasks 1-13 ran under subagent-driven development. Tasks 14-15 (CLI wiring and the 17-item exit contract) were implemented in a bounded Antigravity packet and then reviewed in this repo; the dependency-posture doc was rewritten by hand after a shell-heredoc corruption (`\b` ate `beancount` / `bean-check` and stripped code spans). A whole-branch review (`4d77e5a..c1a42f8`) returned merge-with-fixes, no Critical. The load-bearing crash-window fixes, then the two Important follow-ups and the remaining minors, landed on `main` before this document.

Every number in section 4 comes from a test run executed against `HEAD` `93269f6` on 2026-09-08 in this session, after installing `beancount==3.2.3` so `bean-check` was on `PATH`. It is not copied from an implementer report.

`[tool.ironledger] phase = 3` in `pyproject.toml`. Branch-finish for the implementation work was keep-as-is (D-0 on `main`, no remote). That is not this gate. This document is the operator-review artifact required by the implementation plan. The operator approved it in this session.

## 2. Repository and environment state

| Item | Value |
|---|---|
| Repository path | `C:\dev\IronLedger` (operator-approved home, D-0) |
| Git branch | `main` |
| HEAD | `93269f6` (`test(cli): cover compile exit-1 path and compile recover subcommand`) |
| Phase 3 range | 35 commits, `4d77e5a..93269f6` (`4d77e5a` = Phase 2b approval re-apply; `24f30ad` = plan) |
| Upstream remote | None configured. Do not push. |
| Preflight | `verify-repo-context.ps1 -Path C:\dev\IronLedger` → `PREFLIGHT_PASS` on `pyproject.toml` |
| Toolchain | Python 3.14.6, pytest 9.1.1, SQLite 3.50.4 (stdlib `sqlite3`) |
| Working tree | Clean except untracked `.context/` and `.ijfw/` (not this phase) |
| Commit author | All 35 commits authored `Iron-Hammer <iron-hammer@ironledger.local>` (repo-local config). `backup/pre-author-rewrite-20260908` holds the pre-rewrite tip `4abb71f`. |
| Compiler version | `ironledger.compile.beancheck.COMPILER_VERSION = "0.1.0"` |
| `beancount` Python dep | None on the runtime path. Optional extra `dev` pins `beancount==3.2.3` for the `bean-check` CLI. `src/ironledger` does not `import beancount`. |
| `bean-check` on this host | `Beancount 3.2.3` (`%APPDATA%\Python\Python314\Scripts\bean-check.EXE`). That Scripts dir is not on the default user `PATH`; the evidence run prepended it. |

### 2.1 What shipped

`src/ironledger/compile/` (`model`, `render`, `hashing`, `beancheck`, `journal`, `writer`, `recover`, `errors`). Migration `0005_compile_journal.sql` (append-only journal, `RAISE(ABORT)` on `UPDATE`/`DELETE`). CLI:

- `ironledger compile --ledger-dir <dir>` (mutator)
- `ironledger compile status --ledger-dir <dir>` (read-only; does not call `migrations.migrate`)
- `ironledger compile recover --ledger-dir <dir>` (mutator)

Ledger layout unchanged from Phase 1: `ledger/main.beancount`, `ledger/accounts.beancount`, `ledger/txns/YYYY.beancount`. Writes go through `ledger/.staging/<run_id>/` then `os.replace`. Exclusive lock is `ledger/.compile.lock` (`O_CREAT|O_EXCL`).

### 2.2 Commit groups (`4d77e5a..HEAD`)

| Group | Tip / range | What |
|---|---|---|
| Plan | `24f30ad` | Phase 3 implementation plan |
| Schema + core | `dc9b343` .. `5595a35` | migration 0005, model, render, hashing, bean-check runner, journal, lock/staging, atomic replace + index |
| Recovery | `27f70ae` `f7b0fb0` | decision table + crash-injection at `os.replace` |
| Auth + CLI | `153cdc7` `6044227` `81b9788` | phrases, renderers, `compile` / `status` / `recover` |
| Exit contract | `bddd738` .. `c1a42f8` | 17-item suite, dep-posture rewrite, `integration` marker, timeout 10s, LF |
| Crash-window fix wave | `e102aef` `10972f2` | atomic lock, index-before-finish, stale-year prune, refusal audit, phase=3, `*.sql` LF |
| SDD ledger archive | `a3b7aa4` | `docs/meta/plans/ironledger-phase-3-plan-sdd-ledger.md` |
| Important follow-ups | `ca18f87` `11b4d15` `ac18f55` | recover.py index-before-status, `bean-check --version`, lock/audit/staging hardening |
| Minors M1-M6 | `4736b42` .. `93269f6` | read-only status, derived migration count, tighter items 7/11, checksum-isolated, lint, CLI exit-1 + recover |

The SDD workspace `.superpowers/sdd/ironledger-phase-3-plan/` was deleted after the final review. The ledger in git is the record.

## 3. Dependency posture

Recorded in `docs/meta/ironledger-dependency-posture.md` (Phase 3 amendment). Summary:

- Runtime core still has one third-party import: `ofxtools==1.1.1` (Phase 2a, OFX parse only).
- `beancount` is not a Python dependency. The compiler renders plaintext Beancount in `compile/render.py` and shells out to `bean-check` with a 10.0s timeout (`compile/beancheck.py`).
- Missing binary → `BeanCheckUnavailableError` before a `compile_runs` row is inserted. Ingest, review, rules, and migrations stay usable.
- `beancount_version` is taken from `bean-check --version`, then `importlib.metadata.version("beancount")`, then `"unknown"`.

## 4. Focused acceptance run (2026-09-08)

From `C:\dev\IronLedger`:

```powershell
$env:PATH = "$env:APPDATA\Python\Python314\Scripts;" + $env:PATH
$env:PYTHONPATH='src'; python -m pytest -q
```

```text
343 passed, 1 skipped in 4.87s
```

Item 6 alone: `tests/test_phase3_exit_contract.py::test_contract_6_real_bean_check_passes` → `1 passed in 1.13s`.

Zero `PytestUnknownMarkWarning`. Remaining skip:

| Skip | Why |
|---|---|
| `tests/test_ingest_inbox.py` (symlink-escape) | Windows privilege / symlink unavailable. Pre-existing since Phase 2a. |

Baseline into Task 1 was 254 passed / 1 skipped. Phase 3 added the compile package, migration 0005, CLI, the 17-item contract, crash-injection, and the follow-up tests.

## 5. Spec §14 test-contract mapping

Each of the 17 numbered items in the Phase 3 design spec §14 maps below. Gaps are in section 6, not hidden in the PASS column.

| # | Spec requirement | Covering test(s) | This-host result |
|---|---|---|---|
| 1 | `render.py` byte-identical across two runs and a reordered input set | `test_contract_1_render_byte_identical` | PASS with gap: same `ApprovedSet` rendered twice; no permutation of input order. `render_ledger` is a pure function of a frozen tuple, so two calls match by construction. Reordered-input is untested in the contract file. |
| 2 | Amount formatting: negative, zero, scale 0 | `test_contract_2_amount_formatting` (`-1234/2` → `-12.34`, `0/2` → `0.00`, `5/0` → `5`) | PASS |
| 3 | Entry order, posting order (`imported` then `contra`), `open` order | `test_contract_3_order`; deeper coverage in `tests/test_compile_render.py` | PASS with gap: contract test only asserts `imported` appears before `contra` in one year file. Multi-year / `open` sort is not in the contract file. |
| 4 | Quote and backslash escaping | `test_contract_4_escaping` | PASS |
| 5 | `input_hash` / `intended_output_hash` stable across runs and change when the set changes | `test_contract_5_stable_hashes`; `tests/test_compile_hashing.py` | PASS with gap: contract test only asserts `len(h1)==64`. Stability and change-on-delta live in `test_compile_hashing.py`, not in the named contract item. |
| 6 | Valid set compiles and **real** `bean-check` passes | `test_contract_6_real_bean_check_passes` (`@pytest.mark.integration`) | PASS against `bean-check` from `beancount 3.2.3`. Seeded approved set compiled; `main.beancount` written; `bean-check` exit 0. |
| 7 | Unbalanced, invalid account, invalid sign, cross-currency fail compile | `test_contract_7_bad_inputs_fail` (4 parametrize cases, drives `compile_approved`) | PASS. Invalid-account input is `Expenses:invalid-lower` (passes the SQLite `GLOB`, fails PascalCase). Brief's `'not a valid account'` would raise at `_seed` INSERT, never reaching the compiler. |
| 8 | NULL `contra` refused before journaling | `test_contract_8_refuse_null_contra` | PASS |
| 9 | Index populated; recompile replaces, does not append | `test_contract_9_index_populated_and_replaced` | PASS (`ledger_entries=1`, `ledger_postings=2` after two compiles) |
| 10 | Replay: byte-identical files, no duplicate index rows | `test_contract_10_replay_byte_identical` | PASS |
| 11 | Every recovery decision-table row + re-entrant recover | `test_contract_11_recovery_table_rows_covered` plus the six named tests it requires | PASS as strengthened (M3): each named test exists and has `assert`. Named tests: `test_recover_pre_write_abort_marks_failed`, `test_recover_staging_hash_mismatch_refuses`, `test_recovery_is_reentrant_after_mid_recovery_crash`, `test_recover_rerun_after_full_recovery_is_safe_noop`, `test_crash_mid_replace_recovers_cleanly`, `test_crash_during_recovery_then_second_recover_completes`. Spec also names "staging-complete finish", "unrecognized live-state escalation", and "`bean_checked`-or-later failed run" as distinct rows; those are not one-name-per-row in the contract file. Extra coverage: `test_crash_between_index_replace_and_status_flip_leaves_run_recoverable`. |
| 12 | `os.replace` crash between two target files; repeat recover is a no-op | `test_contract_12_crash_between_files_recovers`; `tests/test_compile_recovery_integration.py` | PASS |
| 13 | Second concurrent acquire → `CompileLockedError`, journals nothing | `test_contract_13_lock_denial`; stale-lock tests in `tests/test_compile_writer_staging.py` | PASS. Lock is process-atomic (`O_CREAT\|O_EXCL`). Intra-process nested acquire is what the contract test exercises. |
| 14 | Safe mode blocks `compile` and `compile recover` | `test_contract_14_safe_mode_denial` (real `require_operator`, no `safe-mode.json` → default ON) | PASS for `action="compile"`. `compile recover` is the same `_PREFIX` mechanism with `subject="compile recover"`; not a second contract test. |
| 15 | Exact phrase; mismatch denies | `test_contract_15_phrase_mismatch`; `tests/test_cli_auth_phase3.py`; CLI exit 3 in `test_cli_compile_auth_failure_exits_code_3` | PASS. Contract item checks `require_operator` for `compile` with `confirm="wrong phrase"`. Audit `result="denied"` is asserted in the auth-module tests, not in this contract function. |
| 16 | Success / failure / recovery / denial audit events carry `compile_run_id` | `test_contract_16_audit_events_carry_run_id` | PASS for successful compile (`result="ok"`) and refused recovery (`result="error"`). Denial-path `compile_run_id` is not asserted here (a denied compile never starts a run). |
| 17 | Missing `bean-check` → `BeanCheckUnavailableError` before any `compile_runs` row | `test_contract_17_missing_beancheck_raises` | PASS (`shutil.which` patched to `None`) |

CLI wiring beyond the 17 items: `tests/test_cli_compile.py` covers success (exit 0), auth failure (exit 3), bad input (exit 1), `compile status` read-only, `compile recover` with nothing dangling, and `compile recover` of a started run.

## 6. Known limitations (not hidden)

These are the honest leftovers. None are unreviewed surprises; they were either accepted in the Phase 3 final review, closed later, or left as operator calls.

1. **Contract items 1, 3, 5 are thinner than their titles.** See the mapping table. The named contract file was transcribed from the plan's illustrative tests; M3 tightened items 7 and 11 only.
2. **`compile status` on a never-migrated DB.** After M1 dropped the implicit `migrate()`, a status check against a brand-new file raises `sqlite3.OperationalError` instead of auto-creating schema. Acceptable for a read-only inspector. Optional follow-up: guard the SELECTs and print "nothing compiled yet".
3. **`failed-<run_id>/` quarantine dirs are never auto-deleted.** Deliberate: they hold `bean-check.txt` for forensics.
4. **No live bank-file compile, no production ledger, no Git publication of `ledger/`.** Same focused-suite posture as Phases 1, 2a, and 2b.
5. **Item 11 is "named tests exist and contain asserts", not a full restatement of spec §11.** The recovery suite itself is the behavioral evidence.
6. **No remote, Iron-Hammer author.** Reconcile identity before the repo ever gains a remote. Do not push.
7. **Default user `PATH` does not include the Python user Scripts dir.** `bean-check` is installed; the evidence run had to prepend `%APPDATA%\Python\Python314\Scripts`. A later shell without that prefix will skip item 6 again. Optional follow-up: add that dir to the user PATH.

Closed in this evidence session: live `bean-check` (spec §14 item 6) against `beancount 3.2.3`. Renderer output is valid Beancount.

Closed in this phase (were open at the first final-review handoff, now on `main`): recover.py index-before-`recovered` status (`ca18f87`); `beancount_version` from `bean-check --version` (`11b4d15`); lock unlink-on-write-fail, refusal-audit commit, orphan `.staging` cleanup, `fail_compile_run WHERE status='started'`, `live_matches_prev` bool (`ac18f55`); M1-M6 (`4736b42`..`93269f6`).

## 7. Fixed authorization phrases (published)

Neither phrase is a secret. The gate's value is the audit event and the safe-mode precondition.

| Action | Phrase |
|---|---|
| `ironledger compile` | `authorize compile` |
| `ironledger compile recover` | `authorize compile recover` |

`compile status` is read-only: no phrase, no lock, no `migrate()`. Without a TTY, pass the exact phrase with `--confirm`. Safe mode (`config/safe-mode.json` absent or `"enabled": true`) denies both mutators with exit code 3.

Exit codes: `0` success, `1` compile/validation error, `3` authorization or safe-mode denial.

## 8. Deferred, unchanged (Phase 4+)

- Analytics and search projection, FTS5, projection hash manifest, atomic projection activate (Phase 4).
- Read-only MCP (Phase 5).
- SimpleFIN, RAG/NotebookLM export, private mobile, encrypted backup (Phases 6-8).
- Incremental compile; editing a single approved transaction; Git add/commit/push of `ledger/`.
- Live bank files, production evidence.

## 9. Operator verdict

Approved — 2026-09-08, transcript: this session; user's literal words "commit and approve the phase 3 gate" after the live `bean-check` 3.2.3 run (item 6 PASS; suite 343 passed / 1 skipped). Implementation range `4d77e5a..93269f6`. This evidence document and the `beancount==3.2.3` `dev` extra pin sit on top of that range.

Phase 4 (analytics and search projection) is cleared to start: spec, then plan, then operator approval of that plan, then code. No Phase 4 code is authorized by this verdict.
