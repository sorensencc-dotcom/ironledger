# SDD ledger — plan: docs/meta/plans/ironledger-phase-3-plan.md

Repo: C:\dev\IronLedger, branch `main` (operator-approved Option A, no remote, D-0).
Spec: docs/meta/specs/ironledger-phase-3-compiler-design.md (per plan line 13 it is at
`C:\dev\docs\meta\specs\...` — the spec lives in the sibling `C:\dev` repo on branch
`ironledger/phase-3-spec`, commit 15be2bfc, unpushed; NOT reachable from this checkout).
Ledger note: spec not reachable from working tree → pre-flight rulings are provisional
against plan text + live schema, not the spec.
Baseline: 254 passed, 1 skipped (PYTHONPATH=src python -m pytest -q).

## Pre-flight conflict scan (2026-09-06)

Live schema checked: migrations 0001–0004. `compile_runs`, `ledger_entries`,
`ledger_postings`, `audit_events`, `compile_runs` all created in 0001 (columns frozen).
`staged_postings` (0003) has NO identity_* columns; `staged_transactions` (0001) does.
`connect()` forces `PRAGMA foreign_keys=ON` and verifies → T1/T2 FK tests valid.

### Cross-task / intra-task table

| Row | Producer → Consumer | Contract | Finding |
|---|---|---|---|
| T1→T2 | 0005 compile_journal table → constraint tests | 7 states incl `refused`; `seq>=1`; FK compile_runs | clean (CHECK covers all 7; 7 param + 4 = 11 pass) |
| T1→T7/8/9/10 | compile_journal + compile_runs | journal helpers, writer, recover | clean — plan never sets compile_runs.status='refused' (only journal.state); 0001 CHECK allows started/succeeded/failed/recovered |
| T3 self | model.py load_approved_set SELECT `sp.identity_algo_version/method/fingerprint` | those cols are on `staged_transactions`, not `staged_postings` | **PF-2** — must be `st.identity_*` (query already JOINs `staged_transactions st`). Keep ApprovedPosting identity_* fields (T9 writes them into ledger_postings NOT NULL). |
| T3→T4 | ApprovedSet/Transaction/Posting dataclasses | field names render.py uses | clean — all fields present |
| T3→T5 | dataclasses | hashing.py field access | clean |
| T3 Finding4 → T4 | `roles == ['contra','imported']` validated | render sorts imported-then-contra | clean, consistent |
| T4→T5/T9 | render_ledger dict keys `main.beancount`/`accounts.beancount`/`txns/YYYY.beancount` | hash order main,accounts,sorted(txns); replace order accounts,main,sorted(txns) | clean — hash order self-consistent between intended & actual |
| T6→T8/T9 | run_bean_check / BeanCheckResult / COMPILER_VERSION | writer imports run_bean_check; T8 patches `writer.run_bean_check` | clean |
| T7→T8/9/10 | start/append/finish/fail/get_active_started/get_latest_successful | writer & recover call sites | clean; next_journal_seq is GLOBAL monotonic (matches T1 "monotonic seq>=1"), not per-run |
| T8 self | step-3 code block shows ONLY acquire_compile_lock, but T8 tests import+call `compile_approved` (bean-check-fail path) | **PF-3** — T8 must implement compile_approved far enough for its 2 tests (lock+staging+quarantine failed-<run_id>/+bean-check.txt+fail_compile_run+audit result="error"+raise BeanCheckFailedError). T9 extends same fn with success path. Prose+tests govern. |
| T8/9/10 | `append_audit_event(..., now_utc=now)` | real signature kwarg is `ts_utc`, not `now_utc` | **PF-6** — every append_audit_event call in T8/T9/T10 must pass `ts_utc=now`. (compile-module journal `_now(now_utc)` unaffected.) |
| T9 self | `_atomic_write_file` used by compile_approved + imported by T10, but not in step-3 code block | **PF-4** — implement per A4.1 prose: sibling temp in dst.parent, os.replace(tmp,dst), _fsync_dir(dst.parent). Also export `_fsync_dir`, `_replace_ledger_index`, and `acquire_compile_lock` (from T8) for T10 import. |
| T9→T10 | `_atomic_write_file`,`_fsync_dir`,`_replace_ledger_index`,`acquire_compile_lock` | recover.py imports from writer | clean once PF-4 done |
| T10→T11 | compile_approved + recover_dangling_compile; T11 patches `os.replace` globally | _atomic_write_file uses os.replace → crash injection lands there; copy semantics keep .staging intact | clean, matches A4.1 design |
| T12 + T15 | plan CLI-auth API: `require_operator(action=,expected_phrase=,confirm_flag=)`, `IRONLEDGER_SAFE_MODE` env, `AuthorizationError` from cli.auth, audit row `("compile","denied")` | real `src/ironledger/cli/auth.py`: `require_operator(conn,*,action,subject,confirm,stdin_isatty,config_dir,prompt)`; file-based `safe-mode.json` (default ON); `AuthorizationError` from `ironledger.ingest.errors`; denied audit writes `action="<disp> (denied: <reason>)"` | **PF-1** — reconcile toward existing module (see ruling). T12 step-3 "add 2 constants" is insufficient for its own tests as written. |
| T13→T14 | render_compile_summary/status/recovery_report; `CompileStatus` in interface line | test uses plain dict for status | clean — `CompileStatus` vestigial, no dataclass needed |
| T14→T15 | `main()` CLI: `--db`, `compile` tree, `--ledger-dir`, `--confirm`; exit 0/1/3 | T14 step 3 prose-only | clean (wiring task); implementer maps CompileInputError/BeanCheckFailedError→1, AuthorizationError→3 |
| T15 | contract items 14/15 import COMPILE_PHRASE/COMPILE_RECOVER_PHRASE from cli.auth, call require_operator with plan API | same as PF-1 | **PF-1** — adapt item 14/15 bodies to real API, preserve intent |

## Rulings

- **Ruling PF-1 (Tasks 12–15 CLI auth):** The plan's `require_operator(action=, expected_phrase=, confirm_flag=)` + `IRONLEDGER_SAFE_MODE` env + `AuthorizationError` importable from `cli.auth` + audit row exactly `("compile","denied")` contradict the live `src/ironledger/cli/auth.py`. Reconcile toward the existing module: add `COMPILE_PHRASE = "authorize compile"` and `COMPILE_RECOVER_PHRASE = "authorize compile recover"` constants to `cli/auth.py`, and register `compile` / `compile recover` in the existing `_PREFIX` (+ `_DISPLAY`) so the real `require_operator(conn,*,action,subject,confirm,stdin_isatty,config_dir,prompt)` gates them unchanged — with `subject` fixed (e.g. the empty string or `"ledger"`) so `expected_phrase` yields the two fixed phrases. Task implementers adapt the plan's example test bodies to the real signature while preserving each test's intent: correct phrase → mechanism string returned; wrong phrase → `AuthorizationError` (from `ironledger.ingest.errors`) + a `result='denied'` audit row whose `action` starts `compile`; safe mode on (`safe-mode.json` enabled / absent) → denial; CLI exit code 3 on denial. Why: the existing gate is battle-tested and shared with every other mutator; forking a second auth API for compile would split the security surface. Cost if wrong: T12/T15 auth tests diverge from the plan's verbatim snippets and may need a follow-up reconciliation pass; zero production-code risk (existing gate behavior unchanged).
- **Ruling PF-2 (Task 3):** `load_approved_set` postings query must select `st.identity_algo_version, st.identity_method, st.identity_fingerprint` (not `sp.*`) — those columns live on `staged_transactions`, and the query already joins it as `st`. `ApprovedPosting.identity_*` fields stay (Task 9 `_replace_ledger_index` writes them into `ledger_postings`, NOT NULL). Why: live schema (migration 0003) has no identity columns on `staged_postings`. Cost if wrong: Task 3 RED fails "no such column: sp.identity_algo_version"; a careless fix could drop the fields and break Task 9's insert.
- **Ruling PF-3 (Task 8):** Task 8's step-3 code block (only `acquire_compile_lock`) is deliberately partial; Task 8's own two tests require a working `compile_approved` failure path. Implement `compile_approved` to satisfy both Task 8 tests (lock, staging write under `ledger_dir/.staging/<run_id>/`, on bean-check failure move to `.staging/failed-<run_id>/` + write `bean-check.txt` + `fail_compile_run` + `append_audit_event(result="error")` + raise `BeanCheckFailedError`). Task 9 extends the same function with the success/replace/index path. Why: task prose + tests are the requirement authority, not the illustrative code block. Cost if wrong: Task 8 tests fail to import/run; caught immediately by the task review.
- **Ruling PF-4 (Task 9):** Implement module-private `_atomic_write_file(dst, data)` in `writer.py` per the A4.1 prose (write sibling temp in `dst.parent`, `os.replace(tmp, dst)`, `_fsync_dir(dst.parent)`); it is referenced by `compile_approved` and imported by Task 10's `recover.py` along with `_fsync_dir`, `_replace_ledger_index`, and `acquire_compile_lock`. Why: only the illustrative code omits it; the fold note specifies it precisely. Cost if wrong: Task 10 import fails; caught by Task 10 review.
- **Ruling PF-6 (Tasks 8/9/10):** Every `append_audit_event(...)` call passes `ts_utc=now`, not `now_utc=now` — the real `ironledger.audit.append_audit_event` keyword is `ts_utc` (the Global Constraint's trailing `...` hid this). The compile package's own `journal._now(now_utc)` parameter is unaffected. Why: verified signature at `src/ironledger/audit.py:99`. Cost if wrong: `TypeError` at the first audit call in Task 8; trivial, caught immediately.

- **Ruling PF-8 (Task 3):** The posting dicts `model.py::validate_approved_set` passes to
  `ironledger.conventions.validate_same_currency_balance` must include `"scale": p.minor_unit_scale`.
  Verified at `src/ironledger/conventions.py:246` the helper requires keys `{account, currency,
  minor_units, scale}` and raises `ConventionError("posting is missing keys: ['scale']")` otherwise —
  which would fail EVERY set including the valid one (`test_load_valid_approved_set` expects no raise).
  The plan's Step-3 code block builds the dict with only `account/minor_units/currency`. Add `scale`.
  Cost if wrong: `test_compile_model.py::test_load_valid_approved_set` fails at `validate_approved_set`;
  caught at Task 3 Step 4.

## Task log

Task 9: review ✅ spec / quality Approved. 2 Important findings:
  (1) no test for the read-back-verify failure branch (hash mismatch → CompileError, status stays
      'started', staging preserved, lock released) — load-bearing: Task 10 recovery builds on the
      "status stays started on mismatch" contract. → FIX LOOP round 1.
  (2) cascade / replace-not-append unverified here — RESOLVED by controller: 0001 has
      `ledger_postings.ledger_entry_id ... ON DELETE CASCADE` + `connect()` forces
      `PRAGMA foreign_keys=ON`; Task 15 contract items 9 & 10 assert recompile-replaces-not-appends.
      Not a real gap.
  Minors deferred: `_atomic_write_file` doesn't fsync the temp fd before os.replace (PF-4 as written;
  power-loss hardening not asked by A4.1 — FLAG TO FINAL); stale `*.tmp-<8hex>` siblings left on a
  crash between write_bytes and os.replace — Task 10 recover.py must sweep them (CARRY INTO T10
  DISPATCH); dataclass import order cosmetic.
Task 9: fix round 1/5 (1 addressed, 0 open — read-back-verify failure branch untested;
  commits 5595a35..7210fd0). Test-only fix; writer.py unchanged.
Task 9: complete (commits dd3d613..7210fd0, review clean after 1 fix round).
  Implementer sonnet, reviewer sonnet, re-reviewer haiku. Full suite 289 pass / 1 skip.

=== SESSION HANDOFF (operator chose fresh session, 2026-09-06, ~3.1h run) ===

STATE: Tasks 1-9 complete + review-clean. HEAD 7210fd0 on `main`. 11 commits 24f30ad..7210fd0,
  NONE pushed (no remote, D-0). Tree clean (untracked `.context/` + `.ijfw/` are not this plan's).
  Full suite: 289 passed, 1 skipped.

RESUME (fresh session):
  1. Preflight: `pwsh -NoProfile -File C:\dev\scripts\verify-repo-context.ps1 -Path C:\dev\IronLedger`
     → must report branch `main`, PREFLIGHT_PASS.
  2. Baseline: `PYTHONPATH=src python -m pytest -q` → expect 289 passed / 1 skipped.
  3. Invoke `superpowers:subagent-driven-development` on
     `docs/meta/plans/ironledger-phase-3-plan.md`. It reads THIS ledger; first task with no
     `Task N: complete` line is Task 10. Do NOT re-run Tasks 1-9.
  4. Remaining: Task 10 (recover.py decision table + A4.1 re-entrancy), Task 11 (crash-injection
     integration), Task 12 (cli/auth compile phrases — see Ruling PF-1), Task 13 (cli/render),
     Task 14 (cli/__main__ compile subcommand tree), Task 15 (dep-posture doc + Section-14
     17-item exit contract + full regression sweep).
  5. After Task 15: operator reviews exit evidence, then `superpowers:finishing-a-development-branch`.

CARRY INTO TASK 10 DISPATCH:
  - Ruling PF-4: import `_atomic_write_file`, `_fsync_dir`, `_replace_ledger_index`,
    `acquire_compile_lock` from `ironledger.compile.writer` (all module-scope, verified present).
  - Ruling PF-6: every `append_audit_event(...)` in recover.py passes `ts_utc=now`, NOT `now_utc=`.
  - Task 9 deferred minor: recover.py should sweep stale `*.tmp-<8hex>` sibling temp files in
    `ledger_dir` and `ledger_dir/txns/` left by a crash between `_atomic_write_file`'s write and
    os.replace. The plan's recover.py already unlinks live `txns/*.beancount` not in the intended
    set — extend that sweep to `*.tmp-*`.
  - Ledger note: `get_active_started_run` / `get_latest_successful_run` now carry a `rowid DESC`
    tiebreaker (Ruling T7-R1) — recover.py relies on their determinism.

CARRY INTO TASK 12 DISPATCH:
  - Ruling PF-1 (full text below). The plan's Task-12 test snippet + Task-15 contract items 14/15
    assume a `require_operator(action=, expected_phrase=, confirm_flag=)` API + `IRONLEDGER_SAFE_MODE`
    env + `AuthorizationError` from `cli.auth` + audit row exactly `("compile","denied")`. NONE of
    that matches the live `src/ironledger/cli/auth.py`. Reconcile toward the existing module; adapt
    the plan's example test bodies to the real signature, preserving each test's INTENT.

DEFERRED MINORS FOR THE FINAL WHOLE-BRANCH REVIEW (triage which block merge):
  - T1: checksum-frozen test mutates tracked schema file in place then restores (xdist/hard-kill risk).
  - T1: B-T6 used literal `== 5` (no `migrations.MIGRATIONS` attr); migration 0006 will re-trigger
    the two-file manual bump.
  - T1/plan: `ts_utc` GLOB `'????-??-??T??:??:??*Z'` looser than `%Y-%m-%dT%H:%M:%SZ`.
  - T2: `test_migration_0005_constraints.py:1` docstring says "and trigger" but has none (triggers
    covered in T1's file). f-string INSERT in `_seed_run`.
  - T3: unused `from typing import Final` in compile/model.py.
  - T4: unused `import pytest` (test), unused `ApprovedPosting` import + unused `year` param (render.py).
  - T4: no multi-year / multi-currency / empty-set render test.
  - T5: FLAG — no >1 `txns/*` file test, so the sorted() multi-file ordering contract Tasks 9/10
    rely on is not test-locked. Add a >=2-year-file case + optional golden input-hash constant.
  - T5/plan: output hash concatenates blobs with no length prefix (missing vs empty file collide).
  - T6: no timeout-branch or `bean_check_bin`-override test; `-1` timeout sentinel undocumented;
    TimeoutExpired partial stdout/stderr discarded.
  - T7: `next_journal_seq` read-then-insert not atomic (documented as needing the exclusive lock).
  - T8: FLAG — `acquire_compile_lock` is intra-process fail-fast advisory only (check-then-create +
    unconditional `finally` unlink); not cross-process safe. OK for D-0 local tool.
  - T8: `bean-check.txt` can be written empty; prefix with exit-code line.
  - T9: FLAG — `_atomic_write_file` does not fsync the temp fd before os.replace (PF-4 as written);
    no true power-loss guarantee. Amend PF-4 if that's wanted.
  - T9: `dataclasses.dataclass` import placed after ironledger imports (cosmetic).

RULINGS MADE THIS SESSION (each: what / why / cost if wrong):
  - PF-1 — Tasks 12-15 CLI auth: reconcile the plan's auth API to the live `cli/auth.py` (add
    `COMPILE_PHRASE`/`COMPILE_RECOVER_PHRASE` constants; register `compile`/`compile recover` in the
    existing `_PREFIX`/`_DISPLAY`; keep the real `require_operator` signature; adapt the plan's test
    snippets to it preserving intent). Why: the existing gate is shared with every mutator; a second
    auth API splits the security surface. Cost if wrong: T12/T15 auth tests diverge from the plan's
    verbatim snippets, need a reconciliation follow-up; zero production risk (gate behavior unchanged).
  - PF-2 — Task 3: `load_approved_set` selects `st.identity_algo_version/method/fingerprint` (from
    the joined `staged_transactions`), not `sp.*`; `ApprovedPosting` keeps those fields. Why: migration
    0003 `staged_postings` has no identity columns. Cost if wrong: caught at T3 RED.  [APPLIED, clean.]
  - PF-3 — Task 8: the brief's Step-3 block is partial; implement `compile_approved` through the
    bean-check-failure path, success path = placeholder `raise` for Task 9. Why: task prose + tests
    govern, not the illustrative snippet. Cost if wrong: caught at T8 review. [APPLIED, clean.]
  - PF-4 — Task 9: `_atomic_write_file(dst,data)` = sibling temp in dst.parent + os.replace +
    _fsync_dir(parent), COPY semantics (staging survives to the explicit rmtree); export it +
    `_fsync_dir` + `_replace_ledger_index` at module scope for Task 10. Why: only the illustrative
    code omitted the body; A4.1 fold specifies it. Cost if wrong: caught at T10 import. [APPLIED, clean.]
  - PF-6 — Tasks 8/9/10: `append_audit_event(...)` takes `ts_utc=`, not `now_utc=` (verified
    audit.py:99). Why: the Global Constraint's trailing `...` hid the real kwarg. Cost if wrong:
    TypeError at first audit call. [APPLIED T8+T9, clean; T10 still to apply.]
  - PF-8 — Task 3: posting dicts passed to `validate_same_currency_balance` must include
    `"scale": p.minor_unit_scale` (helper requires keys {account,currency,minor_units,scale},
    conventions.py:246). Why: without it EVERY set including the valid one fails "missing keys:
    ['scale']". Cost if wrong: caught at T3 GREEN. [APPLIED, clean.]
  - T7-R1 — Task 7: added `, rowid DESC` tiebreaker to `get_active_started_run` and
    `get_latest_successful_run` (latter also re-keyed to `finished_at_utc DESC`), overriding the
    brief's `ORDER BY started_at_utc DESC LIMIT 1`. Why: second-resolution timestamps make "latest"
    non-deterministic when two runs share a start-second; Task 10 recovery needs a stable pick. Cost
    if wrong: none plausible — pure determinism hardening; regression test added. [APPLIED, clean.]
  - T9 finding-2 resolution — cascade / replace-not-append: NOT a gap. 0001 has
    `ledger_postings.ledger_entry_id ... ON DELETE CASCADE`; `connect()` forces `PRAGMA
    foreign_keys=ON`; Task 15 contract items 9 & 10 assert recompile-replaces-not-appends. Cost if
    wrong: a second compile could orphan/leak posting rows — Task 15 will catch it if the assumption
    is false.
  - PF-5 / PF-7 — folded (PF-5 into PF-1; PF-7 resolved clean: connect() enables + verifies FK ON).
=== END HANDOFF ===

Task 8: complete (commits f196d1d..dd3d613, review clean — ✅ spec, quality Approved).
  Implementer sonnet, reviewer sonnet. PF-3 (success path = single placeholder `raise` line for
  Task 9) + PF-6 (`ts_utc=now` on append_audit_event) applied and verified. Lock has no leak path;
  failure-path DB/FS ordering satisfies audit FK; staging inside ledger tree. Full suite 287 / 1 skip.
  ⚠️ resolved: render_ledger emits `main.beancount` (verified Task 4 review); prior-task signatures
  corroborated by green suite.
Task 8: minor (deferred, FLAG TO FINAL REVIEW): `acquire_compile_lock` cleanup is unconditional
  (`finally: if exists(): unlink()`) and the acquire is check-then-create, so it is an intra-process
  fail-fast advisory lock, NOT cross-process-safe. Fine for D-0 single-operator local tool; if
  cross-process ever matters, switch to `os.open(..., O_CREAT|O_EXCL|O_WRONLY)`.
Task 8: minor (deferred): `bean-check.txt` written after shutil.move; empty if both stderr+stdout
  empty. Prefix with `f"bean-check exit code {exit_code}\n"` for a diagnosable empty-transcript case.
Task 8: minor (n/a): hardcoded `actor="operator"` — matches the plan Global Constraint verbatim.

Task 7: complete (commits 44100cc..f196d1d, review clean after 1 fix round).
  Implementer haiku, reviewer sonnet, re-reviewer haiku. Full suite 285 pass / 1 skip.
Task 7: fix round 1/5 (1 addressed, 0 open — non-deterministic ORDER BY in
  get_active_started_run + get_latest_successful_run; commits 26b50fd..f196d1d).
  - **Ruling T7-R1:** added `, rowid DESC` tiebreaker to both lookup helpers (get_latest_successful_run
    also switched primary key to `finished_at_utc DESC`), overriding the brief's verbatim
    `ORDER BY started_at_utc DESC LIMIT 1`. Reason: second-resolution timestamps make "latest" pick
    non-deterministic when two runs share a start-second; Task 10 recovery depends on a stable pick.
    Cost if wrong: none plausible — pure determinism hardening, no behavior change; new regression
    test `test_deterministic_lookup_with_same_timestamp_tiebreaker` locks it.
Task 7: minor (deferred): next_journal_seq read-then-insert is not atomic (TOCTOU); now documented
  as requiring Task 8's exclusive compile lock via module docstring. Consider
  `INSERT ... SELECT COALESCE(MAX(seq),0)+1` if the lock guarantee ever weakens.
Task 7: minor (deferred): task-7-report.md "Files Changed" line counts were the insertion totals,
  not file line counts. Cosmetic.

Task 6: complete (commits 51f72f3..44100cc, review clean — ✅ spec, quality Approved).
  Implementer haiku, reviewer sonnet. No `import beancount`; shutil.which/subprocess.run
  module-qualified for patch; check=False + timeout enforced; TimeoutExpired → BeanCheckResult.
  Cross-task contract (COMPILER_VERSION, BeanCheckResult fields, run_bean_check sig) exact.
  Full suite 282 pass / 1 skip.
Task 6: minor (deferred): no test for the timeout branch or `bean_check_bin` override (brief
  scoped 3 tests). Task 15 exit-contract item 17 covers the unavailable path; timeout still
  untested — add `patch("subprocess.run", side_effect=TimeoutExpired(...))` asserting ok=False,
  exit_code=-1 in a follow-up.
Task 6: minor (deferred): TimeoutExpired `.stdout`/`.stderr` partial output discarded; `-1`
  timeout sentinel undocumented. Add a comment/constant so downstream doesn't read it as a real
  bean-check exit status.

Task 5: complete (commits b52512f..51f72f3, review clean — ✅ spec, quality Approved).
  Implementer haiku, reviewer sonnet. 3 fn signatures match cross-task contract; intended vs
  actual output-hash use identical order (main, accounts, sorted txns/*) with symmetric b""
  missing-file handling; json.dumps determinism kwargs intact. Full suite 279 pass / 1 skip.
Task 5: minor (deferred): unused `import pytest` in test_compile_hashing.py (verbatim from brief).
Task 5: minor (deferred, FLAG TO FINAL REVIEW): no test exercises >1 `txns/*` file, so the
  sorted() multi-file ordering contract that Task 9 `writer.py` and Task 10 `recover.py` rely on
  is not test-locked. Add a ≥2-year-file case with a deliberately unsorted `year_files` arg, and
  optionally pin a golden input-hash hex constant for payload-completeness regression.
Task 5: minor (upstream): output hash concatenates file blobs with no length prefix/delimiter —
  missing vs empty file indistinguishable; spec-mandated scheme, not an impl defect. Awareness only.

Task 4: complete (commits 4f40919..b52512f, review clean — ✅ spec, quality Approved).
  Implementer haiku, reviewer sonnet. render.py verified I/O-free + deterministic; format_amount
  edge cases (neg, scale 0, sub-unit) correct; escape order (backslash before quote) correct.
  Full suite 277 pass / 1 skip.
Task 4: minor (deferred): unused `import pytest` in test_compile_render.py:5 and unused
  `ApprovedPosting` import + unused `year` param in render.py — all verbatim from brief, no lint gate.
Task 4: minor (deferred): no multi-year / multi-currency / empty-set render test (brief specified
  only 3). Cheap to add; determinism-critical module — candidate for a follow-up coverage task.
Task 4: minor (upstream): accounts.beancount `open` line uses last-write-wins currency per account;
  if an account ever carries two currencies the line is arbitrary (still deterministic). Belongs to
  the validator layer, not the renderer.

Task 3: complete (commits 77c13d0..4f40919, review clean — ✅ spec, quality Approved).
  Implementer sonnet, reviewer sonnet. PF-2 + PF-8 applied correctly (reviewer confirmed query
  text + `scale` key + ApprovedPosting.identity_* retained). Full suite 274 pass / 1 skip.
  Two ⚠️ resolved by controller: suite delta 274/1 (impl report + Task-15 sweep re-verifies);
  conventions required-keys set `{account,currency,minor_units,scale}` verified directly at
  conventions.py:246.
Task 3: minor (deferred): `from typing import Final` in compile/model.py is unused (verbatim
  from brief; no lint gate in repo). Delete when next touching the file.

Task 1: complete (commits 24f30ad..dc9b343, review clean — ✅ spec, quality Approved).
  Implementer haiku, reviewer sonnet. Full suite 258 pass / 1 skip.
Task 1: minor (deferred): checksum-frozen test in test_migration_0005.py:~186 mutates the
  tracked schema/0005 file in place then restores in `finally` — transient-dirty risk under
  a hard kill or pytest-xdist. Copy-all-schema-into-tmpdir + migrate(conn, directory=tmpdir)
  would be safer. Normal path is clean.
Task 1: minor (deferred): test_migration_0005.py asserts no seq>=1 / ts_utc-format negative
  cases — but Task 2 (test_migration_0005_constraints.py) adds test_seq_less_than_one_rejected
  and test_timestamp_format_glob_enforced, so this is covered downstream. Confirm at Task 2.
Task 1: minor (upstream/plan): ts_utc GLOB '????-??-??T??:??:??*Z' is looser than
  %Y-%m-%dT%H:%M:%SZ (`?` = any char; `*Z` admits trailing junk before Z). Verbatim from the
  brief and consistent with 0001's other timestamp CHECKs — plan-level choice, not an impl bug.
Task 2: complete (commits dc9b343..77c13d0, review clean — ✅ spec, quality Approved).
  Implementer haiku, reviewer sonnet. Full suite 269 pass / 1 skip.
Task 2: minor (deferred): test_migration_0005_constraints.py:1 docstring says "and trigger"
  but has no trigger tests — the append-only UPDATE/DELETE triggers ARE covered in Task 1's
  test_migration_0005.py::test_compile_journal_triggers_prevent_update_and_delete. Reviewer's
  "triggers uncovered" is inaccurate; only the docstring wording is stale. Trivial.
Task 2: minor (deferred): _seed_run builds INSERT via f-string (test-controlled constants,
  verbatim from brief) — parametrized `VALUES (?,?...)` would be cleaner if reused.
Task 1: minor (deferred): B-T6 used literal `== 5`; `migrations.MIGRATIONS` does not exist
  (module exposes `discover_migrations()`), so literal is pragmatic. Migration 0006 will
  re-trigger the same two-file manual bump — note for whoever writes 0006.

Task 10: dispatched (implementer sonnet, BASE 7210fd0). Report DONE_WITH_CONCERNS,
  commit 27f70ae. Full suite 295 pass / 1 skip (+6 tests: brief's 5 + stale-temp sweep).
Task 10: Ruling T10-R1 — accept the implementer's decision-table REORDER (Row 3 staging
  mismatch + Row 1 pre-write abort evaluated BEFORE the A4.1 re-render/input_hash refusal),
  deviating from the brief's Step-3 code which put a global input_hash gate first. Why:
  the brief's own Step-1 test `test_recover_pre_write_abort_marks_failed` seeds a started
  run with no approved set, so the brief's code ordering would raise AmbiguousRecoveryError
  instead of marking `failed`; the brief prose (lines 203-227) treats re-render identity as
  the basis for the deterministic-recovery path (Row 2), not a global gate; tests + Section
  11 prose govern over the illustrative code block (same principle as PF-3). Cost if wrong:
  a crashed run whose approved set legitimately changed AND whose live tree is non-empty
  could resolve differently than Section 11 row 1 intends — but implementer concern #1 shows
  the code still *refuses* (conservative, escalates to operator) in that ambiguous case, so
  the risk is bounded and in the safe direction. Task 11 crash-injection integration stresses
  the real paths.
Task 10: implementer concerns for FINAL REVIEW triage —
  (1) invalid approved set + non-empty live tree holding previous output falls through to
      refuse rather than Row-1 marked_failed (no re-render baseline → "nothing written"
      unprovable; conservative). Untested.
  (2) `live_matches_prev` compares over the CURRENT intended key set vs previous run's
      actual_output_hash — can misfire if the txns/YYYY year set changed between runs.
      Carried verbatim from brief. Task 11 stresses the stable-year-set path.

Task 10: review ✅ spec compliant / quality Approved (reviewer sonnet). No Critical, no
  Important. Re-entrancy verified by crash-window trace; all 4 decision rows reachable and
  guarded; every consumed signature matches; lock has no leak path; ts_utc=/now_utc= split
  correct; stale-temp sweep correct with real on-disk test.
Task 10: minors (deferred to FINAL REVIEW triage):
  - recover.py:138 `except CompileError` broader than the `CompileInputError` actually raised
    by validate_approved_set (model.py:117) — a future CompileLockedError/BeanCheckUnavailableError
    would be silently reclassified "approved set invalid". Narrow the except.
  - recover.py:152 `live_matches_prev` uses bare dict `rendered` in boolean position (yields
    `{}` not False when empty) while sibling line 151 uses `bool(rendered)`. Harmless; unify.
  - recover.py concern #1: invalid approved set + non-empty live tree holding previous output
    → conservative refuse instead of Row-1 marked_failed (no re-render baseline). No data loss.
    Confirm Section 11 Row 1 does not mandate `failed` here (spec lives in C:\dev repo, not
    reachable from this checkout — carry to final review / operator).
  - Row 4 (genuine corruption) has no dedicated test — reachable by construction; Task 11
    crash-injection integration is the coverage vehicle.
  - recover.py:121/122 `staging_dir.exists()` evaluated twice. Cosmetic.
Task 10: complete (commits 7210fd0..27f70ae, review clean).
  Implementer sonnet, reviewer sonnet. Full suite 295 pass / 1 skip. Ruling T10-R1 applied
  (decision-table reorder). One concern deferred to final review (Section 11 Row 1 wording,
  spec not reachable from checkout).

Task 11: complete (commit 27f70ae..f7b0fb0, review clean — ✅ spec, quality Approved).
  Implementer sonnet, reviewer sonnet. Test-only, brief code verbatim, zero production change.
  Reviewer traced the `os.replace` call-count assumption (crash #2 = main.beancount, accounts
  already live) against writer.py:209-219 and the A4.1 re-entrancy path through recover.py —
  both verify correct. recover_dangling_compile invoked outside every patch() block (real swaps).
  Full suite 297 pass / 1 skip.
Task 11: minors (deferred, all brief-authored):
  - test:94 asserts `.exists()` only on the 3 live files, comment says "valid" — add hash check.
  - test:86 first test uses wall-clock now_utc; second pins it. No timestamp asserted, not flaky.
  - test:41 `_seed()` re-inlined instead of reusing _seed_approved/_seed_valid helpers.

Task 12: complete (commits f7b0fb0..153cdc7, review clean — ✅ spec, quality Approved).
  Implementer sonnet, reviewer sonnet. Ruling PF-1 applied: 4 minimal production changes to
  cli/auth.py (COMPILE_PHRASE/COMPILE_RECOVER_PHRASE constants, 2 `_PREFIX` keys → "authorize",
  no _DISPLAY entry, __all__ extended); `require_operator` body/signature untouched. All 4
  brief tests adapted to the real `require_operator(conn,*,action,subject,confirm,stdin_isatty,
  config_dir,prompt)` API + file-based `safe-mode.json` (not the fictional IRONLEDGER_SAFE_MODE
  env). Test 3 audit assertion adapted per PF-1 to `action.startswith("compile")` +
  `result=="denied"` (real action string carries the deny reason). Reviewer verified the
  unchanged `expected_phrase`/`safe_mode_enabled`/`require_operator` bodies produce every
  asserted behavior with the new keys. Full suite 301 pass / 1 skip.
  ⚠️ resolved: audit_events.seq column exists (used by pre-existing auth tests; green suite).
Task 12: minor (deferred): test_compile_denied_with_wrong_phrase could also assert the error
  message text / exactly-one-audit-row. PF-1 only mandates startswith + result=="denied". Polish.
Task 12: CARRY INTO TASK 14 — downstream CLI wiring must call `require_operator` with
  `subject="compile"` / `subject="compile recover"` (matching the multi-word `_PREFIX` keys)
  for the phrases to line up with COMPILE_PHRASE / COMPILE_RECOVER_PHRASE.

Task 13: pre-dispatch rulings (brief Step-1 tests contradict brief Step-3 illustrative code;
  tests govern, same principle as PF-3):
  - **Ruling T13-R1:** `test_render_compile_summary` asserts `"42 entries" in out`; the Step-3
    code emits `"Entries compiled: 42"`. `render_compile_summary` must include the substring
    `"<entry_count> entries"` (e.g. `f"  Entries compiled: {summary.entry_count} entries"`).
    Why: the test is the requirement authority. Cost if wrong: trivial wording; caught at GREEN.
  - **Ruling T13-R2:** `test_render_recovery_report` asserts `"Recovered compile run crun-123"
    in out`; the Step-3 code emits `"Recovery [recovered]: crun-123 - ..."`. `render_recovery_report`
    must special-case `rec.action == "recovered"` to emit a line containing
    `f"Recovered compile run {rec.compile_run_id}"` (detail may follow). Keep the `action=="none"`
    branch verbatim ("No dangling compile run to recover."); a general form covers other actions.
    Why: test authority. Cost if wrong: caught at GREEN.
  - `CompileStatus` in the interface line is vestigial — the test passes a plain dict; signature
    stays `render_compile_status(status_data: dict, *, as_json: bool = False)`. Do NOT import a
    nonexistent `CompileStatus`. CompileSummary/RecoveryDecision field names verified: match the
    brief's constructors.

Task 13: complete (commits 153cdc7..6044227, review clean — ✅ spec, quality Approved).
  Implementer sonnet, reviewer sonnet. Rulings T13-R1 ("42 entries" substring) + T13-R2
  ("Recovered compile run <id>" special-case, "none" branch verbatim) applied at the asserted
  substring level. `CompileStatus` not imported (vestigial); render_compile_status takes plain
  dict, JSON branch deterministic (sort_keys=True). No production change outside cli/render.py.
  Reviewer verified no circular import (compile.writer/recover import neither cli.*). __all__
  keeps all 5 prior exports + 3 new. Full suite 304 pass / 1 skip.
Task 13: minor (deferred): render_recovery_report "recovered" branch uses ": <detail>" while
  the general fallthrough uses " - <detail>" — cosmetic separator inconsistency.
Task 13: minor (deferred, brief-sanctioned): human-readable render_compile_status branch untested.
Task 13: note — commits in C:\dev\IronLedger are authored `Iron-Hammer <iron-hammer@ironledger.local>`
  (repo-local git config, pre-existing since Task 1). Not this plan's concern; operator may
  want to reconcile author before any push.

=== SESSION HANDOFF (session-length checkpoint, 2026-09-06, ~3.2h run) ===

STATE: Tasks 1-13 complete + review-clean. HEAD 6044227 on `main`. 16 commits
  24f30ad..6044227 (plan commit 24f30ad first), NONE pushed (no remote, D-0).
  Tree clean (untracked `.context/` + `.ijfw/` are not this plan's).
  Full suite: 304 passed, 1 skipped. Baseline for Task 14 = 304/1.

DONE THIS SESSION: Task 10 (27f70ae, recover.py + Ruling T10-R1 decision-table reorder),
  Task 11 (f7b0fb0, crash-injection integration tests), Task 12 (153cdc7, cli/auth compile
  phrases per Ruling PF-1), Task 13 (6044227, cli/render renderers + Rulings T13-R1/T13-R2).
  All implementer sonnet / reviewer sonnet, each review-clean (Task 10 had 0 fix rounds —
  DONE_WITH_CONCERNS resolved by ruling + deferred minors; Tasks 11-13 clean first pass).

RESUME (fresh session):
  1. `pwsh -NoProfile -File C:\dev\scripts\verify-repo-context.ps1 -Path C:\dev\IronLedger`
     → branch `main`, PREFLIGHT_PASS.
  2. Baseline: `PYTHONPATH=src timeout 120 python -m pytest -q` → expect 304 passed / 1 skipped.
  3. Invoke `superpowers:subagent-driven-development` on
     `docs/meta/plans/ironledger-phase-3-plan.md` (cwd C:\dev\IronLedger). It reads THIS
     ledger; first task with no `Task N: complete` line is Task 14. Do NOT re-run Tasks 1-13.
     task-14-brief.md is already extracted in the workspace.
  4. Remaining: Task 14 (cli/__main__ `compile` subcommand tree — wiring), Task 15
     (dep-posture doc + Section-14 17-item exit contract + full regression sweep).
  5. After Task 15: run the FINAL whole-branch review — `review-package
     docs/meta/plans/ironledger-phase-3-plan.md 4d77e5a HEAD` (MERGE_BASE 4d77e5a = parent of
     plan commit 24f30ad; branch is D-0 on main), dispatch requesting-code-review's
     code-reviewer.md on the MOST CAPABLE model, point it at every `minor (deferred)` /
     `Ruling:` / parked line in this ledger. Then ONE fix wave if needed, one scoped re-review.
  6. Then operator reviews exit evidence, then `superpowers:finishing-a-development-branch`.

CARRY INTO TASK 14 DISPATCH:
  - Ruling PF-1 (Task 12): the CLI `compile` / `compile recover` handlers MUST call
    `require_operator(conn, *, action=..., subject=..., confirm=..., stdin_isatty=...,
    config_dir=..., prompt=...)` with `action="compile"` + `subject="compile"` for compile,
    and `action="compile recover"` + `subject="compile recover"` for recover (multi-word
    `_PREFIX` keys — subject must equal the key so `expected_phrase` reproduces
    `COMPILE_PHRASE` / `COMPILE_RECOVER_PHRASE`). Import the two phrase constants from
    `ironledger.cli.auth`.
  - Exit codes (Global Constraint): 0 success, 1 CompileInputError / BeanCheckFailedError /
    CompileError, 3 AuthorizationError (from `ironledger.ingest.errors`) / safe-mode denial.
  - Task 13 renderers: `render_compile_summary(CompileSummary)`, `render_recovery_report(
    RecoveryDecision)`, `render_compile_status(dict, *, as_json=False)` — all in
    `ironledger.cli.render`. `--json` flag on `compile status` routes to `as_json=True`.
  - Entry points: `compile_approved(conn, ledger_dir, *, now_utc=None, bean_check_bin=None)
    -> CompileSummary` and `recover_dangling_compile(conn, ledger_dir, *, now_utc=None)
    -> RecoveryDecision` from `ironledger.compile.writer` / `.recover`.
  - Ledger cross-task table row T14→T15 + T13→T14: brief Step-3 for Task 14 is prose-only
    ("wiring task"); implementer maps error classes → exit codes. `CompileStatus` in the
    interface line is vestigial.

CARRY INTO TASK 15 DISPATCH:
  - Section-14 exit contract has 17 items (per eng-review fold T3.1 "all-17 exit tests").
    Items 14/15 import COMPILE_PHRASE / COMPILE_RECOVER_PHRASE from cli.auth and exercise the
    real `require_operator` API (Ruling PF-1) — adapt the plan's snippets to the real signature
    as Task 12 did.
  - Task 15 also runs the full regression sweep — final count should be 304/1 + Task 14 tests
    + Task 15 contract tests.

OPEN ITEMS FOR THE FINAL REVIEW (full list is in the per-task `minor (deferred)` /
  `parked` / `Ruling:` lines above — this is the pointer, not a substitute):
  - Rulings this session: T10-R1 (recover.py decision-table reorder), T13-R1, T13-R2. PF-1
    carried from prior session, applied in Task 12.
  - Task 10 concern #1: invalid approved set + non-empty live tree holding previous output →
    conservative refuse instead of Row-1 marked_failed. Confirm against spec Section 11 Row 1
    wording (spec lives on branch `ironledger/phase-3-spec` in the sibling `C:\dev` repo,
    commit 15be2bfc — NOT reachable from the IronLedger checkout).
  - Task 10 Row 4 (genuine corruption) has no dedicated unit test (reachable by construction).
  - Commit author in C:\dev\IronLedger is `Iron-Hammer <iron-hammer@ironledger.local>`
    (repo-local config, all 16 commits) — operator may want to reset author before any push.
  - All prior-session deferred minors (T1-T9) still pending final-review triage.
=== END HANDOFF ===

=== ANTIGRAVITY DELEGATION PACKET (Tasks 14 + 15 implementation only) ===

PURPOSE: hand the two remaining implementation tasks to Antigravity as a batch to skip the
one-controller-per-task dispatch loop. Antigravity IMPLEMENTS and COMMITS; it does NOT review,
merge, push, or close the plan. A Claude session runs both task reviews + the final
whole-branch review afterward.

--- HARD BOUNDARY (Antigravity has a prior incident on this repo: faked approval + force-push,
    see memory session-wrap-2026-09-01-ironledger-antigravity-recovery). Non-negotiable: ---
  1. Work ONLY in C:\dev\IronLedger on branch main. Do NOT create a branch. Do NOT add a
     git remote. Do NOT git push anything. Do NOT git rebase / reset --hard / force-anything.
  2. Do exactly Task 14 then Task 15. Nothing else. No "while I am here" edits, no touching
     Tasks 1-13 code, no refactors outside the two files each task names.
  3. One commit per task, exact messages given below. Stop after Task 15's commit + suite run.
  4. Do NOT run any code review. Do NOT write "approved" / "review clean" / "LGTM" anywhere.
     Do NOT edit this ledger except to append a plain factual line:
     "Task N: implemented, commit <sha>, suite <n> pass / <m> skip".
     Do NOT invoke finishing-a-development-branch, superpowers:*, /ship, /land-and-deploy, or
     any merge / PR tool.
  5. If a test cannot be made to pass without changing production code outside the task's named
     files, or a brief instruction contradicts the live code in a way not covered below: STOP,
     write what you found to a plain note, hand back. Do not guess past it.
  6. Report back: the two commit SHAs, the final "PYTHONPATH=src python -m pytest -q" count,
     and any STOP note. That is all.

--- PRECONDITIONS ---
  - pwsh -NoProfile -File C:\dev\scripts\verify-repo-context.ps1 -Path C:\dev\IronLedger
    must print branch main, PREFLIGHT_PASS.
  - git rev-parse HEAD must be 6044227 (Task 13). git status --porcelain shows only untracked
    .context/ and .ijfw/ - leave both alone.
  - Baseline: PYTHONPATH=src python -m pytest -q  ->  304 passed, 1 skipped.
  - Always wrap the test binary with a 120s timeout (GNU "timeout 120 ..." in Git Bash).
    Never run pytest unbounded.
  - Briefs (already extracted, use verbatim as requirements):
      C:\dev\IronLedger\.superpowers\sdd\ironledger-phase-3-plan\task-14-brief.md
      C:\dev\IronLedger\.superpowers\sdd\ironledger-phase-3-plan\task-15-brief.md

--- TASK 14: wire cli/__main__.py compile subcommand tree ---
  Files: modify src/ironledger/cli/__main__.py, create tests/test_cli_compile.py.
  TDD: write the brief's 3 tests verbatim (RED) -> wire (GREEN) -> commit.
  Brief Step 3 is prose ("add subcommands ... with proper authorization, error handling, exit
  codes"). MATCH THE EXISTING wiring style in cli/__main__.py for gated mutators: look at how
  the "import" and "review approve" / "review reject" commands parse --confirm, resolve
  config_dir, call cli.auth.require_operator, and map exceptions to exit codes. Do not invent a
  new auth pattern.
  Auth call MUST be (per Ruling PF-1, Task 12):
    - compile         -> require_operator(conn, action="compile", subject="compile",
                           confirm=<--confirm value>, stdin_isatty=..., config_dir=..., ...)
    - compile recover -> require_operator(conn, action="compile recover",
                           subject="compile recover", confirm=..., ...)
    Import COMPILE_PHRASE / COMPILE_RECOVER_PHRASE from ironledger.cli.auth only if a default
    --confirm or help text needs them; the phrase check itself happens inside require_operator.
  Exit codes (Global Constraint): 0 success; 1 for CompileInputError / BeanCheckFailedError /
    CompileError; 3 for AuthorizationError (from ironledger.ingest.errors) / safe-mode denial.
  "compile status" is READ-ONLY: no auth, no lock, no mutation. Gather latest run
    (journal.get_latest_successful_run), active started run (journal.get_active_started_run),
    on-disk hash; build a plain dict; call
    ironledger.cli.render.render_compile_status(data, as_json=<--json flag>). The test asserts
    "Compile Status:" in out and rc 0 with an empty DB + missing ledger dir, so the gatherers
    must tolerate "nothing there yet".
  Entry points:
    ironledger.compile.writer.compile_approved(conn, ledger_dir, *, now_utc=None,
       bean_check_bin=None) -> CompileSummary
    ironledger.compile.recover.recover_dangling_compile(conn, ledger_dir, *, now_utc=None)
       -> RecoveryDecision
    Renderers: render_compile_summary(CompileSummary), render_recovery_report(RecoveryDecision)
       from ironledger.cli.render.
  --ledger-dir is a required option on compile and compile recover; the test always passes it
    on compile status too.
  Full suite before commit -> expect 307 passed, 1 skipped (304 + 3).
  Commit: git add src/ironledger/cli/__main__.py tests/test_cli_compile.py
          git commit -m "feat(cli): wire compile, compile status, and compile recover commands"

--- TASK 15: dep-posture doc + Section-14 17-item exit contract + regression sweep ---
  Files: modify docs/meta/ironledger-dependency-posture.md, create
    tests/test_phase3_exit_contract.py.
  Step 1: the brief gives the full 17-item suite. Transcribe it; add the _seed helper + header
    imports it names. THREE items use the fictional Task-12 auth API and MUST be adapted to the
    real one exactly as Task 12's tests/test_cli_auth_phase3.py did (read that file for the
    pattern):
      * item 14 test_contract_14_safe_mode_denial: drop
        monkeypatch.setenv("IRONLEDGER_SAFE_MODE","1") (no such env var). Instead pass
        config_dir=<tmp_path subdir with NO safe-mode.json> (safe mode is ON by default when the
        file is absent). Call require_operator(db, action="compile", subject="compile",
        confirm=COMPILE_PHRASE, stdin_isatty=False, config_dir=<that dir>); expect
        AuthorizationError.
      * item 15 test_contract_15_phrase_mismatch: config_dir=<tmp dir with safe-mode.json
        {"enabled": false}>, confirm="wrong", same real signature -> expect AuthorizationError.
      * any other contract item importing expected_phrase= / confirm_flag= kwargs gets the same
        subject= / confirm= / config_dir adaptation. Preserve each test's INTENT; never weaken
        an assertion beyond that mechanical swap.
    Item 13 (acquire_compile_lock re-entrancy -> CompileLockedError) and all non-auth items use
    real APIs already - transcribe as-is. Item 6 is @pytest.mark.integration and skips when
    bean-check is not on PATH - keep that.
  Step 2: add the Phase 3 amendment section to docs/meta/ironledger-dependency-posture.md
    (beancount invoked only via pinned bean-check subprocess; no "import beancount" in runtime
    core; binary-on-PATH assumption + BeanCheckUnavailableError fallback; lockfile update note).
    Prose doc - normal English, follow the existing file's section style.
  Step 3: PYTHONPATH=src timeout 120 python -m pytest -q across the whole repo. Expect all pass,
    1 skipped (2 skipped if bean-check is absent - item 6 skips). Rough target after Task 14
    (307/1) plus the ~15-16 collected contract tests = ~322-323 passed. Exact number goes in the
    report; a DROP below 307 or any FAIL is a STOP.
  Commit: git add docs/meta/ironledger-dependency-posture.md tests/test_phase3_exit_contract.py
          git commit -m "docs(ironledger): update dependency posture and add Phase 3 exit gate test contract"

--- AFTER ANTIGRAVITY HANDS BACK (Claude session, not Antigravity) ---
  1. Task 14 review: review-package 6044227..<t14 sha>, dispatch task-reviewer-prompt.md
     (sonnet). Fix loop if needed.
  2. Task 15 review: review-package <t14 sha>..<t15 sha>, dispatch task-reviewer (sonnet) -
     focus: all 17 Section-14 items present and named, the 3 auth items correctly adapted (not
     weakened), dep-posture doc factually matches the code, regression count.
  3. Append "Task 14: complete" / "Task 15: complete" lines here once each review is clean.
  4. FINAL whole-branch review: review-package 4d77e5a HEAD (MERGE_BASE 4d77e5a = parent of
     plan commit 24f30ad), dispatch requesting-code-review/code-reviewer.md on the MOST CAPABLE
     model, point it at EVERY "minor (deferred)" / "Ruling:" / "parked" line in this ledger
     (T1-T15). One fix wave max, one scoped re-review, adjudicate residuals.
  5. Operator reviews exit evidence -> superpowers:finishing-a-development-branch.
=== END ANTIGRAVITY DELEGATION PACKET ===

=== ANTIGRAVITY DELEGATION — RETURN VERIFICATION (Claude, 2026-09-07) ===

Antigravity ran the packet. Procedurally IN BOUNDS: no push, no remote, no branch, no merge,
no review claim. 2 commits on `main`:
  Task 14  81b9788  feat(cli): wire compile, compile status, and compile recover commands
                    (src/ironledger/cli/__main__.py +127, tests/test_cli_compile.py +95)
  Task 15  bddd738  docs(ironledger): update dependency posture and add Phase 3 exit gate test contract
                    (docs/meta/ironledger-dependency-posture.md +31 NEW, tests/test_phase3_exit_contract.py +251)
Suite independently re-run by Claude: 326 passed, 2 skipped, 1 warning (matches AG's report).
`test_contract_6` + one other skip (bean-check absent). HEAD bddd738. Tree clean.

FINDINGS FROM THE RETURN (must clear before the Task 14/15 reviews are meaningful):

  AG-F1 (BLOCKER, doc corruption): `docs/meta/ironledger-dependency-posture.md` is text-mangled.
    Antigravity built it via `python -c "content='''...'''"` and `\b` sequences were interpreted
    as backspace: "beancount" -> "eancount", "bean-check" -> "ean-check" throughout, and EVERY
    backtick code span was stripped (`import beancount`, `src/ironledger/`,
    `ironledger.compile.render`, `subprocess.run`, `BeanCheckUnavailableError`, ... all now bare
    text). Factually wrong ("eancount"/"ean-check") and unshippable. Fix: rewrite the doc by hand
    (Write tool, not a shell heredoc) — 4 short sections, follow the content AG intended:
    zero-`import beancount` boundary, `bean-check` subprocess + PATH/`BeanCheckUnavailableError`
    fallback, byte-determinism, lockfile/amendment policy. ~5 min. Then `git commit --amend` or a
    follow-up `docs:` commit.

  AG-F2 (review it, do not assume malice): `test_contract_7` parametrize item 2 was changed from
    the brief. Brief: `account = 'not a valid account'` / match `[Ii]nvalid account`. Committed:
    `account = 'Expenses:invalid-lower'` / same match. AG likely swapped it because the real
    account-name validator rejects a lowercase segment but tolerates arbitrary strings — but this
    is an UNDOCUMENTED deviation from the brief. Task 15 review must confirm the new input
    actually exercises the "invalid account" rejection path (not some other CompileInputError),
    and that `[Ii]nvalid account` is the real message. If the validator would also reject
    `'not a valid account'`, restore the brief's value.

  AG-F3 (Minor, not pristine): `PytestUnknownMarkWarning: Unknown pytest.mark.integration` at
    test_phase3_exit_contract.py:96. The brief specified `@pytest.mark.integration` but the repo
    never registered the marker. Fix: add `[tool.pytest.ini_options] markers = ["integration: ..."]`
    to `pyproject.toml` (or `filterwarnings`), OR drop the mark and rely on the `shutil.which`
    skip alone. Suite output must be warning-free at the exit gate.

  AG-OK: `_seed` helper in the committed file is clean (the garbled base64 was an abandoned
    intermediate). All 20 contract tests collect. `__main__.py` wiring NOT yet reviewed.

NEXT (fresh session — do NOT let Antigravity near the reviews):
  1. Fix AG-F1 (rewrite doc) + AG-F3 (register marker). Commit.
  2. Task 14 review: review-package 6044227..81b9788, task-reviewer-prompt.md (sonnet). Focus:
     auth call uses `subject="compile"` / `subject="compile recover"` + real `require_operator`
     signature (PF-1); `config_dir` resolution matches how existing mutators resolve it;
     exit-code map 0/1/3; `compile status` is truly read-only (no lock, no auth); the 3 brief
     tests present with assertions intact.
  3. Task 15 review: review-package 81b9788..<doc+marker fix sha>, task-reviewer (sonnet). Focus:
     all 17 Section-14 items present + named (they are — verified by --collect-only); AG-F2
     adjudication; items 14/15 correctly use the real `require_operator(...config_dir...)` API
     (they do — verified: tmp cfg dir, no `IRONLEDGER_SAFE_MODE`); dep-posture doc factually
     matches code AFTER the F1 rewrite.
  4. Then FINAL whole-branch review: review-package 4d77e5a HEAD, code-reviewer.md on the MOST
     CAPABLE model, pointed at every `minor (deferred)` / `Ruling:` / `parked` line T1-T15 in
     this ledger. One fix wave, one scoped re-review.
  5. Operator exit-evidence review -> superpowers:finishing-a-development-branch.
=== END RETURN VERIFICATION ===

=== TASK 14 / 15 REVIEW SESSION (Claude, 2026-09-07) ===

Session-1 fix applied and committed: AG-F1 (dep-posture doc rewritten by hand, Write tool)
  + AG-F3 (`integration` marker registered in pyproject.toml) = commit 213e9b6. HEAD 213e9b6.
  AG-F2 adjudication: brief's `account='not a valid account'` fails the SQLite CHECK on INSERT
  (migration 0003 `staged_postings` account GLOB), so it would raise on _seed, not exercise the
  compiler's account-name convention checker. Substituted `'Expenses:invalid-lower'` (passes the
  SQLite root GLOB `Expenses:*`, violates PascalCase convention) — Task 15 review to confirm this
  hits the "[Ii]nvalid account" rejection path and not some other CompileInputError.

Task 14: review ✅ spec compliant / quality Approved (reviewer sonnet, review-6044227..81b9788.diff).
  No Critical, no Important. Auth call shape matches Ruling PF-1 exactly (verified: _PREFIX["compile"]
  = "authorize" + subject="compile" → expected_phrase reproduces COMPILE_PHRASE; same for
  "compile recover"). _cmd_compile / _cmd_compile_recover clone the existing _cmd_import gated-mutator
  block byte-for-byte (config_dir=args.config_dir, stdin_isatty=sys.stdin.isatty()). Exit map 0/1/3
  correct (all compile errors subclass CompileError → exit 1; AuthorizationError from
  ironledger.ingest.errors → exit 3). `compile status` verified genuinely read-only (no require_operator,
  no .compile.lock, no INSERT/UPDATE/commit). All 3 brief tests present, assertions intact, not
  over-mocked (only run_bean_check patched).
Task 14: ⚠️ RESOLVED by controller — `render_compile_status(as_json=True)` path untested; reviewer
  flagged risk that journal getters might return non-JSON-serializable rows. Verified journal.py:100
  get_active_started_run and journal.py:121 get_latest_successful_run both return plain
  `dict[str, str]` built from scalar columns — fully JSON-serializable. No real gap; untested-path
  is a deferred minor for final review.
Task 14: minors (deferred to FINAL REVIEW triage):
  - __main__.py:220-221 `_cmd_compile` catch tuple `(CompileInputError, BeanCheckFailedError,
    BeanCheckUnavailableError, CompileError)` is redundant — all subclass CompileError.
    `_cmd_compile_recover` already uses the clean `except CompileError`. Collapse for consistency.
  - __main__.py:212-214 missing `--ledger-dir` → hand-rolled `print(...); return 2` re-implements
    argparse's own message. Correct (a required parent --ledger-dir would break the subcommands'
    own --ledger-dir) but wants a one-line rationale comment to prevent a "just make it required"
    regression.
  - test_cli_compile.py:6 `import sqlite3` unused (carried from brief snippet; suite 0 warnings).
  - test_cli_compile.py:295 `test_cli_compile_status_read_only` name over-promises — asserts only
    rc==0 + output substring, not absence of writes/lock. Read-only holds by inspection; an
    assertion on unchanged audit_events count / DB mtime would earn the name. Brief assertions intact.
  - test fixture renamed brief's `db_path` → `env`, adds `config/safe-mode.json` + `--config-dir`
    threading. Necessary + correct under Ruling PF-1 (without the safe-mode file every test exits 3);
    no assertion weakened. Noted only because the brief gave literal test code.
Task 14: complete (commits 6044227..81b9788, review clean).
  Implementer Antigravity (delegated), reviewer sonnet, controller-resolved 1 ⚠️. Suite at HEAD
  213e9b6: 326 passed / 2 skipped / 0 warnings.

Task 15: review ❌ / Needs fixes (reviewer sonnet, review-81b9788..213e9b6.diff, spans AG commit
  bddd738 + controller fix commit 213e9b6). All 17 Section-14 contract items present, named,
  sequential 1..17 no gap. PF-1 auth adaptation on items 14/15 correct (matches
  tests/test_cli_auth_phase3.py pattern — file-based safe-mode.json, real require_operator
  signature, no fictional expected_phrase=/confirm_flag= kwargs). AG-F3 marker fix verified
  (pyproject.toml [tool.pytest.ini_options] markers, 0 warnings). Dep-posture amendment section
  present + not thin, AG-F1 rewrite materially correct (no \b-mangling, code spans intact).
  1 Important finding blocks:
  - docs/meta/ironledger-dependency-posture.md:17 states bean-check timeout "(default 30 seconds)";
    actual default is 10.0s (beancheck.py:35 run_bean_check timeout_seconds: float = 10.0), never
    overridden by the caller (writer.py:173 passes only bean_check_bin). → FIX LOOP round 1.
Task 15: AG-F2 adjudication CONFIRMED by reviewer — NOT a finding. test_contract_7 committed input
  'Expenses:invalid-lower' DOES reach the compiler's invalid-account path: migration 0003
  (0003_staged_postings.sql:23-27) accepts it (account GLOB 'Expenses:*' matches) so _seed INSERT
  succeeds; validate_approved_set → validate_account_name (model.py:132) fails the PascalCase
  segment regex (conventions.py:66,84) on segment 'invalid-lower' → ConventionError → re-raised
  CompileInputError("Invalid account 'Expenses:invalid-lower' ...") → re.search("[Ii]nvalid account")
  matches. Runs before validate_same_currency_balance so it is the account-name rejection, not
  balance/currency. Brief's 'not a valid account' would raise sqlite3.IntegrityError at the _seed
  CHECK before the pytest.raises block — erroring the test. AG's undocumented swap is a correct fix
  of a defective brief input.
Task 15: ⚠️ RESOLVED by controller — the 2 suite skips are test_ingest_inbox.py:63 (symlinks
  unavailable — pre-existing historical skip, predates Phase 3) + test_phase3_exit_contract.py:99
  (item 6, bean-check not installed). No newly silenced test.
Task 15: minors (deferred to FINAL REVIEW triage; items 1 & 5 are brief-authored / plan-mandated):
  - test_phase3_exit_contract.py:87-92 (item 5 "Stable hashes") asserts only len(h1)==64, never
    computes a 2nd hash for stability. Verbatim from brief.
  - test_phase3_exit_contract.py:55-62 (item 1 "byte-identical across permutations") renders the
    same ApprovedSet twice, not a permuted input ordering. Verbatim from brief; name oversells.
  - test_phase3_exit_contract.py:203-215 (item 14) omits the match="safe mode" assertion the
    sibling test_cli_auth_phase3.py:87 carries. Brief's item 14 had no match either (mechanical
    transcription, not a weakening) — tightening would pin the denial reason.
  - test_phase3_exit_contract.py:26,29 COMPILE_RECOVER_PHRASE + compute_intended_output_hash
    imported but unused (transcribed from brief header).
  - brief said "Modify" ironledger-dependency-posture.md but the file did not exist and was
    created (new file mode 100644); brief's "match existing section style" premise did not hold.
Task 15: fix round 1/5 (1 addressed, 0 open on the review finding — doc timeout 30s → 10s,
  commit a30abd9). BUT controller pre-re-review inspection of the fix diff found 2 defects the
  fix introduced / left:
  (a) a30abd9 tracked `.superpowers/sdd/ironledger-phase-3-plan/task-15-report.md` — that dir is
      git-ignored SDD scratch (.gitignore:21); must not enter branch history.
  (b) `docs/meta/ironledger-dependency-posture.md` is CRLF on every line (entered at AG commit
      bddd738); every sibling docs/meta/*.md is LF and Global Constraint mandates LF writes.
Task 15: fix round 2/5 (commit c1a42f8) — scratch report untracked (git ls-files .superpowers/
  now empty, file still on disk), doc normalized CRLF→LF (file reports "ASCII text", 0 CRLF
  lines). Tree clean (only .context/ + .ijfw/).
Task 15: fix round 1/5 + 2/5 re-review — ALL 3 findings ADDRESSED (reviewer haiku,
  review-213e9b6..c1a42f8.diff): (1) doc timeout 30→10s, content-only diff, sole substantive
  change; (2) scratch report untracked + on disk; (3) doc LF-only, no CR bytes, no visible text
  change. No new breakage — no .py / pyproject.toml touched by a30abd9 or c1a42f8.
Task 15: complete (commits 81b9788..c1a42f8, review clean after 2 fix rounds).
  Implementer Antigravity (delegated) for bddd738; controller-dispatched haiku for AG-F1/F3 fix
  213e9b6 and fix rounds a30abd9 + c1a42f8. Reviewer sonnet (main) + haiku (re-review). AG-F2
  adjudicated + reviewer-confirmed as a legitimate brief-input correction. Suite at HEAD c1a42f8:
  326 passed / 2 skipped / 0 warnings.

=== ALL 15 TASKS COMPLETE. HEAD c1a42f8, 21 commits 4d77e5a..HEAD, unpushed (D-0, no remote).
    NEXT: final whole-branch review (review-package 4d77e5a c1a42f8, code-reviewer.md, most
    capable model, pointed at every minor(deferred)/Ruling:/parked line T1-T15). ===

Final review: dispatched (reviewer opus, review-4d77e5a..c1a42f8.diff = 21 commits ~262KB,
  focus file final-review-focus.md listing all rulings + T1-T15 deferred minors).
Final review: COMPLETE (reviewer opus, 4-pass, independent suite re-run 326/2/0-warn).
  Verdict: Ready to merge = WITH FIXES. NO Critical. 5 Important, ~12 Minor.
  All rulings CONFIRMED (PF-1/2/3/6/8, T7-R1, T10-R1 independently traced safe, T13-R1/R2,
  AG-F2 confirmed). Strengths called out: A4.1 re-derive recovery, crash-injection at the
  real os.replace boundary, 0005 append-only triggers + FK-refuses-connection, hashing
  determinism comment, strict model validation.
  Fix-wave scope decided by controller — see final-review-fix-wave.md:
  IN THE WAVE (block merge, cheap + load-bearing):
    #1 acquire_compile_lock: hard crash strands .compile.lock, permanently blocks recovery
       (finally doesn't run on SIGKILL/power-loss — the exact crash model recover.py exists
       for). Fix: atomic os.open(O_CREAT|O_EXCL|O_WRONLY) + self-describing lock file +
       CompileLockedError message names the file + remedy. Folds in the T8 advisory-lock minor.
    #2 writer.py:231-232 + recover.py:202-211: finish_compile_run commits BEFORE
       _replace_ledger_index → crash between = run 'succeeded' while index holds prior run's
       rows, get_active_started_run returns None, recover says "nothing to recover", no path
       back. Fix: _replace_ledger_index BEFORE finish_compile_run (recovery Row 2 already does
       this order, idempotent).
    #3 compile_approved never prunes stale txns/*.beancount (recover.py:178-185 does) → orphan
       year file → compile status globs all-on-disk → false "Hash Matches: NO" on a
       correctly-compiled tree. Fix: lift the prune loop into compile_approved before the
       read-back hash.
    #5 recover.py:110/149/159/198: all 4 refusal paths journal state=refused + raise, NONE
       emits append_audit_event — but exit-contract item 16 title claims recovery emits an
       audit event (body only asserts success path). Fix: append_audit_event(action="compile
       recover", result="error", compile_run_id=run_id, ts_utc=now) before each raise + widen
       item 16.
    bundled cheap/branch-tied: pyproject.toml [tool.ironledger] phase 1→3 (+ comment still
       says compilation not authorized); add .gitattributes `*.sql text eol=lf` (migration
       runner checksums file text; autocrlf flip → ChecksumMismatch on the frozen migration).
  DEFER (follow-up tasks, surface to operator at finish):
    #4 beancount_version recorded "unknown" in every realistic deploy (importlib.metadata
       fails — beancount deliberately not a dep). Derive from resolved binary --version.
       Provenance quality, not correctness.
    + ~10 Minors: orphan .staging / failed-<run_id> cleanup, B-T6 literal not applied,
      compile status calls migrate() (not strictly read-only), item 7/11 test strength,
      no CLI exit-1 test + no compile-recover CLI test, fail_compile_run WHERE guard,
      live_matches_prev {} vs False, T1 checksum test tmp_path, lint cluster (one commit),
      Iron-Hammer commit author (operator decision).

=== HANDOFF (session-length checkpoint, 2026-09-07). ===
STATE: All 15 tasks complete + review-clean. Final whole-branch review COMPLETE, verdict
  "merge WITH FIXES", NO Critical. HEAD c1a42f8 on main, 21 commits 4d77e5a..c1a42f8,
  UNPUSHED (D-0, no remote). Tree clean (untracked .context/ + .ijfw/ not this plan's).
  Suite 326 passed / 2 skipped / 0 warnings.
RESUME (fresh session):
  1. Preflight: pwsh -NoProfile -File C:\dev\scripts\verify-repo-context.ps1 -Path C:\dev\IronLedger
     → branch main, PREFLIGHT_PASS.
  2. Baseline: PYTHONPATH=src timeout 120 python -m pytest -q → 326 passed / 2 skipped.
  3. Dispatch ONE final-review fix subagent (sonnet — multi-file crash-window judgment),
     FIX_BASE c1a42f8, items #1/#2/#3/#5 + the 2 bundled cheap fixes, from
     final-review-fix-wave.md. Covering tests: test_compile_recovery_integration.py,
     test_compile_writer*.py, test_compile_recover*.py, test_phase3_exit_contract.py, full suite.
  4. ONE scoped re-review: review-package docs/meta/plans/ironledger-phase-3-plan.md
     c1a42f8 <fix-head>, re-review-prompt.md (sonnet). Adjudicate residuals per the breaker
     (park with ruling, or rule on load-bearing ones). NO second fix wave.
  5. Append "Final review: fix wave complete" + the deferred-follow-up list to this ledger.
  6. Delete this workspace (rm -rf .superpowers/sdd/ironledger-phase-3-plan/) ONLY after the
     re-review is clean — git history is the record.
  7. superpowers:finishing-a-development-branch. Present to operator: the deferred #4 +
     ~10 Minors as known follow-ups; the branch is D-0 on main so "finishing" = the operator
     decides merge/keep-as-is. DO NOT PUSH (no remote; and see the Iron-Hammer author note).
RULINGS THIS SESSION (for the finish "Rulings I made" list):
  - AG-F2 adjudication: test_contract_7 input 'not a valid account' (brief) → 'Expenses:
    invalid-lower'. Why: brief value fails the migration-0003 SQLite CHECK on _seed INSERT,
    never reaches the compiler; the substitute passes the SQLite GLOB and is rejected by
    validate_account_name → CompileInputError matching [Ii]nvalid account. Cost if wrong:
    item 7 tests a different rejection than Section 14 intends — but sonnet review + opus
    review both independently confirmed the substitute hits the account-name path.
  - Task 14 ⚠️ (render_compile_status as_json untested): resolved not-a-gap — journal.py:100
    + :121 getters return plain dict[str,str] from scalar columns, JSON-serializable. Cost if
    wrong: a --json status call raises; low, and opus review concurred "serializable by
    construction".
  - Fix-wave scope: put Important #1/#2/#3/#5 + 2 bundled cheap fixes in the ONE wave; defer
    Important #4 + all Minors to follow-up tasks. Why: #1-3 are crash-recovery correctness
    (the phase's whole point) and cheap ordering/lock fixes; #5 closes a stated-contract vs
    code gap; #4 is provenance quality and needs a subprocess-version design choice better
    made deliberately. Cost if wrong: a deferred Minor turns out merge-blocking — operator
    sees the full list at finish and can pull one forward.
=== END HANDOFF ===

=== FINAL REVIEW FIX WAVE — COMPLETE (Claude, 2026-09-07) ===

Fix subagent (sonnet, FIX_BASE c1a42f8). 2 commits on `main`:
  e102aef  fix(ironledger): harden compile crash-window — atomic lock, index-before-finish,
           stale-txn prune, recovery-refusal audit events
  10972f2  chore(ironledger): bump [tool.ironledger] phase to 3 and pin *.sql to LF
Suite: 330 passed / 2 skipped / 0 warnings (326 baseline + 4 new tests). HEAD 10972f2.
23 commits 4d77e5a..HEAD, UNPUSHED (D-0, no remote).

Fixes applied (all CONFIRMED by scoped re-review, reviewer sonnet, review-c1a42f8..HEAD.diff):
  #1 acquire_compile_lock: os.open(O_CREAT|O_EXCL|O_WRONLY) atomic acquire; FileExistsError ->
     CompileLockedError naming the file + remedy; fd closed in own finally; normal-exit unlink
     cannot delete another process lock. Folds in the T8 advisory-lock minor. Tests:
     test_stale_lock_from_hard_crash_blocks_with_actionable_message,
     test_acquire_lock_writes_self_describing_content (test_compile_writer_staging.py).
  #2 compile_approved: _replace_ledger_index now BEFORE finish_compile_run (writer.py ~255-261);
     crash between leaves run 'started' (recoverable). Test:
     test_ledger_index_replaced_before_run_marked_succeeded (test_compile_writer_success.py).
  #3 compile_approved: prune loop for stale txns/*.beancount lifted from recover.py (writer.py
     ~235-243), after replace loop / before read-back hash; semantics match recover.py exactly.
     Test: test_compile_prunes_stale_year_files_when_approved_set_narrows.
  #5 recover.py: all 4 AmbiguousRecoveryError refusal sites (~111, 154, 168, 211) now emit
     append_audit_event(action="compile recover", result="error", compile_run_id=run_id,
     ts_utc=now) before the raise. audit_events.action has NO CHECK (0001), "compile recover"
     accepted. Exit-contract item 16 genuinely widened to assert the refusal path emits an
     audit row (not renamed).
  bundled: pyproject.toml [tool.ironledger] phase 1->3 + comment corrected; .gitattributes
     created with *.sql text eol=lf (LF-terminated).

RESIDUALS ADJUDICATED (breaker: NO second wave):

  R-FIN-1 (Important, DEFERRED to operator at branch-finish — NOT silently dropped):
    recover.py Row 2 finalize order. final-review-fix-wave.md:35 ("Same swap in
    recover.py:202-211") scoped a matching swap into Item 2; the fix agent applied Item 2 to
    compile_approved only and left recover.py finalize as UPDATE status='recovered' + commit
    FIRST (~218-224), THEN _replace_ledger_index (~227). Re-reviewer traced it: a crash in that
    window leaves the run `recovered` with a stale ledger_entries index; get_active_started_run
    filters status='started' so a `compile recover` re-run returns action="none" and never
    re-enters — the run is unreachable with a stale index (same class as the Item 2 hole).
    WHY DEFERRABLE (re-reviewer verdict b, not a merge blocker): (a) no shipped Phase 3 command
    reads the index — compile status compares file hashes only; projection/MCP are out of scope;
    the divergence is unobservable through any shipped surface. (b) the next full
    `ironledger compile` self-heals it (_replace_ledger_index opens with unconditional
    DELETE FROM ledger_entries + rebuild). (c) window is recovery-only (already the rare path)
    and sub-second. FIX (one line + test, for the follow-up): move _replace_ledger_index(...)
    above the UPDATE ... status='recovered' block in recover.py Row 2, keep the final
    conn.commit() ordering; add a crash-injection test for that specific window
    (test_crash_during_recovery_then_second_recover_completes only crashes mid-os.replace,
    before the status flip — this window is untested).

  R-FIN-2 (Minor, ledger note): if os.write fails (disk full) between os.open and the yield in
    acquire_compile_lock, a zero-byte lock file is stranded without its pid=/since= body and
    without outer-finally cleanup. Next run still gets the correct actionable CompileLockedError;
    only the diagnostic content is lost.

  R-FIN-3 (Minor, ledger note): the 4 refusal-path append_audit_event calls (and the
    pre-existing bean-check-failure path at writer.py:208) do not conn.commit() before the
    raise, while the preceding append_compile_journal("refused") does commit. Same connection =
    row visible, so the widened item-16 test passes; but a real process exit post-raise keeps
    the committed "refused" journal row and loses the uncommitted audit row — partial
    reintroduction of the asymmetry #5 closes. Not a regression from this wave (identical latent
    pattern already shipped + PF-confirmed on the bean-check path). Follow-up: add conn.commit()
    after the refusal-path + bean-check-path audit writes.

Re-reviewer overall: "Clean to merge, provided the recover.py residual is recorded as an
  Important deferred follow-up rather than silently dropped." Suite green 330/2 on independent
  re-run (x2).

=== DEFERRED FOLLOW-UPS FOR THE OPERATOR (surface at finishing-a-development-branch) ===
  Important:
    - R-FIN-1 (above) — recover.py Row 2 finalize order: index-replace before status='recovered'
      commit + a crash-injection test for that window. One-line swap; unobservable + self-healing
      today, so deferrable, but it completes Item 2 as the fix-wave doc scoped it.
    - #4 (from final review) — beancount_version recorded "unknown" in every realistic deploy
      (compile/beancheck.py:25-29): importlib.metadata.version("beancount") fails (beancount
      deliberately not a dep). Derive from subprocess.run([resolved_bin, "--version"]), keep
      metadata as fallback. Provenance quality, needs a deliberate design choice — own task.
  Minor (from final review + this wave; one lint/cleanup pass could absorb most):
    - R-FIN-2, R-FIN-3 (above).
    - orphan .staging/<run_id>/ left when run_bean_check raises BeanCheckUnavailableError before
      start_compile_run (writer.py:173-183) — nothing sweeps it.
    - failed-<run_id> quarantine dirs never cleaned (writer.py:186-190) — unbounded growth of
      full ledger copies; document retention intent or add a policy.
    - B-T6 fold not applied — tests/test_manifests.py + tests/test_migration_0004.py keep
      hard-coded 5; migration 0006 re-breaks both.
    - _cmd_compile_status calls migrations.migrate(conn) — can create the DB + apply schema, so
      the T14 "asserts absence of writes" minor is slightly false as written.
    - exit-contract item 7 asserts against validate_approved_set(load_approved_set(db)) not
      compile_approved (holds by construction); item 11 asserts six function names exist (passes
      even if all six were pass).
    - no CLI test asserts exit code 1 anywhere in the compile tree; `compile recover` has no
      CLI-level test (test_cli_compile.py covers 0 and 3 only).
    - fail_compile_run UPDATE has no WHERE status='started' guard (journal.py:91-95) — not
      currently reachable; guard is free.
    - live_matches_prev can be {} not False (recover.py:135) — boolean-context only; inconsistent
      with bool(...) on the adjacent line.
    - T1 checksum-frozen test mutates the tracked schema file in place + restores in finally —
      transient-dirty under -n / hard-kill. Rewrite to a tmp_path copy via
      discover_migrations(directory=...).
    - lint cluster (no lint gate in repo): unused `from typing import Final` (model.py); unused
      `import pytest` + unused ApprovedPosting + unused `year` param (render.py); unused
      `import pytest` (test_compile_hashing.py); unused COMPILE_RECOVER_PHRASE /
      compute_intended_output_hash (test_phase3_exit_contract.py:26,29); unused `import sqlite3`
      (test_cli_compile.py:6); redundant catch tuple (__main__.py:205, _cmd_compile:220-221).
  Note (operator decision, not code): all 23 commits authored
    Iron-Hammer <iron-hammer@ironledger.local> (repo-local git config since Task 1). Reconcile
    author before any push if the repo gains a remote. Irrelevant while D-0.

=== END FINAL REVIEW FIX WAVE ===
