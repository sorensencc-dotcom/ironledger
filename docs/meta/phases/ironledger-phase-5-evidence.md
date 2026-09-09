# IronLedger Phase 5 evidence and exit verification

- **Status**: Phase 5 implementation completed and ratified on 2026-09-09.
- **Scope**: Local-first Operator Workbench, FastAPI REST API (`src/ironledger/web/`), React 19 SPA (`web/`), and CLI command (`ironledger web`).
- **Commit Range**: `dd663ff..2f06157` on local `main`.
- **D-0 Contract**: Local repository `C:\dev\IronLedger`, branch `main`, no remote, do not push.

---

## 1. Provenance of evidence

Phase 5 was implemented against `docs/meta/specs/ironledger-phase-5-workbench-design.md` and `docs/meta/plans/ironledger-phase-5-workbench-plan.md`. Subagent-driven development (SDD) executed across 11 discrete tasks tracked in `.superpowers/sdd/progress.md`.

All metrics in this document were verified live against local `HEAD` on 2026-09-09.

---

## 2. Environment and test metrics

| Item | Value |
|---|---|
| Repository path | `C:\dev\IronLedger` |
| Git branch | `main` |
| Toolchain | Python 3.14.6, Node.js v22.14.0, Vite 6.4.3, React 19.1.0, pytest 9.1.1 |
| Pytest suite | **448 passed, 2 skipped in 10.47s** (100% passing) |
| Frontend build | **Built cleanly into `web/dist/`** via `tsc && vite build` |
| `beancount` Python dep | None on runtime path (`src/ironledger/` does not import `beancount`) |

---

## 3. Implemented components and endpoints

### 3.1 Backend package (`src/ironledger/web/`)
- `schemas.py`: Pydantic models enforcing integer minor units and ISO-4217 currency codes.
- `app.py`: FastAPI application factory with dependency injection and static dist asset mounting.
- `routers/staging.py`: Endpoints for staging queue, categorize, approve, reject, and multi-leg splits.
- `routers/rules.py`: Rule management, regex candidate extraction, and Hit Confidence Trend (HCT) drift status calculation.
- `routers/projection.py`: Account balances hierarchy, FTS5 search, and freshness latency check.
- `routers/compile.py`: Safe-mode gated compile execution, dry-run simulation, and projection rebuild.
- `routers/system.py`: Safe mode status check and hash-chained audit log inspection.

### 3.2 Frontend SPA (`web/`)
- Three-pane layout with navigation sidebar, virtualized register grid, and contextual inspector sidecar.
- Plaintext Beancount preview with rule drift alerting.
- Modals for Rule Creation Wizard (`RuleWizardModal.tsx`), Command Palette (`CommandPalette.tsx`), and Simulation Diff Inspector (`SimulationModal.tsx`).

### 3.3 CLI command (`src/ironledger/cli/commands/web.py`)
- `ironledger web` subcommand with options: `--host`, `--port`, `--db`, `--projection-db`, `--reload`, and `--open-browser`.

### 3.4 Container infrastructure (`Dockerfile`, `docker-compose.yml`)
- Multi-stage Dockerfile compiling React 19 SPA and running FastAPI on Python 3.12-slim.
- Docker Compose configuration mounting host repository root (`.:/data`) for continuous host persistence with `restart: unless-stopped` background automation.

---

## 4. Governance documents

The Phase 5 specification and test matrices are codified under `docs/meta/governance/`:
- `IL-GOV-SPEC-005.md`: Architectural invariants, API catalog, and UI register topology.
- `IL-GOV-MANIFEST-005.md`: Implementation commit inventory, file map, and test suite metrics.
- `IL-GOV-TEST-005.md`: Automated test matrices and acceptance vectors.
- `IL-GOV-AMENDMENTS-005.md`: Formal governance modification register.
