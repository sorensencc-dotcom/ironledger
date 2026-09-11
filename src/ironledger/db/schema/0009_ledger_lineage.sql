-- Migration 0009: Ledger Lineage Explorer & Bi-Directional Provenance DAG

CREATE TABLE IF NOT EXISTS lineage_nodes (
    ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    node_id TEXT NOT NULL CHECK(length(node_id) >= 1 AND length(node_id) <= 64 AND node_id NOT GLOB '*[^a-zA-Z0-9_-]*'),
    node_type TEXT NOT NULL CHECK(node_type IN ('EVIDENCE_BLOB', 'SOURCE_RECORD', 'STAGED_TX', 'POSTING', 'PRICE_DIRECTIVE', 'EVIDENCE')),
    entity_ref TEXT NOT NULL CHECK(length(entity_ref) >= 1 AND length(entity_ref) <= 128),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) = 1),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    PRIMARY KEY(ledger_id, node_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_lineage_nodes_entity ON lineage_nodes(ledger_id, entity_ref);

CREATE TABLE IF NOT EXISTS lineage_edges (
    ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    source_node_id TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    relationship TEXT NOT NULL CHECK(relationship IN ('EXTRACTED_FROM', 'STAGED_FROM', 'COMPILED_FROM', 'DERIVED_FROM', 'COMPILED_INTO', 'VALUED_BY')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    CHECK(source_node_id != target_node_id),
    PRIMARY KEY(ledger_id, source_node_id, target_node_id, relationship),
    FOREIGN KEY(ledger_id, source_node_id) REFERENCES lineage_nodes(ledger_id, node_id) ON DELETE CASCADE,
    FOREIGN KEY(ledger_id, target_node_id) REFERENCES lineage_nodes(ledger_id, node_id) ON DELETE CASCADE
) STRICT;

CREATE INDEX IF NOT EXISTS idx_lineage_edges_forward ON lineage_edges(ledger_id, source_node_id);
CREATE INDEX IF NOT EXISTS idx_lineage_edges_backward ON lineage_edges(ledger_id, target_node_id);
