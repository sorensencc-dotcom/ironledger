# Task 15 report

## Original implementation

Task 15 (dep-posture amendment + Section-14 17-item exit contract + regression sweep)
was implemented by a delegated agent (Antigravity) as commit `bddd738`, then the
controller applied two fixes as commit `213e9b6`:
- AG-F1: `docs/meta/ironledger-dependency-posture.md` rewritten by hand (the delegated
  agent's shell-heredoc build had mangled `beancount`/`bean-check` and stripped code spans).
- AG-F3: `integration` pytest marker registered in `pyproject.toml` `[tool.pytest.ini_options]`.

No structured implementer report was produced for the original work. Suite at `213e9b6`:
326 passed, 2 skipped (`test_ingest_inbox.py:63` symlinks-unavailable historical skip +
`test_phase3_exit_contract.py:99` item 6 bean-check-absent), 0 warnings.

## Task 15 review (sonnet, review-81b9788..213e9b6.diff)

Verdict: Needs fixes. All 17 Section-14 contract items present, named, sequential 1..17;
PF-1 auth adaptation correct on items 14/15; AG-F2 deviation (`test_contract_7` input
`'Expenses:invalid-lower'`) adjudicated as a legitimate correction of a defective brief
input (the brief's `'not a valid account'` fails the migration-0003 SQLite CHECK before
reaching the compiler). One Important finding blocks:

- **`docs/meta/ironledger-dependency-posture.md:17`** — "invoked with a strict execution
  timeout (default 30 seconds)". Actual default is `10.0` s (`src/ironledger/compile/beancheck.py:35`,
  `run_bean_check(..., timeout_seconds: float = 10.0, ...)`), and the caller
  `src/ironledger/compile/writer.py:173` does NOT override it. No code path uses 30 s.

## Fix round 1

**Before:** `- \`bean-check\` is invoked with a strict execution timeout (default 30 seconds) via \`subprocess.run\`.`

**After:** `- \`bean-check\` is invoked with a strict execution timeout (default 10 seconds) via \`subprocess.run\`.`

**Verification:**
- `src/ironledger/compile/beancheck.py:35` — function definition `def run_bean_check(..., timeout_seconds: float = 10.0, ...)`
- `src/ironledger/compile/writer.py:173` — call site `run_bean_check(staging_dir / "main.beancount", bean_check_bin=bean_check_bin)` does not override `timeout_seconds`

**Commit SHA:** (pending)

**Test coverage:** No covering test — docs-only prose change; verified against beancheck.py + writer.py source.
