-- Migration 0013: Compliance Audit Bundles, Governance Logs, Nonces, and Fenced Leases

-- 1. Compliance Audit Archive Bundles
CREATE TABLE IF NOT EXISTS compliance_audit_bundles (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    bundle_id TEXT NOT NULL,
    framework TEXT NOT NULL CHECK(framework IN ('SOC2_TYPE2', 'ISO27001', 'SOX', 'CUSTOM')),
    period_start_utc TEXT NOT NULL,
    period_end_utc TEXT NOT NULL,
    merkle_root_hex TEXT NOT NULL CHECK(length(merkle_root_hex) = 64),
    sealed_archive_sha256 TEXT NOT NULL CHECK(length(sealed_archive_sha256) = 64),
    record_count INTEGER NOT NULL CHECK(record_count >= 0),
    manifest_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(manifest_json) = 1),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    PRIMARY KEY (ledger_id, bundle_id)
) STRICT;

-- 2. Append-Only Governance Audit Events Table
CREATE TABLE IF NOT EXISTS governance_audit_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    before_state_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(before_state_json) = 1),
    after_state_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(after_state_json) = 1),
    envelope_hash TEXT NOT NULL CHECK(length(envelope_hash) = 64),
    timestamp_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

CREATE TRIGGER IF NOT EXISTS governance_audit_no_update
BEFORE UPDATE ON governance_audit_events
BEGIN
    SELECT RAISE(ABORT, 'governance_audit_events is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS governance_audit_no_delete
BEFORE DELETE ON governance_audit_events
BEGIN
    SELECT RAISE(ABORT, 'governance_audit_events is append-only: DELETE is forbidden');
END;

-- 3. Idempotency & Anti-Replay Registry Table
CREATE TABLE IF NOT EXISTS governance_nonce_registry (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    scope TEXT NOT NULL,
    request_hash TEXT NOT NULL CHECK(length(request_hash) = 64),
    response_status INTEGER,
    response_body_json TEXT,
    issued_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    expires_at_utc TEXT NOT NULL,
    PRIMARY KEY (ledger_id, idempotency_key)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_nonce_expiry ON governance_nonce_registry(expires_at_utc);

-- 4. Persistent Connector Circuit Breakers Table
CREATE TABLE IF NOT EXISTS connector_circuit_breakers (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL REFERENCES connector_providers(provider_id) ON DELETE RESTRICT,
    state TEXT NOT NULL DEFAULT 'CLOSED' CHECK(state IN ('CLOSED', 'OPEN', 'HALF_OPEN')),
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK(failure_count >= 0),
    last_failure_utc TEXT,
    opened_at_utc TEXT,
    half_open_probes INTEGER NOT NULL DEFAULT 0 CHECK(half_open_probes >= 0),
    updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    PRIMARY KEY (ledger_id, provider_id)
) STRICT;

-- 5. Anomaly & Fraud Detection Flags Table
CREATE TABLE IF NOT EXISTS anomaly_flags (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    flag_id TEXT NOT NULL,
    staged_transaction_id TEXT,
    rule_type TEXT NOT NULL CHECK(rule_type IN ('DUPLICATE_CHARGE', 'VELOCITY_SPIKE', 'RATIONAL_OUTLIER', 'UNUSUAL_PAYEE')),
    severity TEXT NOT NULL CHECK(severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    score_numerator INTEGER NOT NULL,
    score_denominator INTEGER NOT NULL CHECK(score_denominator > 0),
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json) = 1),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    resolved_at_utc TEXT,
    resolution_status TEXT CHECK(resolution_status IN ('DISMISSED', 'CONFIRMED_FRAUD', 'RESOLVED_VALID')),
    PRIMARY KEY (ledger_id, flag_id)
) STRICT;
