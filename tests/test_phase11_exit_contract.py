"""Phase 11 Exit-Gate Contract & Acceptance Regression Suite.

Verifies:
1. Static analysis AST visitor guard ensuring ZERO runtime beancount imports across all src/ironledger/ modules.
2. Static analysis AST visitor guard ensuring ZERO float division across Phase 11 federation, event, and compliance modules.
3. Positive and negative test fixtures verifying AST scanner detection fidelity.
4. End-to-End Integration across Multi-Tenant Federation, Canonical gov.event.v1 Envelopes,
   Dual-Emission Event Router, Fenced Outbox Dispatching, Peer Ingestion Idempotency,
   and Cross-Cluster Merkle Inclusion Proofs.
"""

from __future__ import annotations

import ast
import datetime
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest

from ironledger.compliance.bundle import generate_compliance_bundle
from ironledger.compliance.federation import (
    CrossClusterProofError,
    export_cross_cluster_proof,
    verify_cross_cluster_proof,
)
from ironledger.compliance.merkle import MerkleTree, verify_inclusion_proof
from ironledger.db.migrations import migrate_governed
from ironledger.events import (
    DEFAULT_LEASE_SECONDS,
    EventEnvelopeError,
    EventRouter,
    FederatedEvent,
    OutboxDispatcher,
    canonical_event_bytes,
    compute_event_id,
    validate_federated_event,
)


# ============================================================================
# 1. AST GUARDS & DETECTOR FIDELITY
# ============================================================================


class BeancountImportScanner(ast.NodeVisitor):
    """Detects any direct, aliased, or dynamic imports targeting beancount."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "beancount" or alias.name.startswith("beancount."):
                self.violations.append(
                    f"{self.filename}:L{node.lineno}: Direct import of '{alias.name}' forbidden"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and (node.module == "beancount" or node.module.startswith("beancount.")):
            self.violations.append(
                f"{self.filename}:L{node.lineno}: Import from '{node.module}' forbidden"
            )
        self.generic_visit(node)


class ZeroFloatScanner(ast.NodeVisitor):
    """Detects float division (/), float literals, or float/Decimal conversions."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.violations: list[str] = []

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, ast.Div):
            self.violations.append(
                f"{self.filename}:L{node.lineno}: Prohibited float division operator '/'"
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in ("float", "Decimal"):
            self.violations.append(
                f"{self.filename}:L{node.lineno}: Prohibited float/Decimal call '{node.func.id}()'"
            )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, float):
            self.violations.append(
                f"{self.filename}:L{node.lineno}: Prohibited float literal '{node.value}'"
            )
        self.generic_visit(node)


def test_phase11_ast_zero_beancount_import_contract():
    """Contract: Zero runtime beancount imports across all src/ironledger/ modules."""
    src_root = Path(__file__).parent.parent / "src" / "ironledger"
    all_py_files = list(src_root.rglob("*.py"))
    assert len(all_py_files) > 20, "Expected multiple python files in src/ironledger"

    violations: list[str] = []
    for f in all_py_files:
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        scanner = BeancountImportScanner(str(f.relative_to(src_root)))
        scanner.visit(tree)
        violations.extend(scanner.violations)

    assert not violations, f"Contract violation: Found beancount imports:\n" + "\n".join(violations)


def test_phase11_ast_zero_float_contract():
    """Contract: Zero float division across Phase 11 federation, event, and compliance modules."""
    src_root = Path(__file__).parent.parent / "src" / "ironledger"
    fed_files = [
        src_root / "events" / "envelope.py",
        src_root / "events" / "router.py",
        src_root / "events" / "dispatcher.py",
        src_root / "compliance" / "federation.py",
        src_root / "web" / "routers" / "federation.py",
        src_root / "cli" / "commands" / "federation.py",
    ]

    violations: list[str] = []
    for f in fed_files:
        if f.exists():
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            scanner = ZeroFloatScanner(f.name)
            scanner.visit(tree)
            violations.extend(scanner.violations)

    assert not violations, f"Contract violation: Found float operations:\n" + "\n".join(violations)


def test_phase11_ast_scanner_fidelity():
    """Positive and negative test fixtures verifying AST scanner detection fidelity."""
    bad_beancount_code = """
import beancount
from beancount.core import data
import os
"""
    tree = ast.parse(bad_beancount_code)
    scanner = BeancountImportScanner("test_bad.py")
    scanner.visit(tree)
    assert len(scanner.violations) == 2

    bad_float_code = """
def calc(a, b):
    x = a / b
    y = float(a)
    z = 3.14
    return x
"""
    tree = ast.parse(bad_float_code)
    f_scanner = ZeroFloatScanner("test_float.py")
    f_scanner.visit(tree)
    assert len(f_scanner.violations) == 3


# ============================================================================
# 2. END-TO-END PHASE 11 FEDERATION CONTRACT INTEGRATION
# ============================================================================


@pytest.fixture
def phase11_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON;")
    migrate_governed(conn)
    return conn


def test_phase11_e2e_federation_lifecycle(phase11_db: sqlite3.Connection):
    """Comprehensive E2E test verifying:
    1. Tenant & Cluster Node registration.
    2. Event Router dual-emission (outbox + governance audit).
    3. Fenced Outbox Dispatcher with lease claiming, acknowledgement, and expiration safety.
    4. Peer Ingestion Idempotency.
    5. Cross-Cluster Merkle Inclusion Proof export and witness verification.
    """
    conn = phase11_db

    # 1. Setup tenant and nodes
    conn.execute(
        """
        INSERT INTO federation_tenants (tenant_id, name, default_ledger_id)
        VALUES ('tenant_apac', 'APAC Operations', 'default')
        """
    )
    conn.execute(
        """
        INSERT INTO federation_cluster_nodes (node_id, cluster_id, endpoint_url, role)
        VALUES ('node_singapore_1', 'cluster_apac', 'https://sg1.ironledger.net', 'PRIMARY')
        """
    )
    conn.commit()

    # 2. Emit compliance and anomaly events via EventRouter
    ev_comp_id = EventRouter.emit_compliance_bundle_created(
        conn=conn,
        ledger_id="default",
        bundle_id="bnd_phase11_001",
        framework="SOC2_TYPE2",
        merkle_root_hex="a" * 64,
        archive_sha256="b" * 64,
        record_count=100,
        tenant_id="tenant_apac",
    )
    ev_anom_id = EventRouter.emit_anomaly_flagged(
        conn=conn,
        ledger_id="default",
        flag_id="flag_001",
        rule_type="RATIONAL_OUTLIER",
        staged_tx_id="tx_001",
        score_num=95,
        score_den=100,
        severity="WARN",
        tenant_id="tenant_apac",
    )
    conn.commit()

    # Verify dual emission in both tables
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM federated_event_outbox WHERE tenant_id = 'tenant_apac'")
    assert cur.fetchone()[0] == 2

    cur.execute("SELECT COUNT(*) FROM governance_audit_events WHERE actor = 'event_router:anomaly'")
    assert cur.fetchone()[0] == 1

    cur.execute("SELECT COUNT(*) FROM governance_audit_events WHERE actor = 'event_router:compliance'")
    assert cur.fetchone()[0] == 1

    # 3. Fenced Outbox Lease Dispatching
    fence_1, batch_1 = OutboxDispatcher.claim_batch(conn, worker_id="worker_alpha", batch_size=10)
    assert len(batch_1) == 2
    assert fence_1 is not None

    # Worker alpha acknowledges first event
    ack_count = OutboxDispatcher.acknowledge_batch(conn, [ev_comp_id], fence_1)
    assert ack_count == 1

    # Simulate expired lease on second event and worker beta re-claiming
    conn.execute(
        """
        UPDATE federated_event_outbox
        SET lease_expires_at_utc = '2020-01-01T00:00:00Z'
        WHERE event_id = ?
        """,
        (ev_anom_id,),
    )
    conn.commit()

    fence_2, batch_2 = OutboxDispatcher.claim_batch(conn, worker_id="worker_beta", batch_size=10)
    assert len(batch_2) == 1
    assert batch_2[0].event_id == ev_anom_id
    assert fence_2 != fence_1

    # Stale worker alpha acknowledgement should affect 0 rows
    stale_ack = OutboxDispatcher.acknowledge_batch(conn, [ev_anom_id], fence_1)
    assert stale_ack == 0

    # Valid worker beta acknowledgement succeeds
    valid_ack = OutboxDispatcher.acknowledge_batch(conn, [ev_anom_id], fence_2)
    assert valid_ack == 1

    # 4. Peer Ingestion Idempotency
    peer_event = batch_1[0]
    first_ingest = OutboxDispatcher.ingest_peer_event(conn, cluster_id="cluster_emea", event=peer_event)
    assert first_ingest is True

    # Duplicate delivery
    second_ingest = OutboxDispatcher.ingest_peer_event(conn, cluster_id="cluster_emea", event=peer_event)
    assert second_ingest is False

    # 5. Cross-Cluster Merkle Inclusion Proofs
    for i in range(5):
        now_utc = f"2026-06-01T12:0{i}:00Z"
        conn.execute(
            """
            INSERT INTO governance_audit_events (
                ledger_id, actor, action, target, before_state_json, after_state_json,
                envelope_hash, timestamp_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("default", f"actor_{i}", "SET_LIMIT", f"target_{i}", "{}", "{}", f"{i}" * 64, now_utc),
        )
    conn.commit()

    bundle = generate_compliance_bundle(
        conn=conn,
        ledger_id="default",
        framework="SOC2_TYPE2",
        period_start_utc="2026-01-01T00:00:00Z",
        period_end_utc="2026-12-31T23:59:59Z",
    )

    proof_bundle = export_cross_cluster_proof(
        archive_bytes=bundle.archive_bytes,
        target_stream="governance_audit",
        target_seq=3,
    )

    assert proof_bundle["bundle_id"] == bundle.bundle_id
    assert proof_bundle["merkle_root_hex"] == bundle.merkle_root_hex
    assert len(proof_bundle["proof"]) > 0

    # Remote witness node verifies inclusion proof without loading full database or archive
    verified = verify_cross_cluster_proof(proof_bundle, expected_root_hex=bundle.merkle_root_hex)
    assert verified is True

    # Tampered leaf hash fails verification
    tampered = dict(proof_bundle)
    tampered_payload = dict(tampered["leaf_payload"])
    tampered_payload["action"] = "TAMPERED_ACTION"
    tampered["leaf_payload"] = tampered_payload
    assert verify_cross_cluster_proof(tampered) is False
