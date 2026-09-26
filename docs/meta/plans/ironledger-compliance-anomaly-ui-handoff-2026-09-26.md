# Handoff — compliance + anomaly web UI (priority 1 of this doc)

Repo: `C:\dev\IronLedger`, branch `main`, HEAD `1458ba1` at handoff time.
Remote: `https://github.com/sorensencc-dotcom/ironledger` (private).
Run tests with `./.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=/tmp/il-check`
(always pass `--basetemp` to a fresh dir — a stale one leaves read-only
fixture files from `test_archive_windows_readonly` that can't be `rm`'d and
pytest's own tmp cleanup will throw spurious `PermissionError`s that look
like failures but aren't).

## Why this is next

Same shape of gap the tax-tools task (`1458ba1`, shipped 2026-09-26) just
closed: real, tested backend logic, CLI-only, zero web surface. Verified
by direct inspection before writing this doc — do not re-derive from
memory, re-check if stale:

- `src/ironledger/compliance/bundle.py` (`generate_compliance_bundle`,
  `verify_compliance_bundle`) — CLI only, via
  `src/ironledger/cli/commands/compliance.py`. No router. No web
  reference anywhere (`grep -rln "compliance" src/ironledger/web/` is
  empty).
- `src/ironledger/governance/anomaly.py` (`scan_and_persist_anomalies`,
  `resolve_anomaly_flag`, plus the four `detect_*` scanners) — CLI only,
  via `src/ironledger/cli/commands/anomaly.py`. Same: zero web reference.

**Correction to an earlier assumption:** federation and failover are
*not* part of this gap anymore. Both already have full routers
(`src/ironledger/web/routers/federation.py`,
`src/ironledger/web/routers/failover.py`) and full React panels
(`web/src/components/FederationView.tsx`,
`web/src/components/FailoverView.tsx`), wired into `Sidebar.tsx` /
`App.tsx` under `activeView === 'federation' | 'failover'`. Don't
re-build these. If you're tempted to "complete the set," the set is
already complete for those two — this handoff is compliance + anomaly
only.

## One task, two surfaces (compliance bundles, anomaly flags) — do together, one commit

They share nothing at the DB or route level, but both are "operator
audit tooling," small individually, and belong in one PR — don't split
into two commits unless the diff turns out large enough that review gets
hard.

**Read first:**
- `src/ironledger/compliance/bundle.py` — `generate_compliance_bundle(conn,
  ledger_id, framework, period_start_utc, period_end_utc, output_dir=None,
  bundle_id=None) -> ComplianceBundleResult` and
  `verify_compliance_bundle(archive_bytes, expected_merkle_root=None,
  expected_sha256=None) -> dict`. `VALID_FRAMEWORKS` constant for the enum.
  Bundle generation returns a sealed tar archive on disk plus a result
  object (`bundle_id`, `framework`, `ledger_id`, `record_count`,
  `merkle_root_hex`, `sealed_archive_sha256`) — read
  `ComplianceBundleResult`'s dataclass fields exactly, mirror them in the
  response schema.
- `src/ironledger/governance/anomaly.py` — `scan_and_persist_anomalies(conn,
  ledger_id, transactions, rules=VALID_RULE_TYPES) -> list[AnomalyFinding]`
  and `resolve_anomaly_flag(conn, ledger_id, flag_id, resolution_status,
  actor, reason="") -> bool`. `VALID_RESOLUTIONS`, `VALID_RULE_TYPES`
  constants. Scan needs `NormalizedTransaction` objects — see
  `src/ironledger/cli/commands/anomaly.py::run_anomaly_scan` for the exact
  SQL that loads staged transactions and builds them (join
  `staged_transactions`/`staged_postings` on `role = 'imported'`). Reuse
  that query, don't reinvent it.
- `src/ironledger/cli/commands/anomaly.py::run_anomaly_list` for the flags
  list query + status filter (`OPEN` / `RESOLVED` / exact status string).
- `src/ironledger/web/auth.py::require_operator` — the existing FastAPI
  dependency that checks `X-IronLedger-Op-Token` via `hmac.compare_digest`.
  Bundle generation and anomaly resolve are **mutations** (they write —
  bundle writes a file + reads DB, resolve writes `anomaly_flags` +
  appends a governance audit event). Gate both behind `require_operator`,
  the same way other mutating routers do (check `staging.py` or
  `rules.py` for the `Depends(require_operator)` pattern on a POST route).
  Scan (`scan_and_persist_anomalies`) also writes (`INSERT ... anomaly_flags`)
  — gate it too. List/verify are read-only, no token needed.
- `src/ironledger/web/routers/tax.py` and `web/src/components/TaxPanel.tsx`
  (shipped `1458ba1`) as the most recent example of the router +
  schema + panel + api.ts + App.tsx wiring pattern in this repo. Copy its
  shape, not federation/failover's (tax is newer and closer to today's
  conventions).
- `docs/meta/contracts/ironledger-phase-14-exit-contract.md` for the
  house style of an exit contract if you write one for this feature
  (optional, but every phase so far has one — check
  `docs/meta/contracts/` for the naming convention).

**Do:**
1. New router `src/ironledger/web/routers/compliance.py`:
   - `POST /api/compliance/bundles` — body: `ledger_id`, `framework`
     (one of `VALID_FRAMEWORKS`), `period_start_utc`, `period_end_utc`.
     Calls `generate_compliance_bundle` directly. Gated by
     `require_operator`.
   - `POST /api/compliance/bundles/verify` — accepts an uploaded archive
     (FastAPI `UploadFile`) plus optional `expected_merkle_root` /
     `expected_sha256`. Calls `verify_compliance_bundle`. Read-only
     (verification doesn't mutate state) — no operator token needed,
     but do enforce the same `MAX_ARCHIVE_BYTES` limit `bundle.py`
     already defines before reading the upload into memory.
2. New router `src/ironledger/web/routers/anomaly.py`:
   - `GET /api/anomaly/flags` — query params `ledger_id`, `status`
     (optional). Mirrors `run_anomaly_list`'s query exactly.
   - `POST /api/anomaly/scan` — body `ledger_id`, optional `rules` list.
     Loads staged transactions (same join as `run_anomaly_scan`), calls
     `scan_and_persist_anomalies`. Gated by `require_operator`.
   - `POST /api/anomaly/flags/{flag_id}/resolve` — body
     `resolution_status`, `actor`, `reason`. Calls `resolve_anomaly_flag`.
     Gated by `require_operator`.
   - Register both routers in `src/ironledger/web/app.py` the same way
     `tax` was registered.
3. Pydantic schemas in `src/ironledger/web/schemas.py` — mirror
   `ComplianceBundleResult`'s and `AnomalyFinding`'s field names exactly,
   don't invent new ones.
4. React panels:
   - `web/src/components/CompliancePanel.tsx` — framework picker
     (`SOC2_TYPE2` / `ISO27001` / `SOX` / `CUSTOM`), period range inputs,
     generate button, result card (bundle id, merkle root, sha256,
     record count, download/verify affordance).
   - `web/src/components/AnomalyPanel.tsx` — flags table (rule type,
     severity, score, status), filter by status, resolve action
     (status + reason form) per open flag, a "scan now" button.
   - Add both to `Sidebar.tsx`'s `ActiveView` union and nav list, wire
     into `App.tsx` the same way `'gains'` (tax) was wired.
5. `web/src/api.ts` — add the five fetch functions
   (`generateComplianceBundle`, `verifyComplianceBundle`,
   `getAnomalyFlags`, `scanAnomalies`, `resolveAnomalyFlag`) following
   the existing pattern.

**Hard constraints:**
- Scan/resolve/generate are the only writes here. Verify and list stay
  strictly read-only — no accidental mutation on a GET.
- No floating point in any new code path. Anomaly scores are already
  rational (`score_numerator` / `score_denominator` int64 pairs per
  `_assert_int64` in `anomaly.py`) — display as a formatted string in
  the UI, don't coerce to float client-side either if you can help it
  (a plain `numerator/denominator` string or a server-formatted decimal
  string is fine, matching how `tax.py` / `TaxPanel.tsx` already format
  rational amounts — check that file).
- No new runtime `import beancount`.
- Compliance bundle generation writes a file to `output_dir` — do not
  default this to anything inside the web container's static-serving
  path (`IRONLEDGER_STATIC_DIR`). Keep it under the existing data dir
  convention (check how other file-producing paths in this repo — e.g.
  compile output — pick their output directory).

**Tests (TDD, red-green):**
- `tests/test_web_compliance.py` — generate happy path, invalid
  framework, invalid period (`start > end`), missing operator token
  (401), verify happy path, verify tampered archive (bad sha256/merkle
  root → rejected), oversized archive rejected.
- `tests/test_web_anomaly.py` — scan happy path (persists flags), list
  with/without status filter, resolve happy path (flag transitions,
  governance audit event appended), resolve already-resolved flag
  (error), resolve missing flag (404), missing operator token on
  scan/resolve (401).
- Follow `tests/test_web_tax.py` (shipped `1458ba1`) for the FastAPI
  `TestClient` fixture conventions — copy it, don't reinvent.

**Verify:** full test suite green, `cd web && npm run build`,
`docker compose up -d --build`, open the workbench, generate a real
bundle against test data, confirm `ironledger compliance verify` (CLI)
agrees with the web verify endpoint on the same archive. Scan via UI,
confirm flags match `ironledger anomaly list` (CLI) output for the same
ledger.

## Known adjacent gap — flag, don't fix here

`src/ironledger/cli/compose_guard.py`'s mutating-command guard
(`_is_mutating_invocation` in `cli/__main__.py`) warns before
`import`/`compile`/`review`/`rule`/`fitid-trust`/`sync poll`/`prices
poll`/`web`/`project rebuild` when compose is sharing the SQLite file.
`compliance generate` and `anomaly scan`/`resolve` are CLI mutations too
and are **not** in that guarded list — grepped, confirmed absent. Same
corruption risk the guard was built to prevent (`ffba34f`) applies to
these two commands. Out of scope for this handoff (the web routes above
go through the API, not the CLI-against-shared-file path the guard
protects), but note it in your PR description so it doesn't get lost.
Do not silently expand this handoff's scope to fix it — flag it as a
separate one-line follow-up.

## Out of scope — do not touch

- `ledger-vault/` (nested private git repo, gitignored) or anything in
  `config/csv-profiles/` matching a real institution name — real
  personal financial data, kept out of this repo on purpose.
- `src/ironledger/cli/compose_guard.py` / `_is_mutating_invocation` —
  flag the gap above, don't refactor the guard itself here.
- Federation, failover — already shipped with UI, see correction above.
  Don't touch `FederationView.tsx` / `FailoverView.tsx` / their routers.
- Real PDF statement try-on, OCR, email/XLS/Zapier/NotebookLM ingest,
  packaging/versioning, identity-v2 — parked per
  `docs/meta/plans/ironledger-phase-15-handoff.md`, unrelated to this
  handoff, don't fold them in.

## Commit convention

`type(scope): summary`, e.g.
`feat(web): surface compliance bundles and anomaly flags in workbench`.
No attribution footer required (this repo's commits don't carry one).
