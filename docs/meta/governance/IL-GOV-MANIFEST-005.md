# IronLedger Phase 5 implementation manifest (IL-GOV-MANIFEST-005)

- **Document ID**: `IL-GOV-MANIFEST-005`
- **Status**: Ratified
- **Ratification Date**: 2026-09-09
- **Baseline Commit**: `6a7ab78`
- **Release Commit**: `2f06157`
- **Test Metric**: 448 passed, 2 skipped, 0 failures (100% passing)

---

## 1. Commit manifest

| Commit hash | Category | Description |
|---|---|---|
| `dd663ff` | `feat(web)` | Add Pydantic schemas with minor-unit integer conventions and validation guards |
| `0e70508` | `feat(web)` | Add staging review endpoints, confidence scoring, and FastAPI app factory |
| `2e90134` | `feat(web)` | Add rule management and Hit Confidence Trend (HCT) drift detection router |
| `ab09403` | `feat(web)` | Add projection query, FTS5 search, and freshness latency check endpoints |
| `b241642` | `feat(web)` | Add compile router with lock acquisition and safe-mode dry-run simulation |
| `77b3673` | `feat(ui)` | Implement React 19 operator workbench with keyboard-first navigation and modals |
| `2f06157` | `feat(cli)` | Wire `ironledger web` command and add Phase 5 end-to-end acceptance suite |

---

## 2. File and module topology

### 2.1 Backend service (`src/ironledger/web/`)

| File path | Purpose | Invariants enforced |
|---|---|---|
| `src/ironledger/web/__init__.py` | Package root and exports | Clean namespace |
| `src/ironledger/web/schemas.py` | Pydantic request/response models | Strict integer minor units; float/bool rejection |
| `src/ironledger/web/app.py` | FastAPI app factory & static asset mount | CORS isolation, dependency injection |
| `src/ironledger/web/routers/staging.py` | Staging review and split router | Zero-sum split balance conservation |
| `src/ironledger/web/routers/rules.py` | Rule CRUD & HCT drift calculation | Indexed drift status metrics |
| `src/ironledger/web/routers/projection.py` | Balances, FTS search & freshness | Zero-lock read query isolation |
| `src/ironledger/web/routers/compile.py` | Safe-mode compile & simulation | Lock acquisition; 0-mutation dry-run |
| `src/ironledger/web/routers/system.py` | Safe mode state & audit trail | Hash-chained audit event inspection |

### 2.2 Frontend SPA (`web/`)

| File path | Purpose |
|---|---|
| `web/package.json` | React 19, TypeScript, Vite, Tailwind CSS, Lucide icons dependencies |
| `web/src/App.tsx` | Main application shell and three-pane layout |
| `web/src/api.ts` | Type-safe REST client for backend endpoints |
| `web/src/types.ts` | TypeScript domain types matching Pydantic schemas |
| `web/src/components/TopHUD.tsx` | Safe mode status banner, freshness pill, token display |
| `web/src/components/Sidebar.tsx` | View switcher with dynamic staging inbox count |
| `web/src/components/RegisterGrid.tsx` | Virtualized transaction grid with keyboard-driven review |
| `web/src/components/InspectorSidecar.tsx` | Plaintext Beancount syntax preview & rule drift card |
| `web/src/components/RuleWizardModal.tsx` | Regex rule candidate extraction & hit preview |
| `web/src/components/CommandPalette.tsx` | Global `Ctrl+K` operator shortcut dispatcher |
| `web/src/components/SimulationModal.tsx` | Safe-mode dry-run diff viewer |

### 2.3 CLI integration (`src/ironledger/cli/`)

| File path | Purpose |
|---|---|
| `src/ironledger/cli/commands/__init__.py` | CLI commands package marker |
| `src/ironledger/cli/commands/web.py` | Uvicorn server launcher with auto browser launch option |
| `src/ironledger/cli/__main__.py` | `ironledger web` parser and execution dispatch |

---

## 3. Test coverage and validation inventory

| Test suite file | Test count | Scope verified |
|---|---|---|
| `tests/test_web_schemas.py` | 9 | Integer minor units, currency validation, float/bool rejection |
| `tests/test_web_staging.py` | 5 | Staging listing, approve, reject, split, balance validation |
| `tests/test_web_rules.py` | 4 | Rule creation, disable, candidate extraction, drift calculation |
| `tests/test_web_projection.py` | 4 | Balance hierarchy, FTS5 search, freshness latency calculation |
| `tests/test_web_compile.py` | 4 | Safe-mode compile gating, `.compile.lock`, dry-run diff isolation |
| `tests/test_cli_web.py` | 3 | CLI argument parsing, defaults, and Uvicorn invocation |
| `tests/test_phase5_e2e.py` | 1 | Full end-to-end ingest &rarr; review &rarr; compile &rarr; projection &rarr; audit |
| Pre-existing suites (Phase 1–4) | 418 | Ingestion, hashing, compilation, recovery, projection, CLI |
| **Total Test Suite** | **448** | **100% passing (0 failures, 2 skipped)** |
