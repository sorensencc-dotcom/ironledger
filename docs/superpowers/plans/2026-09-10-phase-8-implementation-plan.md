# IronLedger Phase 8: Multi-Asset Valuation, Ledger Lineage & Audit Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Phase 8 of IronLedger: Multi-Asset Valuation, Ledger Lineage & Audit Replay with pure integer rational arithmetic, bi-directional lineage DAG tracking, multi-tenant database & filesystem isolation, deterministic point-in-time audit replay with dual projection/manifest fingerprints, cryptographic capability tokens with RBAC ceilings, and comprehensive AST guards.

**Architecture:** Forward-only SQLite migrations (`0008` through `0011`) with strict table constraints, composite tenant foreign keys, and custom deterministic SQL functions (`sha256_hex`, `sign_authority_sql`). Subsystems are organized in modular packages: `ironledger.valuation`, `ironledger.lineage`, `ironledger.ledger`, `ironledger.replay`, and `ironledger.auth`.

**Tech Stack:** Python 3.12+, SQLite 3 (STRICT mode, foreign keys ON), Pydantic v2, portalocker, FastAPI, pytest.

## Global Constraints

- **Exact Rational Integer Arithmetic:** All price calculations, conversions, and rounding operate exclusively on integers (`minor_units`, `numerator`, `denominator`). Zero float drift; zero `/` operators in valuation and rendering paths.
- **Banker's Half-Even Rounding:** Exact integer Banker's rounding across all scales, including `precision_scale == 0`.
- **Zero Runtime `import beancount`:** All Beancount directives emitted via deterministic string formatting, guarded by symbol-tracking static AST analysis.
- **Tenant Domain Isolation:** Relational composite primary keys `PRIMARY KEY(ledger_id, id)` and composite foreign keys `FOREIGN KEY(ledger_id, parent_id) REFERENCES parent(ledger_id, parent_id)` with `PRAGMA foreign_keys = ON;`.
- **Filesystem Path Safety & Symlink Refusal:** Path hierarchy inspection rejecting symlinks and verifying directory containment via `Path.relative_to`.
- **Deterministic Cryptographic Audit Replay:** Merkle hash chain + Authority Signatures + external out-of-band trust anchors (`.ironledger/anchors/<ledger_id>.anchor.json`) with dual projection and manifest fingerprint verification against genesis anchors.

---

## Proposed Changes & Tasks

### Task 8.1: Multi-Asset Valuation Engine & Price Directives Cache
- **Files:**
  - `src/ironledger/db/schema/0008_price_history.sql`
  - `src/ironledger/valuation/__init__.py`
  - `src/ironledger/valuation/models.py`
  - `src/ironledger/valuation/formatting.py`
  - `src/ironledger/valuation/engine.py`
  - `tests/test_valuation.py`
- **Deliverables:** Rational conversion engine with zero float drift, Banker's integer rounding, price directive string template formatting.

### Task 8.2: Ledger Lineage Explorer & Bi-Directional Provenance DAG
- **Files:**
  - `src/ironledger/db/schema/0009_ledger_lineage.sql`
  - `src/ironledger/lineage/__init__.py`
  - `src/ironledger/lineage/models.py`
  - `src/ironledger/lineage/explorer.py`
  - `tests/test_lineage.py`
- **Deliverables:** Bi-directional recursive CTE DAG traversals, insertion-time cycle detection, and self-edge rejection within tenant boundaries.

### Task 8.3: Multi-Ledger Topology & Isolated Staging Queues
- **Files:**
  - `src/ironledger/db/schema/0010_multi_ledger_rbac.sql` (Part 1: Multi-ledger tables, indexes, triggers)
  - `src/ironledger/ledger/__init__.py`
  - `src/ironledger/ledger/models.py`
  - `src/ironledger/ledger/topology.py`
  - `src/ironledger/ledger/staging.py`
  - `src/ironledger/ledger/consolidation.py`
  - `src/ironledger/governance/migrations.py`
  - `tests/test_multi_ledger.py`
- **Deliverables:** Multi-tenant catalog, composite primary/foreign keys, tenant staging isolation, compile lockfiles, path traversal/symlink guards, and consolidated multi-entity reporting.

### Task 8.4: Deterministic Audit Replay & Outbox Point-in-Time Engine
- **Files:**
  - `src/ironledger/db/schema/0011_mutation_payloads.sql`
  - `src/ironledger/replay/__init__.py`
  - `src/ironledger/replay/models.py`
  - `src/ironledger/replay/schemas.py`
  - `src/ironledger/replay/anchors.py`
  - `src/ironledger/replay/snapshot.py`
  - `src/ironledger/replay/engine.py`
  - `src/ironledger/manifests.py`
  - `tests/test_replay.py`
- **Deliverables:** Replay engine verifying global sequence contiguity, Merkle hash chains, authority signatures, external trust anchor commitments, and dual projection/manifest fingerprints into ephemeral in-memory database and manifest directory.

### Task 8.5: Scoped Capability Tokens & RBAC Policy Enforcement
- **Files:**
  - `src/ironledger/auth/__init__.py`
  - `src/ironledger/auth/models.py`
  - `src/ironledger/auth/tokens.py`
  - `src/ironledger/auth/signing.py`
  - `src/ironledger/auth/policy.py`
  - `tests/test_capabilities.py`
- **Deliverables:** Capability token manager with issuance-time role ceiling checks, constant-time token hash verification, expiration/revocation checks, and cryptographic signing authority.

### Task 8.6: Acceptance Regression Suite & Phase 8 Exit Evidence
- **Files:**
  - `tests/test_phase8_exit_contract.py`
  - `docs/meta/phases/ironledger-phase-8-evidence.md`
- **Deliverables:** Symbol-tracking AST scanner forbidding `import beancount`, zero-float AST visitor, full end-to-end regression pass, and Phase 8 exit evidence document.

---

## Verification Plan

### Automated Tests
- `pytest tests/test_valuation.py -v`
- `pytest tests/test_lineage.py -v`
- `pytest tests/test_multi_ledger.py -v`
- `pytest tests/test_replay.py -v`
- `pytest tests/test_capabilities.py -v`
- `pytest tests/test_phase8_exit_contract.py -v`
- `pytest -v` (Full suite regression pass)
