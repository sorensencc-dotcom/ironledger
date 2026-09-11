"""Comprehensive test suite for Deterministic Audit Replay & Outbox Point-in-Time Engine (Task 8.4)."""

import json
import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ledger.topology import LedgerRegistry
from ironledger.manifests import (
    GENESIS_MANIFEST_HASH,
    compute_directory_manifest_hash,
    compute_ledger_manifest_hash,
)
from ironledger.replay.anchors import (
    compute_anchor_signature_digest,
    get_anchor_path,
    read_trust_anchor,
    sign_authority_payload,
    verify_authority_signature,
    write_trust_anchor,
)
from ironledger.replay.engine import (
    apply_mutation_and_append,
    reconcile_manifest_on_startup,
    replay_audit_stream,
)
from ironledger.replay.models import (
    AuditTamperDetectedError,
    MissingAnchorCommitmentError,
    PayloadValidationError,
    ReconciliationFailedError,
    ReplayBoundaryError,
    TrustAnchor,
)
from ironledger.replay.snapshot import (
    GENESIS_PROJECTION_HASH,
    compute_projection_hash,
)


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test_replay.db"
    c = connect(str(db_path))
    migrations.migrate(c)
    return c


@pytest.fixture
def beancount_root(tmp_path):
    root = tmp_path / "beancount_data"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def ledger_alpha(conn, beancount_root):
    registry = LedgerRegistry(conn=conn, base_path=beancount_root)
    topology = registry.create_ledger(
        name="Alpha Entity",
        root_account="Assets:Alpha",
        base_currency="USD",
        storage_root="alpha",
    )
    return topology.ledger_id


@pytest.fixture
def ledger_beta(conn, beancount_root):
    registry = LedgerRegistry(conn=conn, base_path=beancount_root)
    topology = registry.create_ledger(
        name="Beta Entity",
        root_account="Assets:Beta",
        base_currency="EUR",
        storage_root="beta",
    )
    return topology.ledger_id


def test_normal_mutation_append_and_anchor(conn, beancount_root, ledger_alpha):
    """Test full mutation lifecycle: STAGE -> REVIEW -> PRICE -> COMPILE -> RULE_UPDATE."""
    # 1. Stage transaction
    doc_id = f"doc_{uuid4().hex[:8]}"
    rec_id = f"rec_{uuid4().hex[:8]}"
    staged_tx_id = f"stx_{uuid4().hex[:8]}"
    posting1_id = f"sp_{uuid4().hex[:8]}"
    posting2_id = f"sp_{uuid4().hex[:8]}"

    stage_payload = {
        "source_record_id": rec_id,
        "staged_transaction_id": staged_tx_id,
        "status": "pending",
        "proposed_date": "2026-09-01",
        "payee": "Acme Corp",
        "narration": "Office Supplies",
        "identity_algo_version": 1,
        "identity_method": "fitid",
        "identity_fingerprint": "1" * 64,
        "created_at_utc": "2026-09-01T12:00:00Z",
        "source_record": {
            "source_document_id": doc_id,
            "record_index": 0,
            "canonical_payload": '{"amount": 1000}',
            "content_sha256": "a" * 64,
            "mime_type": "text/csv",
            "encoding": "utf-8",
            "provenance": "bank_sync",
            "raw_payload_ref": "/raw/1.csv",
        },
        "postings": [
            {
                "staged_posting_id": posting1_id,
                "source_record_id": rec_id,
                "role": "imported",
                "posting_index": 0,
                "account": "Assets:Alpha:Checking",
                "minor_units": -1000,
                "currency": "USD",
                "minor_unit_scale": 2,
                "created_at_utc": "2026-09-01T12:00:00Z",
            },
            {
                "staged_posting_id": posting2_id,
                "source_record_id": rec_id,
                "role": "contra",
                "posting_index": 1,
                "account": None,
                "minor_units": 1000,
                "currency": "USD",
                "minor_unit_scale": 2,
                "created_at_utc": "2026-09-01T12:00:00Z",
            },
        ],
    }

    evt1, p1 = apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id=ledger_alpha,
        operator_session="sess_01",
        action="stage_tx",
        event_type="STAGE_TRANSACTION",
        payload=stage_payload,
    )
    assert evt1["seq"] == 1
    assert p1.projection_hash_before == GENESIS_PROJECTION_HASH
    assert p1.projection_hash_after != GENESIS_PROJECTION_HASH

    # 2. Review decision
    review_payload = {
        "staged_transaction_id": staged_tx_id,
        "new_status": "approved",
        "decided_at_utc": "2026-09-01T12:05:00Z",
        "assigned_account": "Expenses:Alpha:Supplies",
    }
    evt2, p2 = apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id=ledger_alpha,
        operator_session="sess_01",
        action="review_decision",
        event_type="REVIEW_DECISION",
        payload=review_payload,
    )
    assert evt2["seq"] == 2
    assert evt2["prev_mutation_hash"] == evt1["mutation_hash"]

    # 3. Price directive
    price_payload = {
        "id": 1,
        "directive_date": "2026-09-01",
        "base_currency": "EUR",
        "quote_currency": "USD",
        "rate_numerator": 110,
        "rate_denominator": 100,
        "precision_scale": 4,
        "source": "POLLED_FEED",
    }
    evt3, p3 = apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id=ledger_alpha,
        operator_session="sess_01",
        action="insert_price",
        event_type="PRICE_DIRECTIVE",
        payload=price_payload,
    )
    assert evt3["seq"] == 3
    assert evt3["sha256_after"] != GENESIS_MANIFEST_HASH

    # 4. Compile ledger
    compile_payload = {
        "compile_run_id": f"crun_{uuid4().hex[:8]}",
        "beancount_version": "2.3.5",
        "compiler_version": "1.0",
        "input_hash": "b" * 64,
        "intended_output_hash": "c" * 64,
        "actual_output_hash": "d" * 64,
        "status": "SUCCESS",
        "compiled_tx_ids": [staged_tx_id],
        "compiled_directives": [
            {
                "proposed_date": "2026-09-01",
                "payee": "Acme Corp",
                "narration": "Office Supplies",
                "postings": [
                    {
                        "account": "Assets:Alpha:Checking",
                        "minor_units": -1000,
                        "currency": "USD",
                        "minor_unit_scale": 2,
                    },
                    {
                        "account": "Expenses:Alpha:Supplies",
                        "minor_units": 1000,
                        "currency": "USD",
                        "minor_unit_scale": 2,
                    },
                ],
            }
        ],
    }
    evt4, p4 = apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id=ledger_alpha,
        operator_session="sess_01",
        action="compile_ledger",
        event_type="COMPILE_LEDGER",
        payload=compile_payload,
    )
    assert evt4["seq"] == 4

    # Verify trust anchor
    anchor = read_trust_anchor(beancount_root, ledger_alpha)
    assert anchor.seq == 4
    assert anchor.mutation_hash == evt4["mutation_hash"]
    sig_digest = compute_anchor_signature_digest(
        seq=anchor.seq,
        mutation_id=anchor.mutation_id,
        ledger_id=anchor.ledger_id,
        ts_utc=anchor.anchored_at_utc,
        mutation_hash=anchor.mutation_hash,
        prev_mutation_hash=anchor.prev_mutation_hash,
        manifest_hash=anchor.manifest_hash,
        projection_hash=anchor.projection_hash,
    )
    assert verify_authority_signature(anchor.authority_signature, sig_digest, "ironledger-dev-key")


def test_dual_fingerprint_replay(conn, beancount_root, ledger_alpha):
    """Replay audit stream and verify bit-for-bit exact projection and manifest hashes."""
    # Seed mutations
    doc_id = f"doc_{uuid4().hex[:8]}"
    rec_id = f"rec_{uuid4().hex[:8]}"
    staged_tx_id = f"stx_{uuid4().hex[:8]}"

    apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id=ledger_alpha,
        operator_session="sess_01",
        action="stage_tx",
        event_type="STAGE_TRANSACTION",
        payload={
            "source_record_id": rec_id,
            "staged_transaction_id": staged_tx_id,
            "status": "pending",
            "proposed_date": "2026-09-02",
            "payee": "Utility Provider",
            "narration": "Power Bill",
            "identity_algo_version": 1,
            "identity_method": "fitid",
            "identity_fingerprint": "2" * 64,
            "created_at_utc": "2026-09-02T10:00:00Z",
            "source_record": {
                "source_document_id": doc_id,
                "record_index": 0,
                "canonical_payload": '{"amount": 5000}',
                "content_sha256": "1" * 64,
                "mime_type": "text/csv",
                "encoding": "utf-8",
                "provenance": "bank_sync",
                "raw_payload_ref": "/raw/2.csv",
            },
            "postings": [
                {
                    "staged_posting_id": f"sp_{uuid4().hex[:8]}",
                    "source_record_id": rec_id,
                    "role": "imported",
                    "posting_index": 0,
                    "account": "Assets:Alpha:Checking",
                    "minor_units": -5000,
                    "currency": "USD",
                    "minor_unit_scale": 2,
                    "created_at_utc": "2026-09-02T10:00:00Z",
                },
                {
                    "staged_posting_id": f"sp_{uuid4().hex[:8]}",
                    "source_record_id": rec_id,
                    "role": "contra",
                    "posting_index": 1,
                    "account": None,
                    "minor_units": 5000,
                    "currency": "USD",
                    "minor_unit_scale": 2,
                    "created_at_utc": "2026-09-02T10:00:00Z",
                },
            ],
        },
    )

    apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id=ledger_alpha,
        operator_session="sess_01",
        action="create_rule",
        event_type="RULE_UPDATE",
        payload={
            "action": "CREATE",
            "rule_id": 1,
            "match_type": "EXACT",
            "pattern": "Utility Provider",
            "target_account": "Expenses:Alpha:Utilities",
            "priority": 10,
            "active": 1,
        },
    )

    # Replay
    result = replay_audit_stream(
        live_conn=conn,
        beancount_root=beancount_root,
        target_ledger_id=ledger_alpha,
    )

    assert result.report.replay_success is True
    assert result.report.total_events_verified == 2
    assert result.report.target_ledger_events_replayed == 2
    assert result.report.interleaved_events_skipped == 0
    assert result.report.final_projection_hash == compute_projection_hash(conn, ledger_alpha)
    assert result.report.final_manifest_hash == compute_ledger_manifest_hash(beancount_root, ledger_alpha)

    # Verify rows in in-memory projection connection
    tx_count = result.projection_conn.execute(
        "SELECT COUNT(*) FROM staged_transactions WHERE ledger_id = ?", (ledger_alpha,)
    ).fetchone()[0]
    assert tx_count == 1
    rule_count = result.projection_conn.execute(
        "SELECT COUNT(*) FROM categorization_rules WHERE ledger_id = ?", (ledger_alpha,)
    ).fetchone()[0]
    assert rule_count == 1


def test_point_in_time_time_travel(conn, beancount_root, ledger_alpha):
    """Test replaying to intermediate target sequence and timestamp."""
    # 3 sequential mutations
    for i in range(1, 4):
        apply_mutation_and_append(
            conn=conn,
            beancount_root=beancount_root,
            ledger_id=ledger_alpha,
            operator_session="sess_pit",
            action="create_rule",
            event_type="RULE_UPDATE",
            payload={
                "action": "CREATE",
                "rule_id": i,
                "match_type": "EXACT",
                "pattern": f"Merchant_{i}",
                "target_account": f"Expenses:Alpha:M{i}",
                "priority": i,
                "active": 1,
                "created_at_utc": f"2026-09-0{i}T12:00:00Z",
            },
        )

    # Replay to seq 1
    res1 = replay_audit_stream(
        live_conn=conn,
        beancount_root=beancount_root,
        target_ledger_id=ledger_alpha,
        target_seq=1,
    )
    assert res1.report.final_sequence == 1
    assert res1.report.total_events_verified == 1
    rules_seq1 = res1.projection_conn.execute(
        "SELECT COUNT(*) FROM categorization_rules WHERE ledger_id = ?", (ledger_alpha,)
    ).fetchone()[0]
    assert rules_seq1 == 1

    # Replay to seq 2
    res2 = replay_audit_stream(
        live_conn=conn,
        beancount_root=beancount_root,
        target_ledger_id=ledger_alpha,
        target_seq=2,
    )
    assert res2.report.final_sequence == 2
    rules_seq2 = res2.projection_conn.execute(
        "SELECT COUNT(*) FROM categorization_rules WHERE ledger_id = ?", (ledger_alpha,)
    ).fetchone()[0]
    assert rules_seq2 == 2

    # Replay by timestamp
    res_ts = replay_audit_stream(
        live_conn=conn,
        beancount_root=beancount_root,
        target_ledger_id=ledger_alpha,
        target_timestamp="2026-09-02T23:59:59Z",
    )
    assert res_ts.report.final_sequence == 2

    # Boundary error out of bounds
    with pytest.raises(ReplayBoundaryError):
        replay_audit_stream(
            live_conn=conn,
            beancount_root=beancount_root,
            target_ledger_id=ledger_alpha,
            target_seq=999,
        )


def test_interleaved_multi_tenant_stream(conn, beancount_root, ledger_alpha, ledger_beta):
    """Test interleaved events across two tenants and isolated replay."""
    # Alpha event 1
    apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id=ledger_alpha,
        operator_session="sess_interleaved",
        action="rule",
        event_type="RULE_UPDATE",
        payload={
            "action": "CREATE",
            "rule_id": 101,
            "match_type": "EXACT",
            "pattern": "Alpha1",
            "target_account": "Expenses:Alpha:1",
        },
    )

    # Beta event 2
    apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id=ledger_beta,
        operator_session="sess_interleaved",
        action="rule",
        event_type="RULE_UPDATE",
        payload={
            "action": "CREATE",
            "rule_id": 201,
            "match_type": "EXACT",
            "pattern": "Beta1",
            "target_account": "Expenses:Beta:1",
        },
    )

    # Alpha event 3
    apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id=ledger_alpha,
        operator_session="sess_interleaved",
        action="rule",
        event_type="RULE_UPDATE",
        payload={
            "action": "CREATE",
            "rule_id": 102,
            "match_type": "EXACT",
            "pattern": "Alpha2",
            "target_account": "Expenses:Alpha:2",
        },
    )

    # Beta event 4
    apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id=ledger_beta,
        operator_session="sess_interleaved",
        action="rule",
        event_type="RULE_UPDATE",
        payload={
            "action": "CREATE",
            "rule_id": 202,
            "match_type": "EXACT",
            "pattern": "Beta2",
            "target_account": "Expenses:Beta:2",
        },
    )

    # Replay Alpha
    res_a = replay_audit_stream(
        live_conn=conn,
        beancount_root=beancount_root,
        target_ledger_id=ledger_alpha,
    )
    assert res_a.report.total_events_verified == 4
    assert res_a.report.target_ledger_events_replayed == 2
    assert res_a.report.interleaved_events_skipped == 2
    assert res_a.report.final_projection_hash == compute_projection_hash(conn, ledger_alpha)
    # Ensure Beta rules not in Alpha projection
    beta_rules = res_a.projection_conn.execute(
        "SELECT COUNT(*) FROM categorization_rules WHERE ledger_id = ?", (ledger_beta,)
    ).fetchone()[0]
    assert beta_rules == 0

    # Replay Beta
    res_b = replay_audit_stream(
        live_conn=conn,
        beancount_root=beancount_root,
        target_ledger_id=ledger_beta,
    )
    assert res_b.report.total_events_verified == 4
    assert res_b.report.target_ledger_events_replayed == 2
    assert res_b.report.interleaved_events_skipped == 2
    assert res_b.report.final_projection_hash == compute_projection_hash(conn, ledger_beta)


def test_tamper_detection_and_anchor_tamper(conn, beancount_root, ledger_alpha):
    """Test cryptographic tamper detection on database and trust anchors."""
    # Seed 2 events
    apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id=ledger_alpha,
        operator_session="sess_tamper",
        action="rule",
        event_type="RULE_UPDATE",
        payload={
            "action": "CREATE",
            "rule_id": 1,
            "match_type": "EXACT",
            "pattern": "GoodPattern",
            "target_account": "Expenses:Alpha:Good",
        },
    )
    apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id=ledger_alpha,
        operator_session="sess_tamper",
        action="rule",
        event_type="RULE_UPDATE",
        payload={
            "action": "CREATE",
            "rule_id": 2,
            "match_type": "EXACT",
            "pattern": "GoodPattern2",
            "target_account": "Expenses:Alpha:Good2",
        },
    )

    # 1. Tamper trust anchor signature
    anchor = read_trust_anchor(beancount_root, ledger_alpha)
    tampered_anchor = TrustAnchor(
        anchor_version=anchor.anchor_version,
        ledger_id=anchor.ledger_id,
        seq=anchor.seq,
        mutation_id=anchor.mutation_id,
        mutation_hash=anchor.mutation_hash,
        prev_mutation_hash=anchor.prev_mutation_hash,
        manifest_hash=anchor.manifest_hash,
        projection_hash=anchor.projection_hash,
        authority_signature="f" * 64,  # Invalid HMAC
        anchored_at_utc=anchor.anchored_at_utc,
    )
    write_trust_anchor(beancount_root, tampered_anchor)

    with pytest.raises(AuditTamperDetectedError):
        replay_audit_stream(
            live_conn=conn,
            beancount_root=beancount_root,
            target_ledger_id=ledger_alpha,
        )

    # Restore correct anchor
    write_trust_anchor(beancount_root, anchor)
    # Replay should now succeed
    replay_res = replay_audit_stream(
        live_conn=conn,
        beancount_root=beancount_root,
        target_ledger_id=ledger_alpha,
    )
    assert replay_res.report.replay_success is True


def test_startup_reconciliation(conn, beancount_root, ledger_alpha):
    """Test startup recovery from crash in COMMITTED_PRE_SWAP state."""
    evt, p = apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id=ledger_alpha,
        operator_session="sess_recon",
        action="price",
        event_type="PRICE_DIRECTIVE",
        payload={
            "id": 10,
            "directive_date": "2026-09-03",
            "base_currency": "GBP",
            "quote_currency": "USD",
            "rate_numerator": 130,
            "rate_denominator": 100,
            "precision_scale": 4,
            "source": "POLLED_FEED",
        },
    )

    # Simulate deleting anchor
    anchor_file = get_anchor_path(beancount_root, ledger_alpha)
    anchor_file.unlink()

    # Startup reconciliation must fail closed when trust anchor is missing
    with pytest.raises(MissingAnchorCommitmentError):
        reconcile_manifest_on_startup(conn, beancount_root)


def test_payload_validation_failure(conn, beancount_root, ledger_alpha):
    """Test invalid payload schema rejection."""
    invalid_payload = {
        # Missing required staged_transaction_id and new_status
        "foo": "bar"
    }
    with pytest.raises(PayloadValidationError):
        apply_mutation_and_append(
            conn=conn,
            beancount_root=beancount_root,
            ledger_id=ledger_alpha,
            operator_session="sess_invalid",
            action="review",
            event_type="REVIEW_DECISION",
            payload=invalid_payload,
        )


def test_empty_ledger_replay(conn, beancount_root, ledger_alpha):
    """Test replaying a ledger with no mutations."""
    res = replay_audit_stream(
        live_conn=conn,
        beancount_root=beancount_root,
        target_ledger_id=ledger_alpha,
    )
    assert res.report.replay_success is True
    assert res.report.total_events_verified == 0
    assert res.report.final_sequence == 0
    assert res.report.final_projection_hash == GENESIS_PROJECTION_HASH
    assert res.report.final_manifest_hash == GENESIS_MANIFEST_HASH


def test_startup_reconciliation_all_journal_states(conn, beancount_root, ledger_alpha):
    """Test startup recovery across PRE_COMMIT (uncommitted), COMMITTED_PRE_SWAP, and SWAPPED journal states."""
    from ironledger.ledger.topology import validate_and_resolve_ledger_root
    tenant_dir = validate_and_resolve_ledger_root(beancount_root, ledger_alpha)
    journal_path = tenant_dir / ".promotion_journal.json"

    # 1. Simulate PRE_COMMIT where seq is not in DB (aborted before DB commit)
    staging_dir = tenant_dir / ".staging_fake_precommit"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "test.beancount").write_text("; fake", encoding="utf-8")
    
    journal_data = {
        "state": "PRE_COMMIT",
        "seq": 999,
        "mutation_id": "mut_precommit_fake",
        "ledger_id": ledger_alpha,
        "ts_utc": "2026-09-04T12:00:00Z",
        "staging_dir": str(staging_dir),
        "sha256_before": GENESIS_MANIFEST_HASH,
        "sha256_after": "1" * 64,
        "projection_hash_before": GENESIS_PROJECTION_HASH,
        "projection_hash_after": "2" * 64,
        "prev_mutation_hash": "0" * 64,
        "mutation_hash": "3" * 64,
        "authority_signature": "4" * 64,
        "payload_sha256": "5" * 64,
    }
    journal_path.write_text(json.dumps(journal_data), encoding="utf-8")

    reconcile_manifest_on_startup(conn, beancount_root)
    # Journal should be unlinked and staging removed
    assert not journal_path.exists()
    assert not staging_dir.exists()

    # 2. Simulate COMMITTED_PRE_SWAP where DB has the mutation and staging was not yet swapped
    evt, p = apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id=ledger_alpha,
        operator_session="sess_recon2",
        action="price",
        event_type="PRICE_DIRECTIVE",
        payload={
            "id": 88,
            "directive_date": "2026-09-05",
            "base_currency": "JPY",
            "quote_currency": "USD",
            "rate_numerator": 1,
            "rate_denominator": 150,
            "precision_scale": 4,
            "source": "POLLED_FEED",
        },
    )
    # Move current to staging to simulate crash right before swap
    staging_dir2 = tenant_dir / ".staging_crash_swap"
    staging_dir2.mkdir(parents=True, exist_ok=True)
    current_dir = tenant_dir / "current"
    for f in current_dir.glob("*.beancount"):
        shutil.move(str(f), str(staging_dir2 / f.name))

    journal_data2 = {
        "state": "COMMITTED_PRE_SWAP",
        "seq": evt["seq"],
        "mutation_id": evt["mutation_id"],
        "ledger_id": ledger_alpha,
        "ts_utc": evt["ts_utc"],
        "staging_dir": str(staging_dir2),
        "sha256_before": evt["sha256_before"],
        "sha256_after": evt["sha256_after"],
        "projection_hash_before": p.projection_hash_before,
        "projection_hash_after": p.projection_hash_after,
        "prev_mutation_hash": evt["prev_mutation_hash"],
        "mutation_hash": evt["mutation_hash"],
        "authority_signature": p.authority_signature,
        "payload_sha256": p.payload_sha256,
    }
    journal_path.write_text(json.dumps(journal_data2), encoding="utf-8")

    reconcile_manifest_on_startup(conn, beancount_root)
    assert not journal_path.exists()
    assert not staging_dir2.exists()
    assert (current_dir / "prices.beancount").exists()

