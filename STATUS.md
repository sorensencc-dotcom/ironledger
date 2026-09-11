# IronLedger Project Status

## Active Goal
Execute Phase 8: Multi-Asset Valuation, Ledger Lineage & Audit Replay (C:\dev\IronLedger).

## Milestone Status: Gate 1 Approved (Pass 19) -> Execution Complete
- **Specification Approval:** Codex CLI Pass 19 issued **VERDICT: APPROVE** on docs/superpowers/specs/2026-09-10-phase-8-lineage-valuation-replay-design.md (byte-identical to docs/meta/specs/ironledger-phase-8-spec.md).
- **Implementation Plan:** Completed and committed to docs/superpowers/plans/2026-09-10-phase-8-implementation-plan.md.

## Subsystem Tasks
1. **Task 8.1:** Multi-Asset Valuation Engine & Price Directives Cache (0008_price_history.sql, src/ironledger/valuation/, tests/test_valuation.py) — **COMPLETED** (27 tests passing, 0 float drift, AST verified)
2. **Task 8.2:** Ledger Lineage Explorer & Bi-Directional Provenance DAG (0009_ledger_lineage.sql, src/ironledger/lineage/, tests/test_lineage.py) — **COMPLETED** (16 tests passing, CTE bi-directional traversal, insertion-time cycle detection)
3. **Task 8.3:** Multi-Ledger Topology & Isolated Staging Queues (0010_multi_ledger_rbac.sql Part 1, src/ironledger/ledger/, tests/test_multi_ledger.py) — **COMPLETED** (10 tests passing, cross-process tenant compile locks, path traversal defense, consolidated reporting)
4. **Task 8.4:** Deterministic Audit Replay & Outbox Point-in-Time Engine (0011_mutation_payloads.sql, src/ironledger/replay/, src/ironledger/manifests.py, tests/test_replay.py) — **COMPLETED** (9 tests passing, Merkle chain validation, HMAC trust anchors, point-in-time time travel, crash recovery)
5. **Task 8.5:** Scoped Capability Tokens & RBAC Policy Enforcement (0010_multi_ledger_rbac.sql Part 2, src/ironledger/rbac/, src/ironledger/auth/, tests/test_rbac.py, tests/test_capabilities.py) — **COMPLETED** (14 tests passing, 71-char `il_cap_` tokens, HMAC signed tokens, role matrices, tenant scoping, revocation, expiration)
6. **Task 8.6:** Multi-Tenant Ledger Isolation & Cryptographic Boundary Verification (src/ironledger/ledger/isolation.py, tests/test_tenant_isolation.py) — **COMPLETED** (19 tests passing, deterministic HMAC-SHA256 key/salt derivation, filesystem jail, boundary assertions)
7. **Task 8.7:** Acceptance Regression Suite & Phase 8 Exit Evidence (tests/test_phase8_exit_contract.py, docs/meta/phases/ironledger-phase-8-evidence.md) — **COMPLETED** (863 tests passing, zero regressions, AST zero-beancount and zero-float verified)

## Key Architecture & Invariants Locked
- Exact rational integer arithmetic with zero floating-point drift and pure integer Banker's half-even rounding across all scales.
- Zero runtime import beancount guarded by static AST analysis.
- Composite primary and foreign keys for multi-tenant database isolation (PRIMARY KEY(ledger_id, id) and FOREIGN KEY(ledger_id, parent_id)).
- Deterministic HMAC-SHA256 tenant salts and ledger-scoped authority keys.
- Path traversal and symlink refusal along the full directory hierarchy.
- Merkle mutation hash chain + Authority Signatures + external out-of-band trust anchors.
- Crash-atomic promotion with .promotion_journal.json state machine (PRE_COMMIT -> COMMITTED_PRE_SWAP -> SWAPPED).
- Cryptographic capability tokens with role ceilings (`READER`, `OPERATOR`, `COMPILER`, `ADMIN`) and HMAC signature verification.

## Next Action
Phase 8 execution complete. Request Phase 8 Gate 2 review and sign-off.

