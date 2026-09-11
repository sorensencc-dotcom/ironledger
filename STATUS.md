# IronLedger Project Status

## Active Goal
Execute Phase 8: Multi-Asset Valuation, Ledger Lineage & Audit Replay (C:\dev\IronLedger).

## Milestone Status: Gate 1 Approved (Pass 19) -> In Execution
- **Specification Approval:** Codex CLI Pass 19 issued **VERDICT: APPROVE** on docs/superpowers/specs/2026-09-10-phase-8-lineage-valuation-replay-design.md (byte-identical to docs/meta/specs/ironledger-phase-8-spec.md).
- **Implementation Plan:** Completed and committed to docs/superpowers/plans/2026-09-10-phase-8-implementation-plan.md.

## Subsystem Tasks
1. **Task 8.1:** Multi-Asset Valuation Engine & Price Directives Cache (0008_price_history.sql, src/ironledger/valuation/, tests/test_valuation.py) — **COMPLETED** (54 tests passing, 0 float drift, AST verified)
2. **Task 8.2:** Ledger Lineage Explorer & Bi-Directional Provenance DAG (0009_ledger_lineage.sql, src/ironledger/lineage/, tests/test_lineage.py) — **COMPLETED** (13 tests passing, CTE bi-directional traversal, insertion-time cycle detection)
3. **Task 8.3:** Multi-Ledger Topology & Isolated Staging Queues (0010_multi_ledger_rbac.sql Part 1, src/ironledger/ledger/, tests/test_multi_ledger.py) — **COMPLETED** (7 tests passing, cross-process tenant compile locks, path traversal defense, consolidated reporting)
4. **Task 8.4:** Deterministic Audit Replay & Outbox Point-in-Time Engine (0011_mutation_payloads.sql, src/ironledger/replay/, src/ironledger/manifests.py, tests/test_replay.py) — **COMPLETED** (9 tests passing, Merkle chain validation, HMAC trust anchors, point-in-time time travel, crash recovery)
5. **Task 8.5:** Scoped Capability Tokens & RBAC Policy Enforcement (0010_multi_ledger_rbac.sql Part 2, src/ironledger/auth/, tests/test_capabilities.py) — **READY**
6. **Task 8.6:** Acceptance Regression Suite & Phase 8 Exit Evidence (tests/test_phase8_exit_contract.py, docs/meta/phases/ironledger-phase-8-evidence.md)

## Key Architecture & Invariants Locked
- Exact rational integer arithmetic with zero floating-point drift and pure integer Banker's half-even rounding across all scales.
- Zero runtime import beancount guarded by static AST analysis.
- Composite primary and foreign keys for multi-tenant database isolation (PRIMARY KEY(ledger_id, id) and FOREIGN KEY(ledger_id, parent_id)).
- Path traversal and symlink refusal along the full directory hierarchy.
- Merkle mutation hash chain + Authority Signatures + external out-of-band trust anchors (.ironledger/anchors/<ledger_id>.anchor.json).
- Crash-atomic promotion with .promotion_journal.json state machine (PRE_COMMIT -> COMMITTED_PRE_SWAP -> SWAPPED -> FINALIZED).

## Next Action
Start execution of **Task 8.5: Scoped Capability Tokens & RBAC Policy Enforcement**:
1. Implement token generator, HMAC-SHA256 validator, and token hashing.
2. Implement tenant RBAC authorization middleware and permission evaluators (`READER`, `OPERATOR`, `COMPILER`, `ADMIN`).
3. Implement `tests/test_capabilities.py` and verify all tests pass.
