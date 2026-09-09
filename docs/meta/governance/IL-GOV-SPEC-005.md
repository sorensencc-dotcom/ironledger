# IronLedger Phase 5 governance specification (IL-GOV-SPEC-005)

- **Document ID**: `IL-GOV-SPEC-005`
- **Status**: Ratified
- **Ratification Date**: 2026-09-09
- **Domain**: Operator Workbench, Web API, and Review Ergonomics
- **Enforcement Level**: Mandatory / Invariant

---

## 1. Purpose and scope

This specification defines the formal architectural, cryptographic, and interface invariants for the IronLedger Phase 5 Operator Workbench. The Operator Workbench provides a local-first interface for staging review, rule learning, drift detection, dry-run simulation, ledger compilation, and projection inspection.

---

## 2. Core architectural invariants

Every component in Phase 5 must strictly enforce the following invariants:

1. **Zero Beancount runtime import**:
   - No module in `src/ironledger/` may execute `import beancount`.
   - Plaintext ledger files are written and parsed using deterministic internal renderers and parsers.

2. **Strict minor-unit integer arithmetic**:
   - All monetary amounts in API request and response models must be integer minor units (`int`).
   - Floats and booleans are strictly rejected at the schema validator level via `mode="before"` type guards.
   - Currency codes must conform to ISO-4217 standard naming validated through `ironledger.conventions`.

3. **Safe-mode compile and rebuild gating**:
   - Mutations affecting ledger files (`POST /api/compile`) or projection databases (`POST /api/project/rebuild`) require safe mode to be disabled or must provide a verified authorization token (`"authorize compile"` / `"authorize project"`).
   - Unauthorized attempts must log a `denied` event to the append-only `audit_events` table and return HTTP 403.

4. **Zero-mutation simulation isolation**:
   - Dry-run compilation (`POST /api/compile/simulate` or `POST /api/compile` with `dry_run: true`) must execute entirely in memory.
   - Dry-run simulations must produce zero byte changes on disk and write zero rows to `audit_events`.

5. **Multi-leg split balance conservation**:
   - Splitting a staged transaction contra leg (`POST /api/staging/{id}/split`) must preserve exact zero-sum balance against the imported leg.
   - Non-zero balance splits must be rejected with HTTP 400.

---

## 3. Web API endpoint catalog

The FastAPI application factory (`src/ironledger/web/app.py`) mounts the following routers:

### 3.1 Staging and review router (`/api/staging`)

| Method | Path | Description | Status codes |
|---|---|---|---|
| `GET` | `/api/staging` | List staged transactions with confidence scores and postings | `200` |
| `POST` | `/api/staging/{stx_id}/categorize` | Assign contra account to staged transaction | `200`, `400` |
| `POST` | `/api/staging/{stx_id}/approve` | Approve staged transaction for compilation | `200`, `400` |
| `POST` | `/api/staging/{stx_id}/reject` | Mark staged transaction as rejected with audit note | `200`, `400` |
| `POST` | `/api/staging/{stx_id}/split` | Split contra leg into multiple balanced postings | `200`, `400`, `404` |

### 3.2 Rule management and drift router (`/api/rules`)

| Method | Path | Description | Status codes |
|---|---|---|---|
| `GET` | `/api/rules` | List all active and disabled categorization rules | `200` |
| `POST` | `/api/rules` | Create a new categorization rule | `200`, `400` |
| `POST` | `/api/rules/{rule_id}/disable` | Disable an existing categorization rule | `200`, `400` |
| `POST` | `/api/rules/candidate` | Extract regex pattern candidate from staged transaction | `200`, `404` |
| `GET` | `/api/rules/{rule_id}/drift` | Compute Hit Confidence Trend (HCT) and drift metrics | `200`, `404` |

### 3.3 Analytics projection router (`/api`)

| Method | Path | Description | Status codes |
|---|---|---|---|
| `GET` | `/api/balances` | Query account balance hierarchy with formatted amounts | `200`, `500` |
| `GET` | `/api/search` | Execute FTS5 query across accounts, narrations, and payees | `200`, `400`, `500` |
| `GET` | `/api/projection/freshness` | Evaluate projection latency and synchronization status | `200` |

### 3.4 Safe-mode compile and simulation router (`/api`)

| Method | Path | Description | Status codes |
|---|---|---|---|
| `POST` | `/api/compile` | Compile approved transactions with lock acquisition | `200`, `400`, `403` |
| `POST` | `/api/compile/simulate` | Dry-run compile simulation returning unified diff preview | `200`, `400` |
| `POST` | `/api/project/rebuild` | Rebuild SQLite projection from compiled plaintext files | `200`, `400` |

### 3.5 System and audit router (`/api/system`)

| Method | Path | Description | Status codes |
|---|---|---|---|
| `GET` | `/api/system/safe-mode` | Retrieve safe-mode configuration and token status | `200` |
| `GET` | `/api/system/audit` | Query hash-chained audit log records | `200` |

---

## 4. UI architecture and register topology

The React 19 single-page application (`web/`) delivers a three-pane layout:

1. **Left Navigation Sidebar (`Sidebar.tsx`)**:
   - Direct switching between Staging Inbox, Journal, Balances, Envelope Budget, Rules, and Audit Trail.
   - Dynamic badge showing unreviewed staged transaction count.

2. **Main Register Grid (`RegisterGrid.tsx`)**:
   - Virtualized data grid supporting high-volume transaction sets.
   - Full keyboard navigation: `↑` / `↓` for row selection, `Enter` for approval, `X` for rejection, `S` for split, `Ctrl+R` for rule creation.
   - Confidence heatmap styling based on calculated machine categorization score.

3. **Contextual Inspector Sidecar (`InspectorSidecar.tsx`)**:
   - Live immutable Beancount plaintext syntax preview for the active row.
   - Hit Confidence Trend (HCT) drift status panel with override rates.
   - Source evidence provenance metadata (document ID, record ID, staged ID).

4. **Top Navigation HUD (`TopHUD.tsx`)**:
   - Global Safe Mode state indicator.
   - Projection Freshness pill with latency thresholds.
   - Command palette launcher (`Ctrl+K`).

---

## 5. Deployment and container topology

The Operator Workbench provides two deployment targets:

1. **Self-Contained Docker Architecture (`Dockerfile`, `docker-compose.yml`)**:
   - **Multi-stage build**: Node 22-alpine compiles the React 19 SPA (`web/dist/`); Python 3.12-slim runtime bundles FastAPI, Uvicorn, and OFX tools with zero Beancount Python runtime dependencies.
   - **Persistent Volume Mount**: Mounts repository root (`.:/data`) preserving `ironledger.db`, `projection.db`, `config/`, and `evidence/` on host.
   - **Auto-restart Policy**: `restart: unless-stopped` ensuring the workbench runs as an uninterrupted background daemon.

2. **Host CLI Execution (`ironledger web`)**:
   - Local development and direct execution via Uvicorn serving static SPA assets mounted at `/`.
