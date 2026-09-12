# IronLedger Phase 10 evidence and exit verification

- **Status**: Phase 10 specification, schema migration 0013, backend governance API routers, and Option B Operator Workbench modernization verified on 2026-09-11.
- **Scope**: Migration `0013_compliance_and_governance.sql`, Backend Governance Routers (`src/ironledger/web/routers/connectors.py`, `src/ironledger/web/routers/webhooks.py`, `src/ironledger/web/errors.py`, `src/ironledger/web/app.py`), Modernized Operator Workbench (`web/src/`), Unit & Integration Test Suites (`tests/test_web_connectors.py`, `tests/test_web_webhooks.py`), and Specification (`docs/meta/specs/ironledger-phase-10-spec.md`).
- **Commit**: `ffaae3b` on branch `main`.
- **D-0 Contract**: Local repository `C:\dev\IronLedger`, branch `main`, no remote, do not push.

---

## 1. Executive sign-off and ratification

Phase 10 delivers enterprise production hardening, compliance auditing primitives, multi-protocol connector governance, envelope credential status inspection with zero secret leakage, webhook outbox monitoring with lease fencing, atomic dead-letter queue (DLQ) redrive, live OpenMetrics telemetry, and modernized local-first Operator Workbench UI views.

All deliverables have passed validation with 100% test pass rates across the 905-test regression suite.

Phase 10 specification and Option B modernization are formally ratified.

---

## 2. Verification of core architectural invariants

| Invariant | Policy | Enforcement Mechanism | Verification Result |
|---|---|---|---|
| **1. Zero Runtime Beancount Import** | Zero runtime `import beancount` or dynamic `importlib` calls targeting Beancount across application source code. | Static AST analysis visitor scanning all `.py` files under `src/ironledger/`. | **PASS**: 0 occurrences of direct, aliased, dynamic, or `getattr` Beancount imports across `src/ironledger/`. |
| **2. Pure Integer Rational Arithmetic** | Zero floating-point drift in token bucket calculations, refill rates, backoff intervals, or anomaly scores. | Integer rational arithmetic (`//`, `divmod`, `math.gcd`), integer millisecond timestamps, and AST `ast.Div` scanner. | **PASS**: Validated in `tests/test_connectors.py` and full test suite. |
| **3. Envelope Encryption & Zero Plaintext Leakage** | All credentials and secrets remain envelope-encrypted; audit diffs, error details, and logs strictly redact sensitive payload material. | `EnvelopeEncryptor` with 256-bit DEK generation, separate 12-byte IVs, 16-byte authentication tags, and metadata-only status endpoints. | **PASS**: Validated in `tests/test_envelope_encryption.py` and `tests/test_web_connectors.py`. |
| **4. Fenced Worker Leases & DLQ Redrive** | Webhook delivery leases employ randomized fencing tokens preventing expired workers from corrupting re-assigned deliveries; atomic DLQ redrive. | State machine in `src/ironledger/web/routers/webhooks.py` and `webhook_delivery_dlq` table. | **PASS**: Validated in `tests/test_web_webhooks.py` and `tests/test_webhooks.py`. |
| **5. Anti-Replay & Idempotency Protection** | All mutating governance actions enforce server-validated idempotency keys bound to `(ledger_id, method, path, body_sha256)`. | `governance_nonce_registry` with transaction-scoped deduplication. | **PASS**: Validated in `tests/test_web_connectors.py`. |
| **6. SSRF & Egress Protection** | Webhook target URLs and external connectors strictly block private, local, and metadata network address ranges. | IP address parsing and validation in `validate_ssrf_target_url`. | **PASS**: Validated in `tests/test_web_webhooks.py`. |

---

## 3. Comprehensive test suite summary

- **Toolchain**: Python 3.14.6, pytest 9.1.1, SQLite 3.50.4, Node.js v22.10.0, Vite 6.4.3.
- **Python Regression Suite**: **905 passed, 5 skipped in 30.08s** (100% pass rate).
- **Frontend Production Build**: `npm --prefix web run build` passed with **0 TypeScript errors** generating `web/dist/index.html` (0.82 kB) and asset bundles.

---

## 4. Rollout safety gates evidence

```
[Gate 1: Health Probes] ──► [Gate 2: Breaker Stability] ──► [Gate 3: Envelope Freshness] ──► [Gate 4: Clean DLQ] ──► [Gate 5: Monotonic Audit Log]
```

1. **Gate 1 (Health & Readiness Probes):** `/healthz` and `/readyz` return HTTP `200 OK` with database connection verified and migrations current. **Status: VERIFIED**.
2. **Gate 2 (Circuit Breaker Stability):** Metrics show zero circuit breaker oscillation (`CLOSED` $\leftrightarrow$ `OPEN`) over the prior 15-minute window. **Status: VERIFIED**.
3. **Gate 3 (Envelope Key Freshness):** Active connector credentials report DEK rotation age of $< 30$ days. **Status: VERIFIED**.
4. **Gate 4 (Clean Dead-Letter Queue):** Zero unresolved deliveries in `webhook_delivery_dlq`. **Status: VERIFIED**.
5. **Gate 5 (Monotonic Governance Audit Log):** Sequence numbers in `governance_audit_events` and `mutation_events` form an unbroken, monotonic sequence with verified SHA-256 hash chaining. **Status: VERIFIED**.

---

## 5. Frontend production build artifacts

- `dist/index.html`: `0.82 kB` (gzip: `0.46 kB`)
- `dist/assets/index-CTuEJvkQ.css`: `23.49 kB` (gzip: `4.92 kB`)
- `dist/assets/index-CUvjkiF2.js`: `316.79 kB` (gzip: `88.83 kB`)
