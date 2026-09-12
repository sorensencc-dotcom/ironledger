-- Migration 0014: Multi-Tenant Federation, Peer Cluster Nodes, and Fenced Outbox

-- 1. Federation Tenants Registry
CREATE TABLE IF NOT EXISTS federation_tenants (
    tenant_id TEXT PRIMARY KEY CHECK(length(tenant_id) >= 1 AND length(tenant_id) <= 64),
    name TEXT NOT NULL CHECK(length(name) >= 1 AND length(name) <= 128),
    default_ledger_id TEXT DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE SET NULL ON UPDATE CASCADE,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

INSERT OR IGNORE INTO federation_tenants (tenant_id, name, default_ledger_id) VALUES ('default', 'Default Tenant', 'default');

-- 2. Peer Cluster Nodes
CREATE TABLE IF NOT EXISTS federation_cluster_nodes (
    node_id TEXT PRIMARY KEY CHECK(length(node_id) >= 1 AND length(node_id) <= 64),
    cluster_id TEXT NOT NULL CHECK(length(cluster_id) >= 1 AND length(cluster_id) <= 64),
    endpoint_url TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('PRIMARY', 'REPLICA', 'WITNESS')),
    last_heartbeat_utc TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

-- 3. Fenced Federated Event Outbox
CREATE TABLE IF NOT EXISTS federated_event_outbox (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE CHECK(length(event_id) >= 16),
    tenant_id TEXT NOT NULL REFERENCES federation_tenants(tenant_id) ON DELETE CASCADE,
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('INFO', 'WARN', 'ERROR', 'CRITICAL')),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json) = 1),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) = 1),
    published_to_peers INTEGER NOT NULL DEFAULT 0 CHECK(published_to_peers IN (0, 1)),
    lease_owner_id TEXT,
    lease_fence_token TEXT,
    lease_expires_at_utc TEXT,
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_federated_outbox_unpub ON federated_event_outbox(published_to_peers, seq);
CREATE INDEX IF NOT EXISTS idx_federated_outbox_lease ON federated_event_outbox(lease_expires_at_utc);

CREATE TRIGGER IF NOT EXISTS federated_outbox_no_delete
BEFORE DELETE ON federated_event_outbox
BEGIN
    SELECT RAISE(ABORT, 'federated_event_outbox is append-only: DELETE is forbidden');
END;

-- 4. Peer Ingestion Idempotency Registry
CREATE TABLE IF NOT EXISTS peer_ingested_events (
    cluster_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    PRIMARY KEY (cluster_id, event_id)
) STRICT;
