# IronLedger Phase 9: Connector Governance & Enterprise Deployment Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Phase 9 of IronLedger: Connector Governance & Enterprise Deployment Pipeline with multi-protocol financial connectors, token-bucket rate limiting, circuit breaker protection, envelope secret encryption (AES-256-GCM), transactional event outbox, HMAC webhook delivery fabric with worker leases and anti-replay guards, containerized deployment infrastructure, and Prometheus observability.

**Architecture:** Forward-only SQLite migration `0012_connectors_governance.sql` with STRICT tables, composite tenant foreign keys, append-only triggers on outbox events, and separate IV/auth-tag storage for envelope encryption. Subsystems are structured in modular packages: `ironledger.connectors`, `ironledger.security`, `ironledger.events`, and `ironledger.observability`.

**Tech Stack:** Python 3.12+, SQLite 3 (STRICT mode, foreign keys ON), cryptography (AES-256-GCM, HMAC-SHA256), Pydantic v2, FastAPI, pytest.

## Global Constraints

- **Exact Rational Integer Arithmetic:** Token bucket rate limiting, refills, wait durations, and interval math operate strictly with integer math and rational proportions ($N / D$). Zero float drift.
- **Zero Runtime `import beancount`:** Plaintext Beancount emission remains purely string-templated and AST-audited.
- **Tenant Domain Isolation:** Relational composite primary keys `PRIMARY KEY(ledger_id, id)` and composite foreign keys `FOREIGN KEY(ledger_id, parent_id) REFERENCES parent(ledger_id, parent_id)` with `PRAGMA foreign_keys = ON;`.
- **Envelope Encryption Invariants:** AES-256-GCM with separate Data Encryption Key (DEK) and Payload IVs and authentication tags. Zero plaintext in storage; zero secrets in logs/exceptions.
- **Outbox Immutability & Replay Protection:** Immutable `event_outbox` protected by SQLite triggers; dedicated `webhook_deliveries` with worker leases; HMAC-SHA256 signatures with timestamp freshness and delivery deduplication.

---

## Proposed Changes & Tasks

- [ ] ### Task 9.1: Multi-Protocol Connector Governance & Ingestion Rate Limiter
  - **Files:**
    - `src/ironledger/db/schema/0012_connectors_governance.sql` (Part 1: `connector_providers`, `connector_sync_runs`)
    - `src/ironledger/db/schema/__init__.py`
    - `src/ironledger/connectors/__init__.py`
    - `src/ironledger/connectors/models.py`
    - `src/ironledger/connectors/base.py`
    - `src/ironledger/connectors/rate_limiter.py`
    - `src/ironledger/connectors/circuit_breaker.py`
    - `src/ironledger/connectors/registry.py`
    - `src/ironledger/connectors/plaid.py`
    - `src/ironledger/connectors/simplefin.py`
    - `src/ironledger/connectors/ofx.py`
    - `tests/test_connectors.py`
  - **Deliverables:** Abstract connector interface, token-bucket rate limiter, 3-state circuit breaker with exponential backoff and jitter, dynamic registry dispatcher, Plaid/SimpleFIN/OFX adapters, and test suite.

- [ ] ### Task 9.2: Secret Management, Hardware Token / HSM & Envelope Encryption
  - **Files:**
    - `src/ironledger/db/schema/0012_connectors_governance.sql` (Part 2: `connector_credentials`)
    - `src/ironledger/security/envelope.py`
    - `src/ironledger/security/key_provider.py`
    - `src/ironledger/security/scrubbing.py`
    - `tests/test_envelope_encryption.py`
  - **Deliverables:** AES-256-GCM envelope encryption with distinct IVs and tags for DEK wrapping and payload encryption, Environment / Windows DPAPI key providers, regex secret scrubbing, and key rotation.

- [ ] ### Task 9.3: Real-Time Webhook Dispatcher & Event Notification Fabric
  - **Files:**
    - `src/ironledger/db/schema/0012_connectors_governance.sql` (Part 3: `webhook_subscriptions`, `event_outbox`, `webhook_deliveries`, `webhook_delivery_dlq`)
    - `src/ironledger/events/__init__.py`
    - `src/ironledger/events/models.py`
    - `src/ironledger/events/outbox.py`
    - `src/ironledger/events/dispatcher.py`
    - `src/ironledger/events/signer.py`
    - `src/ironledger/events/reconciliation.py`
    - `tests/test_webhooks.py`
  - **Deliverables:** Append-only outbox with SQLite triggers, per-subscription deliveries, worker lease claiming with startup lease reconciliation, HMAC-SHA256 signature generator, anti-replay verification, and DLQ routing.

- [ ] ### Task 9.4: Enterprise Deployment Pipeline & Container Infrastructure
  - **Files:**
    - `Dockerfile`
    - `deploy/docker-compose.yml`
    - `src/ironledger/web/routers/health.py`
    - `src/ironledger/web/app.py`
  - **Deliverables:** Multi-stage distroless/minimal non-root container image (`USER 10001:10001`), `/healthz` and `/readyz` endpoints, and startup migration automation.

- [ ] ### Task 9.5: System Observability & Prometheus Metrics Exporter
  - **Files:**
    - `src/ironledger/observability/__init__.py`
    - `src/ironledger/observability/metrics.py`
    - `src/ironledger/observability/middleware.py`
    - `src/ironledger/observability/logging.py`
    - `src/ironledger/web/routers/metrics.py`
    - `tests/test_observability.py`
  - **Deliverables:** Pure-Python Prometheus/OpenMetrics formatted registry, ASGI request metrics middleware, structured JSON log formatter with secret scrubber, and `/metrics` route.

- [ ] ### Task 9.6: Acceptance Regression Suite & Phase 9 Exit Evidence
  - **Files:**
    - `tests/test_phase9_exit_contract.py`
    - `docs/meta/phases/ironledger-phase-9-evidence.md`
    - `STATUS.md`
  - **Deliverables:** Full end-to-end integration test across connectors, envelope encryption, webhooks, metrics, AST zero-beancount and zero-float verification, and sealed Phase 9 exit evidence document.
