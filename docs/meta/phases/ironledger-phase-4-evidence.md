# IronLedger Phase 4 evidence and exit verification

Status: Phase 4 exit gate recorded in this session on 2026-09-09 after the operator asked to commit the golden-path argv fix and write this evidence file. Phase 5 may start as spec, then plan, then operator approval of that plan. No Phase 5 code is authorized by this verdict.
Scope: rebuild a disposable SQLite analytics projection from the compiled Beancount ledger, then `search` and `balances` against that live projection. Focused-suite evidence plus a live README-argv subprocess. MCP, network listeners, SimpleFIN, RAG, mobile, backups, and Git publication of `ledger/` stay out of scope.

## 1. Provenance of this evidence

Phase 4 was implemented against `docs/meta/specs/ironledger-phase-4-projection-design.md` (`922290a`) and `docs/meta/plans/ironledger-phase-4-plan.md` (`f87e7d6`). SDD ran on `ironledger/phase-4-impl` in `.worktrees/ironledger-phase-4-impl`, then fast-forwarded onto local `main` (`31d818d` → `be72f08`). The impl worktree and feature branch were removed. The SDD workspace `.superpowers/sdd/ironledger-phase-4-plan/` was deleted after a clean whole-branch review. Git history is the record.

A later `/devex-review` (golden-path TTHW) found that the published argv `project --db …` did not parse: `--db` lived only on the parent parser, so the db path was taken as `project_command`. Tests had hidden it by putting `--db` before `project`. That parse fix is `6032cb0` on this `HEAD`.

Every number in section 4 comes from a test run executed against `HEAD` `6032cb0` on 2026-09-09 in this session. It is not copied from an implementer report.

`[tool.ironledger] phase = 4` in `pyproject.toml`. D-0 still holds: no remote, do not push.

## 2. Repository and environment state

| Item | Value |
|---|---|
| Repository path | `C:\dev\IronLedger` (operator-approved home, D-0) |
| Git branch | `main` |
| HEAD | `6032cb0` (`fix(cli): accept --db after project subcommand`) |
| Phase 4 range | 22 commits, `922290a..6032cb0` (spec `922290a`; plan `f87e7d6`; impl `1f60fae`..`be72f08`; argv fix `6032cb0`) |
| Upstream remote | None configured. Do not push. |
| Toolchain | Python 3.14.6, pytest 9.1.1, SQLite 3.50.4 (stdlib `sqlite3`) |
| Working tree | Clean except untracked `.context/`, `.ijfw/`, `ijfw/` (IJFW session scratch, not this phase) |
| Commit author | `Iron-Hammer <iron-hammer@ironledger.local>` (repo-local config) |
| `beancount` Python dep | None on the runtime path. `src/ironledger` does not `import beancount`. |
| `bean-check` on this evidence run | Not on default `PATH`. Item 12 therefore matches the Phase 3 no-bean-check baseline (skips), not the 343/1 PATH-prepended run. |

### 2.1 What shipped

`src/ironledger/project/` (`errors`, `parse`, `schema.sql`, `migrate`, `builder`, `activate`, `query`). Projection SQLite is a separate file from the operational `--db`. Schema version 1. CLI:

- `ironledger project --ledger-dir <dir> --db <db>` (mutator; phrase `authorize project`; `--db` accepted before or after `project`)
- `ironledger project status --ledger-dir <dir>` (read-only)
- `ironledger search --ledger-dir <dir> <query>` (no `--db`, no phrase)
- `ironledger balances --ledger-dir <dir>` (no `--db`, no phrase)

Default projection dest is `<ledger-dir>/../projection`. Rebuild takes the compile lock then the project lock. Stale `search` / `balances` fail closed (exit 1) with hashes and a copy-paste `project` line.

### 2.2 Commit groups (`922290a..HEAD`)

| Group | Tip / range | What |
|---|---|---|
| Spec + plan | `922290a` `30e8f0a` `f87e7d6` | projection design, DX/eng fold-in, TDD plan |
| Parse + errors | `1f60fae` `93484cc` `4a6e932` | formula errors, dialect round-trip, closed-dialect refusals |
| Schema + rebuild | `41c69a3` `4cbcd01` `536e666` `5b9b2a9` `a0e2fa0` `82f40d8` | schema v1, shared lock, staging sqlite/FTS, one-currency-per-account, activate under both locks |
| Crash + stale | `aa5b53d` `d3a34f8` `c47931c` | crash-before/between replace, search/balances, stale fail-closed |
| CLI + auth | `106b29a` `dab5b0b` `d7771c2` | phrase + safe mode, `project`/`search`/`balances`, README golden path |
| Exit contract | `be72f08` | spec §11 items 1–21 (item 12 is `pytest -q`) |
| Golden-path parse | `6032cb0` | `--db` after `project`; subprocess README argv |

## 3. Dependency posture

Unchanged from Phase 3 (`docs/meta/ironledger-dependency-posture.md`):

- Runtime core still has one third-party import: `ofxtools==1.1.1` (OFX parse only).
- `beancount` is not a Python dependency. Phase 4 parses the plaintext the compiler already wrote. It does not import Beancount and does not shell out to `bean-check`.
- Contract item 11: no `import beancount` under `src/ironledger`.

## 4. Focused acceptance run (2026-09-09)

From `C:\dev\IronLedger`:

```powershell
$env:PYTHONPATH='src'; python -m pytest -q
```

```text
418 passed, 2 skipped in 7.79s
```

Phase 3 no-bean-check baseline on this host was 342 passed / 2 skipped. Phase 4 only added tests. The two skips are pre-existing (bean-check integration off default PATH; Windows symlink-escape). This gate does not fail Phase 4 for those skips.

Named contract file: `tests/test_phase4_exit_contract.py` (`test_contract_1` … `test_contract_21` except 12). Extra golden-path tests in `tests/test_cli_project.py`: `test_project_accepts_db_after_subcommand`, `test_readme_golden_path_subprocess`.

## 5. Spec §11 test-contract mapping

Each of the 21 numbered items in the Phase 4 design spec §11 maps below. Item 12 has no named function; the module docstring says so.

| # | Spec requirement | Covering test(s) | This-host result |
|---|---|---|---|
| 1 | Render → parse round trip preserves accounts, opens, currencies, dates, payee, narration, postings, metadata | `test_contract_1_render_parse_round_trip` | PASS |
| 2 | Unknown directive / extra metadata / missing metadata / non-inverting amount → `ProjectParseError`; live projection unchanged; `path:line` + snippet | `test_contract_2_parse_refusals_leave_live_untouched` | PASS |
| 3 | `proj_balances` equals `SUM(proj_postings)` per `(account, currency)` | `test_contract_3_balances_equal_sum` | PASS |
| 4 | Second currency on one account refused; balances never net two currencies | `test_contract_4_second_currency_refused` | PASS |
| 5 | Delete projection and rebuild: same counts, same FTS posting_id set, same payload digest excluding `built_at_utc` | `test_contract_5_delete_and_rebuild_identical_payload` | PASS |
| 6 | FTS payee/narration/account/posting_text match; narration change + rebuild changes hits | `test_contract_6_fts_columns_and_rebuild_changes_hits` | PASS |
| 7 | Crash before sqlite `os.replace`: previous live projection remains (or absent) | `test_contract_7_crash_before_sqlite_replace` | PASS |
| 8 | Sqlite replace then crash before manifest: status mismatch; search/balances exit 1 | `test_contract_8_crash_between_replaces_fail_closed` | PASS |
| 9 | Safe mode / wrong phrase deny `project` (exit 3). search/balances/status skip `require_operator` | `test_contract_9_auth_surface` | PASS |
| 10 | New compile without `project` → search/balances exit 1; error names short hashes, `--ledger-dir`, `authorize project` | `test_contract_10_stale_after_new_compile` | PASS |
| 11 | No `import beancount` under `src/ironledger` | `test_contract_11_no_import_beancount` | PASS |
| 12 | Full suite does not drop below Phase 3 baseline; Phase 4 only adds | `python -m pytest -q` | PASS: 418/2 vs Phase 3 342/2 on this host without bean-check on PATH |
| 13 | `search` and `balances` parse and run with no `--db` | `test_contract_13_search_balances_without_db` | PASS |
| 14 | `--help` lists project/search/balances; epilog is the README golden path | `test_contract_14_help_and_epilog` | PASS (epilog now uses `ironledger.db`, not `<db>`) |
| 15 | CLI smoke of README argv; `--help` lists the three commands | `test_contract_15_readme_argv_smoke`; `test_readme_golden_path_subprocess` | PASS. Subprocess uses the published order `project --db ironledger.db …` |
| 16 | `main.beancount` include set disagrees with `txns/*.beancount` glob → `ProjectParseError`; live unchanged | `test_contract_16_include_glob_mismatch` | PASS |
| 17 | Duplicate `staged-transaction-id` → `ProjectParseError` | `test_contract_17_duplicate_stx_id` | PASS |
| 18 | Held `.compile.lock` makes `project` refuse; live unchanged | `test_contract_18_held_compile_lock` | PASS |
| 19 | Manifest `schema_version` equals `projection_meta.schema_version` | `test_contract_19_manifest_schema_version` | PASS |
| 20 | Two `search` runs after one rebuild return identical rows | `test_contract_20_search_order_stable` | PASS |
| 21 | Empty query and invalid FTS query exit 1 with the error formula, not a traceback | `test_contract_21_empty_and_invalid_fts` | PASS |

## 6. Known limitations (not hidden)

1. **This checkout has no compiled operator ledger.** `ledger/` is still the Phase 1 README-only tree. Live README commands from `C:\dev\IronLedger` hit safe mode (no `config/safe-mode.json`) and an empty ledger hash (`e3b0c442…`). A throwaway demo under `%TEMP%\ironledger-demo` produced Coffee / `1234 USD` after seeding a sample compile. That demo is not in git.
2. **TTHW from a cold tree is not 2–5 minutes.** `/devex-review` measured the published three-command path as DNF until `6032cb0`, then sub-second *after* compile + safe-mode off. First-run is still import → review → compile. Plan DX scores (Getting Started 9/10, TTHW 2–5 min) were not met for a clone with no data.
3. **Safe mode defaults ON.** Missing `config/safe-mode.json` denies `project` with exit 3. README now names that file. The file is not in the tree (deliberate).
4. **Stale Fix still prints `--db <db>` when `search` is invoked without `--db`.** The copy-paste is the published `project --db` order, which now parses; the placeholder is not a real path.
5. **No live bank-file projection, no production ledger, no Git publication of `ledger/` or `projection/`.** Same focused-suite posture as Phases 1–3.
6. **No remote, Iron-Hammer author.** Reconcile identity before the repo ever gains a remote. Do not push.
7. **Parked from the Phase 4 final review (not reopened here):** parser whitespace/comment/Unicode, `--projection-dir` path-safety, leftover staging cleanup, numbered perf gate, `wal_checkpoint` inspect, `importlib.resources` for `schema.sql`, argparse dest split so `project --ledger-dir DIR status` does not clobber.

## 7. Fixed authorization phrases (published)

Neither phrase is a secret. The gate's value is the audit event and the safe-mode precondition.

| Action | Phrase |
|---|---|
| `ironledger project` | `authorize project` |
| `ironledger compile` | `authorize compile` (Phase 3, unchanged) |
| `ironledger compile recover` | `authorize compile recover` (Phase 3, unchanged) |

`search`, `balances`, and `project status` are read-only: no phrase, no project lock on the query path. Without a TTY, pass the exact phrase with `--confirm`. Safe mode (`config/safe-mode.json` absent or `"enabled": true`) denies `project` with exit code 3.

Exit codes: `0` success, `1` project/parse/stale/query error, `2` argv, `3` authorization or safe-mode denial.

## 8. Deferred, unchanged (Phase 5+)

- Read-only MCP / network listener (Phase 5). New spec. Not a continuation of this plan.
- SimpleFIN, RAG/NotebookLM export, private mobile, encrypted backup (Phases 6-8).
- Incremental compile; editing a single approved transaction; Git add/commit/push of `ledger/`.
- Hosted docs, LICENSE, CONTRIBUTING, public GitHub (D-0; community score 2/10 accepted).
- In-CLI TTHW telemetry.

## 9. Operator verdict

Requested — 2026-09-09, transcript: this session; user's literal words "do it" after the offer "local commit of that fix, the Phase 4 evidence file, or leave it." Implementation range `922290a..be72f08` plus argv fix `6032cb0`. Focused suite 418 passed / 2 skipped. Spec §11 items 1–21 mapped above.

This document closes Phase 4 implementation on local `main`. It does not claim a 2–5 minute first-run from an empty checkout. Phase 5 (read-only MCP / network listener) is cleared to start only as: spec, then plan, then operator approval of that plan in the transcript, then code. No Phase 5 code is authorized by this verdict.
