"""Tests for Phase 11 multi-tenant federation, event router, fenced outbox, and cross-cluster proofs."""

from __future__ import annotations

import ast
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ironledger.compliance.bundle import generate_compliance_bundle
from ironledger.compliance.federation import (
    CrossClusterProofError,
    export_cross_cluster_proof,
    verify_cross_cluster_proof,
)
from ironledger.events.dispatcher import OutboxDispatcher
from ironledger.events.envelope import (
    EventEnvelopeError,
    FederatedEvent,
    canonical_event_bytes,
    validate_federated_event,
)
from ironledger.events.router import EventRouter
from ironledger.governance.migrations import migrate_governed


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test_federation.db"
    connection = sqlite3.connect(db_path)
    migrate_governed(connection, db_path)
    connection.execute(
        "INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency) VALUES ('led_fed', 'Federated Ledger', 'USD')"
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def test_ast_zero_float_drift_enforcement():
    """Verify strictly zero float division (/) and zero float conversions in federation & events modules."""
    events_dir = Path(__file__).resolve().parent.parent / "src" / "ironledger" / "events"
    compliance_fed_file = Path(__file__).resolve().parent.parent / "src" / "ironledger" / "compliance" / "federation.py"

    files_to_scan = list(events_dir.glob("*.py")) + [compliance_fed_file]

    class FloatAstScanner(ast.NodeVisitor):
        def __init__(self, filename: str):
            self.filename = filename
            self.violations: list[str] = []

        def visit_BinOp(self, node: ast.BinOp):
            if isinstance(node.op, ast.Div):
                self.violations.append(f"{self.filename}:L{node.lineno}: Prohibited float division operator '/'")
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ("float", "Decimal"):
                self.violations.append(f"{self.filename}:L{node.lineno}: Prohibited float/Decimal call '{node.func.id}()'")
            self.generic_visit(node)

        def visit_Constant(self, node: ast.Constant):
            if isinstance(node.value, float):
                self.violations.append(f"{self.filename}:L{node.lineno}: Prohibited float literal '{node.value}'")
            self.generic_visit(node)

    for f in files_to_scan:
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        scanner = FloatAstScanner(f.name)
        scanner.visit(tree)
        assert not scanner.violations, f"Float violations found in {f.name}: {scanner.violations}"


def test_migration_0014_tables_and_triggers(conn: sqlite3.Connection):
    # Check default tenant
    cursor = conn.cursor()
    cursor.execute("SELECT tenant_id, name FROM federation_tenants WHERE tenant_id = 'default'")
    row = cursor.fetchone()
    assert row is not None
    assert row[1] == "Default Tenant"

    # Test outbox trigger blocks DELETE
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """
        INSERT INTO federated_event_outbox (
            event_id, tenant_id, ledger_id, event_type, source, severity, payload_json, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("ev_immut_00000001", "default", "led_fed", "SYSTEM_ALERT", "system", "INFO", "{}", now_utc),
    )

    conn.commit()

    with pytest.raises((sqlite3.IntegrityError, sqlite3.DatabaseError, sqlite3.OperationalError), match="DELETE is forbidden"):
        conn.execute("DELETE FROM federated_event_outbox WHERE event_id = 'ev_immut_00000001'")


def test_event_router_and_envelope_validation(conn: sqlite3.Connection):
    # Compliance bundle created event
    ev_id = EventRouter.emit_compliance_bundle_created(
        conn=conn,
        ledger_id="led_fed",
        bundle_id="bnd_123",
        framework="SOC2_TYPE2",
        merkle_root_hex="0" * 64,
        archive_sha256="1" * 64,
        record_count=42,
    )
    conn.commit()
    assert len(ev_id) >= 16

    # Verify presence in outbox
    cursor = conn.cursor()
    cursor.execute(
        "SELECT event_type, source, published_to_peers FROM federated_event_outbox WHERE event_id = ?",
        (ev_id,),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "COMPLIANCE_BUNDLE_CREATED"
    assert row[1] == "compliance"
    assert row[2] == 0

    # Verify mirrored in governance_audit_events
    cursor.execute(
        "SELECT action, target FROM governance_audit_events WHERE target = ?",
        (f"event:{ev_id}",),
    )
    gov_row = cursor.fetchone()
    assert gov_row is not None
    assert gov_row[0] == "COMPLIANCE_BUNDLE_CREATED"


def test_outbox_dispatcher_fenced_leasing(conn: sqlite3.Connection):
    # Emit two events
    ev1 = EventRouter.emit_anomaly_flagged(
        conn=conn,
        ledger_id="led_fed",
        flag_id="flag_1",
        rule_type="DUPLICATE_CHARGE",
        staged_tx_id="tx_1",
        score_num=1,
        score_den=1,
    )
    ev2 = EventRouter.emit_replication_advanced(
        conn=conn,
        ledger_id="led_fed",
        wal_magic="0x377f0682",
        frame_index=10,
        commit_page_count=100,
    )
    conn.commit()

    # Worker 1 claims batch
    fence_1, claimed = OutboxDispatcher.claim_batch(conn, worker_id="worker_1", batch_size=10, lease_seconds=60)
    conn.commit()
    assert len(claimed) >= 2
    assert fence_1 is not None

    # Stale worker trying to acknowledge with invalid fence token should acknowledge 0 rows
    ack_stale = OutboxDispatcher.acknowledge_batch(conn, [ev1, ev2], fence_token="invalid_token")
    conn.commit()
    assert ack_stale == 0

    # Correct worker acknowledges with valid fence token
    ack_valid = OutboxDispatcher.acknowledge_batch(conn, [ev1, ev2], fence_token=fence_1)
    conn.commit()
    assert ack_valid == 2

    # Verify events are marked published
    cursor = conn.cursor()
    cursor.execute(
        "SELECT published_to_peers FROM federated_event_outbox WHERE event_id IN (?, ?)",
        (ev1, ev2),
    )
    for row in cursor.fetchall():
        assert row[0] == 1


def test_peer_event_idempotent_ingestion(conn: sqlite3.Connection):
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    peer_event = FederatedEvent(
        event_id="peer_ev_999",
        event_type="COMPLIANCE_BUNDLE_VERIFIED",
        occurred_at=now_utc,
        recorded_at=now_utc,
        tenant_id="default",
        ledger_id="led_fed",
        source="compliance",
        severity="INFO",
        payload={"bundle_id": "bnd_remote", "status": "VERIFIED"},
    )

    # First ingestion succeeds
    res1 = OutboxDispatcher.ingest_peer_event(conn, cluster_id="cluster_eu", event=peer_event)
    conn.commit()
    assert res1 is True

    # Duplicate ingestion from same cluster returns False
    res2 = OutboxDispatcher.ingest_peer_event(conn, cluster_id="cluster_eu", event=peer_event)
    conn.commit()
    assert res2 is False


def test_cross_cluster_audit_proofs(conn: sqlite3.Connection):
    # Insert events into governance audit log
    for i in range(5):
        now_utc = f"2026-06-01T12:0{i}:00Z"
        conn.execute(
            """
            INSERT INTO governance_audit_events (
                ledger_id, actor, action, target, before_state_json, after_state_json,
                envelope_hash, timestamp_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("led_fed", f"actor_{i}", "SET_LIMIT", f"target_{i}", "{}", "{}", f"{i}" * 64, now_utc),
        )
    conn.commit()

    # Generate bundle
    bundle = generate_compliance_bundle(
        conn=conn,
        ledger_id="led_fed",
        framework="SOC2_TYPE2",
        period_start_utc="2026-01-01T00:00:00Z",
        period_end_utc="2026-12-31T23:59:59Z",
    )

    # Export cross-cluster inclusion proof for event sequence 3
    proof_bundle = export_cross_cluster_proof(
        archive_bytes=bundle.archive_bytes,
        target_stream="governance_audit",
        target_seq=3,
    )

    assert proof_bundle["bundle_id"] == bundle.bundle_id
    assert proof_bundle["merkle_root_hex"] == bundle.merkle_root_hex
    assert len(proof_bundle["proof"]) > 0

    # Verify proof independently
    is_valid = verify_cross_cluster_proof(proof_bundle, expected_root_hex=bundle.merkle_root_hex)
    assert is_valid is True

    # Tampered leaf fails verification
    tampered = dict(proof_bundle)
    tampered_payload = dict(tampered["leaf_payload"])
    tampered_payload["action"] = "TAMPERED_ACTION"
    tampered["leaf_payload"] = tampered_payload

    assert verify_cross_cluster_proof(tampered) is False
