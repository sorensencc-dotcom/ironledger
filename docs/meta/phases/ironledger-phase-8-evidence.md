# IronLedger Phase 8 evidence and exit verification

- **Status**: Phase 8 implementation completed, ratified, and verified on 2026-09-11.
- **Scope**: Multi-Asset Valuation Engine & Price Directives Cache (`src/ironledger/valuation/`), Ledger Lineage Explorer & Bi-Directional Provenance DAG (`src/ironledger/lineage/`), Multi-Ledger Topology & Isolated Staging Queues (`src/ironledger/ledger/`), Deterministic Audit Replay & Outbox Point-in-Time Engine (`src/ironledger/replay/`, `src/ironledger/manifests.py`), Scoped Capability Tokens & RBAC Policy Enforcement (`src/ironledger/auth/`), and End-to-End Acceptance Regression Suite (`tests/test_phase8_exit_contract.py`).
- **Commit Range**: `d3274bd..HEAD` on local `main`.
- **D-0 Contract**: Local repository `C:\dev\IronLedger`, branch `main`, no remote, do not push.

---

## 1. Executive sign-off and ratification

Phase 8 delivers multi-asset valuation, bi-directional lineage graphs, multi-tenant ledger isolation, deterministic point-in-time audit replay, and role-based capability tokens defined in `docs/meta/specs/ironledger-phase-8-spec.md`.

All six discrete engineering tasks (Tasks 8.1 through 8.6) have completed with 100% test pass rates across both focused unit suites and the full regression test suite. All core architectural invariants (plaintext ground truth, decoupled runtime, integer rational arithmetic, tamper-evident Merkle hash chaining, and fail-closed tenant boundary isolation) are enforced programmatically across the entire codebase.

Phase 8 is formally ratified as complete.

---

## 2. Verification of core architectural invariants

| Invariant | Policy | Enforcement Mechanism | Verification Result |
|---|---|---|---|
| **1. Zero Runtime Beancount Import** | Zero runtime `import beancount` or dynamic `importlib` calls targeting Beancount across application source code. | Static analysis AST visitor (`BeancountAndFloatAstScanner`) scanning all `.py` files under `src/ironledger/`. | **PASS**: Exactly 0 occurrences of direct, aliased, dynamic, or `getattr` Beancount imports across `src/ironledger/`. |
| **2. Pure Integer Rational Arithmetic** | Zero floating-point representation in valuation, minor-unit conversions, Beancount price formatting, or schema columns. | Integer rational math (`//`, `divmod`, `math.gcd`), integer Banker's half-even tie-breaking rounding, and AST `ast.Div` scanner. | **PASS**: Validated in `tests/test_valuation.py` and `tests/test_phase8_exit_contract.py`. |
| **3. Bi-Directional Lineage & Cycle Prevention** | Complete forward and backward provenance DAG traversal within tenant boundaries with strict rejection of cycles and self-edges. | SQLite recursive CTE queries in `LineageExplorer`, edge validation in `LineageDAG`, and `CHECK (source_node_id != target_node_id)`. | **PASS**: Validated in `tests/test_lineage.py` and `tests/test_phase8_exit_contract.py`. |
| **4. Strict Tenant Boundary Isolation** | Complete logical and filesystem isolation across multi-entity ledger tenants. No cross-tenant staging, locking, or FK linkage. | Schema `0010_multi_ledger_rbac.sql` composite keys, `PRAGMA foreign_keys = ON`, `validate_and_resolve_ledger_root` path traversal guards. | **PASS**: Validated in `tests/test_multi_ledger.py` and `tests/test_phase8_exit_contract.py`. |
| **5. Deterministic Dual-Fingerprint Replay** | Every committed mutation verifies projection state and plaintext manifest hash; replaying from genesis reproduces bit-for-bit identical state. | Append-only `mutation_payloads` table, SHA-256 Merkle chain, external HMAC-SHA256 trust anchors, and in-memory dual playback. | **PASS**: Validated in `tests/test_replay.py` and `tests/test_phase8_exit_contract.py`. |
| **6. Scoped Capability Tokens & RBAC** | Cryptographic bearer tokens enforced by role ceilings (`READER`, `OPERATOR`, `COMPILER`, `ADMIN`) and tenant boundary checks. | `PolicyEnforcer.authorize`, constant-time HMAC hash comparison, SQLite `capability_tokens` schema constraints. | **PASS**: Validated in `tests/test_capabilities.py` and `tests/test_phase8_exit_contract.py`. |

---

## 3. Comprehensive test suite summary

All test metrics were executed live against local `HEAD` on 2026-09-11.

### 3.1 Overall test metrics

- **Toolchain**: Python 3.14.6, pytest 9.1.1, SQLite 3.50.4.
- **Total Test Count**: **865 passed, 5 skipped in 28.65s** (100% pass rate).
- **Regression Impact**: Zero regressions across existing Phases 1 through 7.
- **Skipped Tests**: 5 pre-existing environmental skips (missing `bean-check` binary on default PATH, Windows symlink traversal privilege, and three platform-specific MCP contracts).

### 3.2 Phase 8 module test coverage

| Test Suite | Module Under Test | Tests | Status | Key Coverage |
|---|---|---|---|---|
| `tests/test_valuation.py` | `src/ironledger/valuation/` | 27 | PASS | Integer rational conversion, mixed precision scales (0 to 18), exact Banker's half-even rounding, bounded preceding price resolution, inverse quote resolution, zero float drift formatting. |
| `tests/test_lineage.py` | `src/ironledger/lineage/` | 16 | PASS | Bi-directional DAG traversal (upstream/downstream), recursive CTE performance, self-edge rejection, cycle detection, tenant boundary isolation. |
| `tests/test_multi_ledger.py` | `src/ironledger/ledger/` | 10 | PASS | Multi-tenant catalog, path traversal and symlink escape rejection, storage root deduplication, independent compile lockfiles, consolidated balance sheet aggregation. |
| `tests/test_tenant_isolation.py` | `src/ironledger/ledger/isolation.py` | 19 | PASS | Deterministic HMAC-SHA256 tenant salt and key derivation, filesystem isolation jail, boundary assertions. |
| `tests/test_replay.py` | `src/ironledger/replay/`, `src/ironledger/manifests.py` | 9 | PASS | Dual-fingerprint replay (SQLite projection + Beancount filesystem manifest), Merkle chain verification, HMAC-SHA256 trust anchor validation, crash recovery state machine, tamper rejection. |
| `tests/test_capabilities.py` | `src/ironledger/auth/` | 9 | PASS | 71-char `il_cap_` token generation, role ceilings (`READER`, `OPERATOR`, `COMPILER`, `ADMIN`), global vs tenant-scoped tokens, token revocation, expiration checks, malformed/invalid token rejection. |
| `tests/test_rbac.py` | `src/ironledger/rbac/` | 5 | PASS | Scoped capability token minting, HMAC signature verification, expiration checks, hierarchical capability matching, execution guard middleware. |
| `tests/test_phase8_exit_contract.py` | Full Phase 8 Acceptance & AST Scanner | 3 | PASS | AST symbol scanner verifying zero Beancount imports and zero float division across `src/ironledger/`, scanner positive/negative fixtures, and end-to-end integration across all subsystems. |

---

## 4. Traceability matrix (Tasks 8.1 through 8.6)

| Task | Title | Core Artifacts | Verification Suite | Commit | Status |
|---|---|---|---|---|---|
| **8.1** | Multi-Asset Valuation Engine & Price Directives Cache | `0008_price_history.sql`, `src/ironledger/valuation/` | `tests/test_valuation.py` | `d3274bd`, `79221ae` | Complete |
| **8.2** | Ledger Lineage Explorer & Bi-Directional Provenance DAG | `0009_ledger_lineage.sql`, `src/ironledger/lineage/` | `tests/test_lineage.py` | `bf83f70`, `fe3b0ca` | Complete |
| **8.3** | Multi-Ledger Topology & Isolated Staging Queues | `0010_multi_ledger_rbac.sql`, `src/ironledger/ledger/` | `tests/test_multi_ledger.py` | `bd07567`, `e8f3286`, `c039cc1` | Complete |
| **8.4** | Deterministic Audit Replay & Outbox Point-in-Time Engine | `0011_mutation_payloads.sql`, `src/ironledger/replay/`, `src/ironledger/manifests.py` | `tests/test_replay.py` | `523914a`, `b7c1a7a`, `1f04b05` | Complete |
| **8.5** | Scoped Capability Tokens & RBAC Policy Enforcement | `src/ironledger/auth/` | `tests/test_capabilities.py` | `HEAD` | Complete |
| **8.6** | Acceptance Regression Suite & Phase 8 Exit Evidence | `tests/test_phase8_exit_contract.py`, `docs/meta/phases/ironledger-phase-8-evidence.md` | `tests/test_phase8_exit_contract.py`, full test suite (`pytest -q`) | `HEAD` | Complete |

---

## 5. Architectural compliance checklist

1. **Transaction Isolation**: All schema migrations, mutation appends, and tenant catalog modifications acquire locks via `BEGIN IMMEDIATE` and enforce `PRAGMA foreign_keys = ON;`.
2. **Deterministic Canonical Serialization**: Mutation payloads serialize using sorted keys, no whitespace separators, and explicit ASCII encoding prior to SHA-256 payload hashing and HMAC authority signing.
3. **External Trust Anchors**: Every mutation promotion generates an external `.trust_anchor.json` committing `(seq, mutation_id, mutation_hash, manifest_hash, projection_hash, authority_signature)` outside SQLite.
4. **Crash-Safe Outbox Promotion**: Startup reconciliation handles `PRE_COMMIT`, `COMMITTED_PRE_SWAP`, and `SWAPPED` states using `.promotion_journal.json` to guarantee consistency across database and filesystem.
5. **Decoupled Architecture**: Zero Beancount Python imports across all runtime code; Beancount price directives formatted using pure integer Banker's rounding.
6. **Multi-Tenant Security**: Path resolution strictly prevents directory traversal, symlink escapes, and storage root collisions; capability tokens restrict operations to granted scopes and tenant boundaries.
