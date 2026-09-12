# IronLedger Project Status

## Active Goal
Execute Phase 9: Connector Governance & Enterprise Deployment Pipeline (C:\dev\IronLedger).

## Milestone Status: Gate 1 Approved -> In Execution
- **Specification Approval:** Codex CLI reviewed and verified `docs/meta/specs/ironledger-phase-9-spec.md` (mirrored to `docs/superpowers/specs/2026-09-11-phase-9-connector-governance-deployment-design.md`).
- **Implementation Plan:** Completed and committed to `docs/superpowers/plans/2026-09-11-phase-9-implementation-plan.md`.

## Subsystem Tasks
1. **Task 9.1:** Multi-Protocol Connector Governance & Ingestion Rate Limiter (`0012_connectors_governance.sql`, `src/ironledger/connectors/`, `tests/test_connectors.py`) — **COMPLETED** (9 tests passing, token bucket rate limiter, 3-state circuit breaker with backoff, Plaid/SimpleFIN/OFX adapters, registry dispatch)
2. **Task 9.2:** Secret Management, Hardware Token / HSM & Envelope Encryption (`src/ironledger/security/`, `tests/test_envelope_encryption.py`) — **NEXT**
3. **Task 9.3:** Real-Time Webhook Dispatcher & Event Notification Fabric (`src/ironledger/events/`, `tests/test_webhooks.py`) — **PLANNED**
4. **Task 9.4:** Enterprise Deployment Pipeline & Container Infrastructure (`deploy/`, `Dockerfile`, `src/ironledger/web/routers/health.py`) — **PLANNED**
5. **Task 9.5:** System Observability & Prometheus Metrics Exporter (`src/ironledger/observability/`, `src/ironledger/web/routers/metrics.py`, `tests/test_observability.py`) — **PLANNED**
6. **Task 9.6:** Acceptance Regression Suite & Phase 9 Exit Evidence (`tests/test_phase9_exit_contract.py`, `docs/meta/phases/ironledger-phase-9-evidence.md`) — **PLANNED** (874 tests passing, zero regressions, AST verified)

## Key Architecture & Invariants Locked
- Integer-based token bucket rate limiter ($C, r, \tau$) and 3-state circuit breaker with exponential backoff and jitter.
- Pure rational integer calculations with zero floating-point drift across all scales.
- Zero runtime import beancount guarded by static AST analysis.
- Composite primary and foreign keys for multi-tenant database isolation (`PRIMARY KEY(ledger_id, id)` and `FOREIGN KEY(ledger_id, parent_id)`).
- Envelope encryption (AES-256-GCM) with distinct DEK and Payload IVs/tags.
- Append-only `event_outbox` with triggers, per-subscription delivery tracking, worker leases, and HMAC anti-replay signatures.
- Distroless container deployment with non-root security context (`USER 10001:10001`).

## Next Action
Begin Task 9.2: Secret Management, Hardware Token / HSM & Envelope Encryption (`src/ironledger/security/envelope.py`, `key_provider.py`, `scrubbing.py`, and `tests/test_envelope_encryption.py`).


