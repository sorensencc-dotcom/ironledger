-- Migration 0012: Connector Governance, Envelope Credentials, Webhook Outbox & DLQ

-- 1. Connector Provider Registry
CREATE TABLE IF NOT EXISTS connector_providers (
    provider_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    protocol_type TEXT NOT NULL CHECK(protocol_type IN ('PLAID', 'SIMPLEFIN', 'OFX', 'REST_JSON')),
    base_url TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    rate_limit_rpm INTEGER NOT NULL DEFAULT 60 CHECK(rate_limit_rpm > 0),
    burst_capacity INTEGER NOT NULL DEFAULT 10 CHECK(burst_capacity > 0),
    config_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(config_json) = 1),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

-- 2. Envelope-Encrypted Connector Credentials
CREATE TABLE IF NOT EXISTS connector_credentials (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    credential_id TEXT NOT NULL,
    provider_id TEXT NOT NULL REFERENCES connector_providers(provider_id) ON DELETE RESTRICT,
    kek_key_id TEXT NOT NULL,
    encrypted_dek_blob BLOB NOT NULL,
    dek_iv_hex TEXT NOT NULL CHECK(length(dek_iv_hex) = 24),
    dek_auth_tag_hex TEXT NOT NULL CHECK(length(dek_auth_tag_hex) = 32),
    encrypted_payload_blob BLOB NOT NULL,
    payload_iv_hex TEXT NOT NULL CHECK(length(payload_iv_hex) = 24),
    payload_auth_tag_hex TEXT NOT NULL CHECK(length(payload_auth_tag_hex) = 32),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    PRIMARY KEY (ledger_id, credential_id),
    UNIQUE (ledger_id, provider_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_connector_credentials_lookup ON connector_credentials(ledger_id, provider_id);

-- 3. Connector Synchronization Execution History
CREATE TABLE IF NOT EXISTS connector_sync_runs (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    provider_id TEXT NOT NULL REFERENCES connector_providers(provider_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'CIRCUIT_BROKEN')),
    records_fetched INTEGER NOT NULL DEFAULT 0 CHECK(records_fetched >= 0),
    records_staged INTEGER NOT NULL DEFAULT 0 CHECK(records_staged >= 0),
    error_code TEXT,
    error_details TEXT,
    started_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    completed_at_utc TEXT,
    PRIMARY KEY (ledger_id, run_id),
    CHECK(completed_at_utc IS NULL OR (completed_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*' AND completed_at_utc NOT GLOB '*[^0-9T:.Z-]*'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_connector_sync_runs_ledger ON connector_sync_runs(ledger_id, started_at_utc);

-- 4. Webhook Subscriptions Registry with Envelope-Encrypted Secrets
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    subscription_id TEXT NOT NULL,
    target_url TEXT NOT NULL CHECK(target_url GLOB 'https://*' OR target_url GLOB 'http://localhost:*' OR target_url GLOB 'http://127.0.0.1:*'),
    kek_key_id TEXT NOT NULL,
    encrypted_dek_blob BLOB NOT NULL,
    dek_iv_hex TEXT NOT NULL CHECK(length(dek_iv_hex) = 24),
    dek_auth_tag_hex TEXT NOT NULL CHECK(length(dek_auth_tag_hex) = 32),
    encrypted_secret_blob BLOB NOT NULL,
    secret_iv_hex TEXT NOT NULL CHECK(length(secret_iv_hex) = 24),
    secret_auth_tag_hex TEXT NOT NULL CHECK(length(secret_auth_tag_hex) = 32),
    secret_fingerprint_hex TEXT NOT NULL CHECK(length(secret_fingerprint_hex) = 64),
    event_types_json TEXT NOT NULL CHECK(json_valid(event_types_json) = 1 AND json_type(event_types_json) = 'array'),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    PRIMARY KEY (ledger_id, subscription_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_ledger ON webhook_subscriptions(ledger_id, is_active);

-- 5. Append-Only Transactional Event Outbox
CREATE TABLE IF NOT EXISTS event_outbox (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json) = 1),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    PRIMARY KEY (ledger_id, event_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_event_outbox_ledger ON event_outbox(ledger_id, created_at_utc);

-- Triggers enforcing immutable event_outbox
CREATE TRIGGER IF NOT EXISTS event_outbox_no_update
BEFORE UPDATE ON event_outbox
BEGIN
    SELECT RAISE(ABORT, 'event_outbox is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS event_outbox_no_delete
BEFORE DELETE ON event_outbox
BEGIN
    SELECT RAISE(ABORT, 'event_outbox is append-only: DELETE is forbidden');
END;

-- 6. Per-Subscription Webhook Delivery State
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    ledger_id TEXT NOT NULL,
    delivery_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'PROCESSING', 'DELIVERED', 'FAILED', 'DEAD_LETTERED')),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
    next_retry_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    leased_by TEXT,
    leased_until_utc TEXT,
    last_status_code INTEGER,
    last_error TEXT,
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    completed_at_utc TEXT,
    PRIMARY KEY (ledger_id, delivery_id),
    FOREIGN KEY (ledger_id, event_id) REFERENCES event_outbox(ledger_id, event_id) ON DELETE CASCADE,
    FOREIGN KEY (ledger_id, subscription_id) REFERENCES webhook_subscriptions(ledger_id, subscription_id) ON DELETE CASCADE,
    UNIQUE (ledger_id, event_id, subscription_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_queue ON webhook_deliveries(status, next_retry_at_utc);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_lease ON webhook_deliveries(status, leased_until_utc);

-- 7. Webhook Delivery Dead-Letter Queue (DLQ) with Strict Composite Tenant Isolation
CREATE TABLE IF NOT EXISTS webhook_delivery_dlq (
    ledger_id TEXT NOT NULL,
    dlq_entry_id TEXT NOT NULL,
    delivery_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    status_code INTEGER,
    last_error TEXT NOT NULL,
    attempt_count INTEGER NOT NULL CHECK(attempt_count >= 0),
    failed_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    PRIMARY KEY (ledger_id, dlq_entry_id),
    FOREIGN KEY (ledger_id, delivery_id) REFERENCES webhook_deliveries(ledger_id, delivery_id) ON DELETE CASCADE,
    FOREIGN KEY (ledger_id, event_id) REFERENCES event_outbox(ledger_id, event_id) ON DELETE CASCADE,
    FOREIGN KEY (ledger_id, subscription_id) REFERENCES webhook_subscriptions(ledger_id, subscription_id) ON DELETE CASCADE
) STRICT;

CREATE INDEX IF NOT EXISTS idx_webhook_dlq_lookup ON webhook_delivery_dlq(ledger_id, subscription_id, failed_at_utc);
