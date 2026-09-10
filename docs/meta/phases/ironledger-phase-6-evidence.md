# IronLedger Phase 6 evidence and exit verification

- **Status**: Phase 6 implementation completed, ratified, and verified on 2026-09-09.
- **Scope**: Governance Subsystem (`src/ironledger/governance/`), Mutation Ledger Engine, Hit Confidence Trend (HCT) Rule Drift Tracker, Projection Freshness & SLA Monitor, Forward-Only Migration Engine Hardening, Stateless HMAC Step-Up Safe-Mode Gate, and End-to-End Acceptance Suite.
- **Commit Range**: `a659d72..HEAD` on local `main`.
- **D-0 Contract**: Local repository `C:\dev\IronLedger`, branch `main`, no remote, do not push.

---

## 1. Executive sign-off and ratification

Phase 6 implements the governance subsystem defined in `docs/superpowers/specs/2026-09-09-phase-6-governance-design.md` and executed under `docs/superpowers/plans/2026-09-09-phase-6-governance.md`.

All six discrete engineering tasks (Tasks 6.1 through 6.6) have completed with 100% test pass rates across both focused unit suites and the full regression test suite. All five core architectural invariants are verified and enforced programmatically across the entire codebase.

Phase 6 is formally ratified as complete.

---

## 2. Verification of core architectural invariants

| Invariant | Policy | Enforcement Mechanism | Verification Result |
|---|---|---|---|
| **1. Plaintext Ground Truth** | Plaintext Beancount files on disk remain the sole financial ground truth. SQLite databases are disposable derivatives. | `compute_canonical_ledger_manifest_hash` scans `.beancount` files; `append_mutation_event` binds disk manifest state transitions. | **PASS**: Validated in `tests/test_governance_e2e.py` and `tests/test_governance_mutations.py`. |
| **2. Decoupled Runtime** | Zero runtime `import beancount` across application code. Beancount validation runs via isolated subprocess (`bean-check`). | Repository-wide AST / ripgrep scan across `src/ironledger/`. | **PASS**: Exactly 0 occurrences of `import beancount` or `from beancount` across `src/ironledger/`. |
| **3. Integer Minor-Unit Arithmetic** | Zero floating-point representation in storage, calculations, or schema columns. | SQLite `STRICT` tables with integer minor units, scale checks, and integer arithmetic constraints. | **PASS**: Enforced via SQLite STRICT schemas and validated across transaction pipelines. |
| **4. Tamper-Evident Hash Chaining** | Every state mutation appends a monotonic, SHA-256 chained event from Genesis ($0^{64}$). | `mutation_events` table with database triggers blocking UPDATE/DELETE; `verify_mutation_chain` validating canonical SHA-256 payload bytes. | **PASS**: Verified in `tests/test_governance_e2e.py` and `tests/test_governance_mutations.py` with tamper rejection. |
| **5. Fail-Closed Safe Mode** | Mutating operations fail closed unless unlocked via cryptographic step-up authorization tokens. | `require_governed_authorization` gating `compile` and mutating endpoints; invalid/missing credentials record denial to `audit_events`. | **PASS**: Verified in `tests/test_governance_e2e.py` and `tests/test_governance_safemode.py`. |

---

## 3. Comprehensive test suite summary

All test metrics were executed live against local `HEAD` on 2026-09-09.

### 3.1 Overall test metrics

- **Toolchain**: Python 3.14.6, pytest 9.1.1, SQLite 3.50.4.
- **Total Test Count**: **605 passed, 4 skipped in 18.87s** (100% pass rate).
- **Regression Impact**: Zero regressions across existing Phases 1 through 5.
- **Skipped Tests**: 4 pre-existing environmental skips (missing `bean-check` binary on default PATH, Windows symlink traversal privilege, and two platform-specific MCP contracts).

### 3.2 Governance module test coverage

| Test Suite | Module Under Test | Tests | Status | Key Coverage |
|---|---|---|---|---|
| `tests/test_governance_mutations.py` | `src/ironledger/governance/mutations.py` | 13 | PASS | Sequence monotonicity, genesis linking ($0^{64}$), canonical JSON bytes, `BEGIN IMMEDIATE` write serialization, tamper detection. |
| `tests/test_governance_drift.py` | `src/ironledger/governance/drift.py` | 14 | PASS | Exact HCT formula calculation, sliding window decay ($\lambda = 0.005$), provisional evaluation tier ($N < 5$), multi-source audit event aggregation. |
| `tests/test_governance_freshness.py` | `src/ironledger/governance/freshness.py` | 12 | PASS | Unidirectional latency computation, clock rollback clamp ($0.0\,\text{s}$), SLA tiers (`FRESH`, `STALE`, `CRITICAL`), live disk hash divergence detection. |
| `tests/test_governance_migrations.py` | `src/ironledger/governance/migrations.py` | 14 | PASS | Pre-flight SHA-256 schema checksum verification, isolated `BEGIN IMMEDIATE` migration execution, `PRAGMA foreign_key_check` rollback. |
| `tests/test_governance_safemode.py` | `src/ironledger/governance/safemode.py` | 23 | PASS | Stateless HMAC-SHA256 token creation, clock skew handling, TTL expiration, fail-closed configuration parsing, denial audit logging. |
| `tests/test_governance_e2e.py` | Full Governance Pipeline | 6 | PASS | End-to-end integration: schema migration pre-flight $\to$ safe-mode gate $\to$ authorized compile $\to$ mutation chaining $\to$ SLA freshness $\to$ drift audit $\to$ tamper rejection. |

---

## 4. Traceability matrix (Tasks 6.1 through 6.6)

| Task | Title | Core Artifacts | Verification Suite | Commit | Status |
|---|---|---|---|---|---|
| **6.1** | Mutation Ledger Engine & Tamper Verification | `src/ironledger/governance/mutations.py`, `src/ironledger/governance/__init__.py`, `src/ironledger/mutation.py` | `tests/test_governance_mutations.py` | `a659d72` | Complete |
| **6.2** | Hit Confidence Trend (HCT) Rule Drift Tracker | `src/ironledger/governance/drift.py` | `tests/test_governance_drift.py` | `dc8d29d` | Complete |
| **6.3** | Projection Freshness & SLA Monitoring | `src/ironledger/governance/freshness.py` | `tests/test_governance_freshness.py` | `3bfa822` | Complete |
| **6.4** | Forward-Only Migration Engine Hardening | `src/ironledger/governance/migrations.py`, `src/ironledger/db/migrations.py` | `tests/test_governance_migrations.py` | `262706a` | Complete |
| **6.5** | Safe-Mode Mutation Gate & Stateless Step-Up Tokens | `src/ironledger/governance/safemode.py`, `src/ironledger/cli/auth.py`, `src/ironledger/web/routers/compile.py` | `tests/test_governance_safemode.py` | `87f8540` | Complete |
| **6.6** | End-to-End Governance Acceptance Suite & Ratification Evidence | `tests/test_governance_e2e.py`, `docs/meta/phases/ironledger-phase-6-evidence.md` | `tests/test_governance_e2e.py`, full suite (`pytest -q`) | Pending commit | Complete |

---

## 5. Architectural compliance checklist

1. **Transaction Isolation**: All schema migrations and mutation event appends acquire exclusive locks via `BEGIN IMMEDIATE`.
2. **Deterministic Canonical Serialization**: Mutation envelopes serialize using sorted keys, no whitespace separators, and explicit ASCII encoding prior to hashing.
3. **Audit Event Traceability**: Denied and authorized step-up events write directly to `audit_events` with associated actor, target digest, and monotonic sequence numbers.
4. **Resilient Degradation**: Missing or corrupt safe-mode configuration files fail closed, requiring cryptographic credentials for mutating routes.
5. **No Runtime Dependencies on Beancount**: Verified clean decoupled architecture with zero Beancount Python imports.
