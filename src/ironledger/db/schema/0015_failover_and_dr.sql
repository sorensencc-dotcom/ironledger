-- Migration 0015: Failover Leases, WAL Replication Checkpoints & Key Rotations

-- 1. Cluster Leader Leases (Fenced Primary Election)
CREATE TABLE IF NOT EXISTS cluster_leader_leases (
    cluster_id TEXT PRIMARY KEY CHECK(length(cluster_id) >= 1 AND length(cluster_id) <= 64),
    term INTEGER NOT NULL DEFAULT 1 CHECK(term >= 1),
    leader_node_id TEXT NOT NULL REFERENCES federation_cluster_nodes(node_id) ON DELETE RESTRICT,
    lease_fence_token TEXT NOT NULL UNIQUE CHECK(length(lease_fence_token) >= 16),
    lease_acquired_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    lease_expires_at_utc TEXT NOT NULL
) STRICT;

-- 2. WAL Replication Checkpoints (Cross-Region Frame Tracking)
CREATE TABLE IF NOT EXISTS replication_wal_checkpoints (
    checkpoint_id TEXT PRIMARY KEY CHECK(length(checkpoint_id) >= 16),
    cluster_id TEXT NOT NULL,
    node_id TEXT NOT NULL REFERENCES federation_cluster_nodes(node_id) ON DELETE RESTRICT,
    wal_offset_bytes INTEGER NOT NULL CHECK(wal_offset_bytes >= 0),
    frame_count INTEGER NOT NULL CHECK(frame_count >= 0),
    salt1 INTEGER NOT NULL,
    salt2 INTEGER NOT NULL,
    checkpoint_sha256 TEXT NOT NULL CHECK(length(checkpoint_sha256) = 64),
    synced_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_wal_checkpoints_node ON replication_wal_checkpoints(cluster_id, node_id, wal_offset_bytes);

-- 3. Tenant Key Rotations (Cryptographic Re-Key Audit)
CREATE TABLE IF NOT EXISTS tenant_key_rotations (
    rotation_id TEXT PRIMARY KEY CHECK(length(rotation_id) >= 16),
    tenant_id TEXT NOT NULL REFERENCES federation_tenants(tenant_id) ON DELETE RESTRICT,
    kek_key_id TEXT NOT NULL,
    previous_kek_key_id TEXT,
    rewrapped_count INTEGER NOT NULL DEFAULT 0 CHECK(rewrapped_count >= 0),
    status TEXT NOT NULL CHECK(status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED')),
    rotated_by TEXT NOT NULL,
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    completed_at_utc TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_tenant_key_rotations ON tenant_key_rotations(tenant_id, created_at_utc);
