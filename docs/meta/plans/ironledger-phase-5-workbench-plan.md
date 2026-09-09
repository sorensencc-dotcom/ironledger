# IronLedger Phase 5 Frontend Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and ship the local-first IronLedger Enterprise Operator Workbench comprising a high-assurance FastAPI service, a React 19 / TypeScript / Vite / Tailwind SPA, and verified integration across staging review, rule drift detection, safe-mode-gated compilation, and projection freshness.

**Architecture:** A new backend package `src/ironledger/web/` exposes read and mutation endpoints over `ironledger.db` and `projection.db`. All mutations enforce `config/safe-mode.json` checks and log to the hash-chained `audit_events` table. A modular React 19 SPA (`web/`) delivers a three-pane Unified Workbench with keyboard-first ergonomics (`↑`/`↓`/`Enter`/`Ctrl+Enter`), real-time Inspector with Beancount syntax previews, Rule Drift analysis, and safe-mode dry-run simulations.

**Tech Stack:** Python 3.12+ (`fastapi`, `uvicorn`, `pydantic`), SQLite3 stdlib, React 19, TypeScript, Vite, Tailwind CSS, TanStack Table & Query, Lucide icons, Vitest, and Pytest.

**Global Constraints:**
- Zero `import beancount` runtime dependency across `src/ironledger/`.
- Monetary amounts are strictly integer minor units (`int`) with explicit ISO-4217 scales.
- Safe Mode enforces strict gating on ledger compilation and projection rebuilds.
- All file locks (`.compile.lock`, `.project.lock`) must be acquired through existing lock managers.
- D-0: local repo `C:\dev\IronLedger`, no remote, do not push.

---

## File Structure & Responsibilities

### Backend (`src/ironledger/web/`)
| Path | Responsibility |
|---|---|
| `src/ironledger/web/__init__.py` | Package entrypoint, version export, app factory |
| `src/ironledger/web/app.py` | FastAPI application setup, CORS, error handlers, static asset mounting |
| `src/ironledger/web/schemas.py` | Pydantic request/response models with minor-unit integer amounts |
| `src/ironledger/web/routers/staging.py` | Endpoints for staging queue, confidence scores, and approvals |
| `src/ironledger/web/routers/rules.py` | Rule CRUD, rule candidate extraction, and drift metrics calculation |
| `src/ironledger/web/routers/projection.py` | Balances tree, FTS5 search, and freshness latency check |
| `src/ironledger/web/routers/compile.py` | Safe-mode-gated compile, dry-run simulation, and projection rebuild |
| `src/ironledger/web/routers/system.py` | Safe mode status, token management, and audit log history |

### Frontend (`web/`)
| Path | Responsibility |
|---|---|
| `web/package.json` | React 19, Vite, Tailwind, TanStack Query/Table dependencies |
| `web/src/App.tsx` | Root shell with Top HUD, Left Sidebar, Main Register, Right Sidecar |
| `web/src/components/TopHUD.tsx` | Safe mode banner, Projection freshness pill, Token countdown |
| `web/src/components/Sidebar.tsx` | Viewport router (Staging, Journal, Balances, Budget, Rules, Audit) |
| `web/src/components/RegisterGrid.tsx` | Keyboard-driven data grid with confidence heatmaps |
| `web/src/components/InspectorSidecar.tsx` | Matched rule details, rule drift alert, and Beancount syntax preview |
| `web/src/components/RuleWizardModal.tsx` | Regex candidate generator and retroactive match preview |
| `web/src/components/CommandPalette.tsx` | `Ctrl+K` global action dispatcher |
| `web/src/components/SimulationModal.tsx` | Safe mode dry-run diff and balance delta inspector |

---

## Bite-Sized Implementation Tasks

### Task 1: FastAPI Backend Schemas & Minor-Unit Validation
**Files:**
- Create: `src/ironledger/web/__init__.py`
- Create: `src/ironledger/web/schemas.py`
- Test: `tests/test_web_schemas.py`

**Interfaces:**
- Consumes: `src/ironledger/conventions.py` (`validate_currency`, `currency_scale`)
- Produces: `Pydantic` models for `StagedTransactionResponse`, `PostingSchema`, `RuleDriftResponse`, `CompileRequest`

- [ ] **Step 1: Write failing schema tests**
- [ ] **Step 2: Run test to verify failure** (`pytest tests/test_web_schemas.py`)
- [ ] **Step 3: Implement schemas with strict integer minor-unit amount enforcement**
- [ ] **Step 4: Run test to verify pass** (`pytest tests/test_web_schemas.py`)
- [ ] **Step 5: Commit** (`git commit -m "feat(web): add pydantic schemas with minor-unit conventions"`)

---

### Task 2: Staging & Review API Router
**Files:**
- Create: `src/ironledger/web/routers/staging.py`
- Create: `src/ironledger/web/app.py`
- Test: `tests/test_web_staging.py`

**Interfaces:**
- Consumes: `src/ironledger/review/workflow.py`, `src/ironledger/db/connection.py`
- Produces: `GET /api/staging`, `POST /api/staging/{id}/approve`, `POST /api/staging/{id}/split`

- [ ] **Step 1: Write failing staging endpoint tests**
- [ ] **Step 2: Run test to verify failure** (`pytest tests/test_web_staging.py`)
- [ ] **Step 3: Implement staging router with confidence score calculations**
- [ ] **Step 4: Run test to verify pass** (`pytest tests/test_web_staging.py`)
- [ ] **Step 5: Commit** (`git commit -m "feat(web): add staging review endpoints"`)

---

### Task 3: Rule Management & Drift Detection Router
**Files:**
- Create: `src/ironledger/web/routers/rules.py`
- Test: `tests/test_web_rules.py`

**Interfaces:**
- Consumes: `src/ironledger/db/` rule tables
- Produces: `GET /api/rules`, `POST /api/rules/candidate`, `GET /api/rules/{id}/drift`

- [ ] **Step 1: Write failing rule and drift metric tests**
- [ ] **Step 2: Run test to verify failure** (`pytest tests/test_web_rules.py`)
- [ ] **Step 3: Implement rule candidate generator and Hit Confidence Trend (HCT) engine**
- [ ] **Step 4: Run test to verify pass** (`pytest tests/test_web_rules.py`)
- [ ] **Step 5: Commit** (`git commit -m "feat(web): add rule management and drift detection router"`)

---

### Task 4: Projection Balances, FTS Search & Freshness Latency Check
**Files:**
- Create: `src/ironledger/web/routers/projection.py`
- Test: `tests/test_web_projection.py`

**Interfaces:**
- Consumes: `src/ironledger/project/query.py`, `src/ironledger/manifests.py`
- Produces: `GET /api/balances`, `GET /api/search`, `GET /api/projection/freshness`

- [ ] **Step 1: Write failing projection query & freshness tests**
- [ ] **Step 2: Run test to verify failure** (`pytest tests/test_web_projection.py`)
- [ ] **Step 3: Implement balance rollups, FTS5 search wrapper, and manifest age calculator**
- [ ] **Step 4: Run test to verify pass** (`pytest tests/test_web_projection.py`)
- [ ] **Step 5: Commit** (`git commit -m "feat(web): add projection query and freshness endpoints"`)

---

### Task 5: Safe-Mode-Gated Compiler & Dry-Run Simulation Router
**Files:**
- Create: `src/ironledger/web/routers/compile.py`
- Test: `tests/test_web_compile.py`

**Interfaces:**
- Consumes: `src/ironledger/compile/writer.py`, `src/ironledger/compile/render.py`, `src/ironledger/project/activate.py`
- Produces: `POST /api/compile`, `POST /api/compile/simulate`, `POST /api/project/rebuild`

- [ ] **Step 1: Write failing compile lock, safe-mode rejection, and simulation tests**
- [ ] **Step 2: Run test to verify failure** (`pytest tests/test_web_compile.py`)
- [ ] **Step 3: Implement compile router acquiring `.compile.lock` and dry-run renderer**
- [ ] **Step 4: Run test to verify pass** (`pytest tests/test_web_compile.py`)
- [ ] **Step 5: Commit** (`git commit -m "feat(web): add compile router with safe-mode simulation"`)

---

### Task 6: React Frontend Scaffolding & Theme System
**Files:**
- Create: `web/package.json`, `web/vite.config.ts`, `web/tailwind.config.js`
- Create: `web/src/index.css`, `web/src/main.tsx`, `web/src/App.tsx`
- Test: `web/tests/app.test.tsx`

- [ ] **Step 1: Setup React + Vite + Tailwind scaffolding with Slate & Indigo tokens**
- [ ] **Step 2: Verify frontend dev build and test environment**
- [ ] **Step 3: Implement core workbench frame and test render**
- [ ] **Step 4: Commit** (`git commit -m "feat(ui): scaffold react workbench with slate-indigo theme"`)

---

### Task 7: Top Navigation HUD (Safe Mode, Freshness Pill, Token HUD)
**Files:**
- Create: `web/src/components/TopHUD.tsx`
- Test: `web/tests/TopHUD.test.tsx`

- [ ] **Step 1: Write unit test for freshness pill color transitions and safe mode status**
- [ ] **Step 2: Implement TopHUD component with live polling queries**
- [ ] **Step 3: Verify component test passes**
- [ ] **Step 4: Commit** (`git commit -m "feat(ui): add top navigation HUD with freshness & safe mode banner"`)

---

### Task 8: Keyboard-Driven Register Grid & Confidence Heatmap
**Files:**
- Create: `web/src/components/RegisterGrid.tsx`
- Test: `web/tests/RegisterGrid.test.tsx`

- [ ] **Step 1: Write test for arrow key row selection and approval shortcut (`Enter`)**
- [ ] **Step 2: Implement TanStack Table with keyboard event handlers and confidence heatmaps**
- [ ] **Step 3: Verify keyboard navigation and row selection pass**
- [ ] **Step 4: Commit** (`git commit -m "feat(ui): add keyboard-first transaction register grid"`)

---

### Task 9: Contextual Inspector Sidecar (Rule Drift & Beancount Preview)
**Files:**
- Create: `web/src/components/InspectorSidecar.tsx`
- Test: `web/tests/InspectorSidecar.test.tsx`

- [ ] **Step 1: Write tests for real-time Beancount syntax generation and drift warning badges**
- [ ] **Step 2: Implement Inspector sidecar with posting editor and 1-click rule learning**
- [ ] **Step 3: Verify tests pass**
- [ ] **Step 4: Commit** (`git commit -m "feat(ui): add inspector sidecar with beancount preview and drift alerts"`)

---

### Task 10: Rule Creation Wizard & Command Palette (`Ctrl+K`)
**Files:**
- Create: `web/src/components/RuleWizardModal.tsx`
- Create: `web/src/components/CommandPalette.tsx`
- Test: `web/tests/RuleWizard.test.tsx`

- [ ] **Step 1: Write tests for regex extraction and command palette triggers**
- [ ] **Step 2: Implement Rule Creation Wizard and global command palette**
- [ ] **Step 3: Verify tests pass**
- [ ] **Step 4: Commit** (`git commit -m "feat(ui): add rule creation wizard and command palette"`)

---

### Task 11: End-to-End Integration & CLI Launch Smoke
**Files:**
- Create: `src/ironledger/cli/commands/web.py`
- Modify: `src/ironledger/cli/__main__.py`
- Test: `tests/test_cli_web.py`, `tests/test_phase5_e2e.py`

- [ ] **Step 1: Add `python -m ironledger web` CLI command**
- [ ] **Step 2: Run end-to-end suite verifying full pipeline: Ingest &rarr; Review &rarr; Compile &rarr; Projection &rarr; UI Sync**
- [ ] **Step 3: Verify complete suite passes** (`pytest -q`)
- [ ] **Step 4: Commit** (`git commit -m "feat(cli): wire web command and add Phase 5 e2e acceptance suite"`)

