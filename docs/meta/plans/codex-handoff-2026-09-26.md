# Codex handoff — 2026-09-26

Repo: `C:\dev\IronLedger`, branch `main`, HEAD `ffba34f` at handoff time.
Remote: `https://github.com/sorensencc-dotcom/ironledger` (private).
Run tests with `./.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=/tmp/il-check`
(always pass `--basetemp` to a fresh dir — a stale one leaves read-only
fixture files from `test_archive_windows_readonly` that can't be `rm`'d and
pytest's own tmp cleanup will throw spurious `PermissionError`s that look
like failures but aren't).

Two independent tasks below. Do them as separate commits/PRs — don't mix.

---

## Task 1 — single source of truth for the version string

**Why:** version is hardcoded in three places and already drifted once
(stuck at v0.11.0 while everything else moved forward). Cheap, mechanical,
low risk.

**Where it currently lives (find all three, there may be more — grep first):**
- `web/src/components/TopHUD.tsx`
- `src/ironledger/web/app.py`
- `scripts/build-docs.py`

**Do:**
1. `grep -rn "0\.1[0-9]\.0\|VERSION" web/src src/ironledger scripts` to find every
   literal version string and confirm there are exactly these three (or more).
2. Add one canonical source. Suggest a top-level `VERSION` file (plain text,
   one line, e.g. `0.15.0`) since this repo doesn't use `pyproject` version
   (locked at `0.0.0` per phase-15 handoff — do not touch that).
3. `src/ironledger/web/app.py` reads `VERSION` at startup and exposes it
   however it currently does (check how the HUD gets the version today —
   likely an API response field or injected into a template/JS global).
4. `web/src/components/TopHUD.tsx` reads it from that same API response
   instead of a literal string.
5. `scripts/build-docs.py` reads the `VERSION` file directly.
6. Grep again after the change to confirm zero remaining hardcoded version
   literals outside the `VERSION` file itself.

**Verify:** `docker compose up -d --build` (or `cd web && npm run build`
first if UI-only change), load the workbench, confirm the HUD version
matches `VERSION` file content. Run full test suite.

**Do not touch:** `pyproject.toml` version (stays `0.0.0`, locked per
phase-15 handoff — packaging is explicitly out of scope for this repo).

---

## Task 2 — surface Phase 14 tax/gains tools in the web workbench

**Why:** `get_capital_gains_summary`, `list_open_tax_lots`,
`get_unrealized_gains`, `preview_lot_disposal` (see
`src/ironledger/mcp/tools.py`, `TAX_TOOL_NAMES`) are real, tested (Phase 14,
`tests/test_mcp_tax_tools.py`, `tests/test_phase14_exit_contract.py`), and
only reachable via a raw MCP client. No web UI. Operator can't see capital
gains from the browser.

**Read first:**
- `src/ironledger/mcp/tools.py` — the 4 tax tool dispatchers, their exact
  input/output schemas. Reuse the underlying functions directly; do not go
  through the MCP JSON-RPC protocol layer from a web router — call
  `src/ironledger/valuation/lots.py` and whatever the tools module calls
  directly, the same way `src/ironledger/web/routers/analytics.py` calls
  into `valuation/` today (read that file for the existing pattern — same
  layering).
- `docs/meta/contracts/ironledger-phase-14-exit-contract.md` — the locked
  invariants (zero float division, zero runtime `import beancount`, exact
  integer arithmetic). A new router must not violate these. If you add any
  arithmetic, it must be integer/`Decimal`-exact, matching the existing
  style in `src/ironledger/valuation/`.
- `src/ironledger/web/routers/analytics.py` and `web/src/components/` for
  the existing router + React component conventions (how a router gets
  `db`/`ledger_dir` via `Depends`, how a component fetches from `web/src/api.ts`
  and renders in `web/src/App.tsx`).

**Scope (do all of it, one feature):**
1. New router `src/ironledger/web/routers/tax.py`:
   - `GET /api/tax/capital-gains-summary` (query params: tax year, term,
     account, commodity filters — match `get_capital_gains_summary`'s
     existing parameter names from `mcp/tools.py` exactly)
   - `GET /api/tax/open-lots`
   - `GET /api/tax/unrealized-gains`
   - `POST /api/tax/preview-disposal` (body matches `preview_lot_disposal`'s
     params: strategy FIFO/LIFO/HIFO, candidate sale quantity/account/etc.)
   - Register the router in `src/ironledger/web/app.py` the same way the
     existing routers are registered.
2. Pydantic request/response schemas in `src/ironledger/web/schemas.py`
   mirroring the MCP tool schemas — do not invent new field names, match
   what `mcp/tools.py` already defines so the two surfaces stay consistent.
3. New React panel, `web/src/components/TaxPanel.tsx` (or similar, match
   existing naming — see `WatchlistPanel` for a recent example of a
   self-contained panel component), wired into `web/src/App.tsx`:
   - Open tax lots table (account, commodity, remaining units, cost basis,
     acquisition date).
   - Unrealized gains summary (per-position + aggregate).
   - Capital gains summary (filterable by tax year/term).
   - A disposal-preview form: pick account/commodity/quantity/strategy,
     shows simulated realized gain/loss without mutating anything (this
     must call the read-only preview endpoint only — never write).
4. `web/src/api.ts` — add the four fetch functions following the existing
   pattern in that file.

**Hard constraints (from the exit contract, do not relax):**
- Every one of these endpoints is read-only. None of them may write to
  `ironledger.db` or the beancount files. If you're tempted to add a mutation
  here, stop — that's out of scope for this task.
- No floating point in any new arithmetic path (reuse `valuation/lots.py`'s
  existing simulation function for disposal preview instead of
  reimplementing it).
- No new runtime `import beancount`.

**Tests (write these, TDD, red-green):**
- `tests/test_web_tax.py` — one test per endpoint: happy path, empty
  ledger, invalid filter params, and (for preview-disposal) confirm no
  database mutation occurs (assert row counts unchanged before/after).
- Follow the existing test style in `tests/test_web_compile.py` or
  `tests/test_web_rules.py` for the FastAPI `TestClient` setup pattern
  (fixtures, temp db, etc. — copy their conventions, don't invent new ones).

**Verify:** full test suite green, then `cd web && npm run build`, then
`docker compose up -d --build`, open the workbench, confirm the new panel
renders and the numbers match `ironledger cli` equivalents (there should be
CLI/MCP output you can diff against for a sanity check on real data — ask
the user for read access to a real ledger snapshot if you need one to
verify against, do not fabricate financial numbers to "demo" this).

---

## Out of scope for both tasks — do not touch

- `ledger-vault/` (nested private git repo, gitignored) or anything in
  `config/csv-profiles/` matching a real institution name (bilt-palladium,
  chase-freedom, amex-*) — these hold real personal financial data, kept
  out of this repo on purpose. If you see them, leave them alone.
- `src/ironledger/cli/compose_guard.py` and the mutating-command guard in
  `cli/__main__.py` (`_is_mutating_invocation`) — landed same session as
  this handoff, unrelated to either task, don't refactor it incidentally.
- Federation, failover, compliance-bundle, anomaly-detection subsystems —
  real code, real tests, but not exercised by actual operator usage yet.
  Not part of either task; don't "helpfully" wire them into the new UI.
- OCR, email/XLS/Zapier/NotebookLM ingest, packaging/versioning bump beyond
  Task 1's scope, identity-v2 rewrites — explicitly parked per
  `docs/meta/plans/ironledger-phase-15-handoff.md`.

## Commit convention

Match existing log style: `type(scope): summary`, e.g.
`feat(web): surface Phase 14 tax tools in workbench` /
`chore(version): single-source the version string`. No attribution
footer needed unless your own tooling requires one — this repo's commits
don't carry one from earlier Codex sessions.
