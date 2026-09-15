"""Phase 15 T01: event_evidence and attach_proposals schema."""

from __future__ import annotations

import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


TS = "2026-09-14T18:00:00Z"


def _seed_parents(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, "
        " acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        "VALUES ('doc-a', 'application/pdf', 'utf-8', 'bank/card', ?, "
        " 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
        " 'evidence/source_documents/doc-a', ?)",
        (TS, TS),
    )
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, "
        " canonical_payload, content_sha256, created_at_utc) VALUES "
        "('doc-a:0', 'doc-a', 0, '{}', "
        " 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', ?),"
        "('doc-a:1', 'doc-a', 1, '{}', "
        " 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', ?)",
        (TS, TS),
    )
    fp1 = "1" * 64
    fp2 = "2" * 64
    conn.execute(
        "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, "
        " proposed_date, payee, narration, identity_algo_version, identity_method, "
        " identity_fingerprint, created_at_utc) VALUES "
        "('stx:one', 'doc-a:0', 'pending', '2026-09-01', 'Cafe', '', 1, 'sha256_fallback', ?, ?),"
        "('stx:two', 'doc-a:1', 'pending', '2026-09-01', 'Cafe', '', 1, 'sha256_fallback', ?, ?)",
        (fp1, TS, fp2, TS),
    )


def test_migrate_creates_event_evidence_and_attach_proposals():
    conn = connect(":memory:")
    migrations.migrate(conn)
    names = _tables(conn)
    assert "event_evidence" in names
    assert "attach_proposals" in names


def test_event_evidence_rejects_two_rows_from_same_document_on_same_event():
    conn = connect(":memory:")
    migrations.migrate(conn)
    _seed_parents(conn)
    conn.execute(
        "INSERT INTO event_evidence (evidence_id, staged_transaction_id, source_record_id, "
        " source_document_id, role, description_text, created_at_utc) "
        "VALUES ('ev-1', 'stx:one', 'doc-a:0', 'doc-a', 'enrichment', 'pdf line', ?)",
        (TS,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO event_evidence (evidence_id, staged_transaction_id, source_record_id, "
            " source_document_id, role, description_text, created_at_utc) "
            "VALUES ('ev-2', 'stx:one', 'doc-a:1', 'doc-a', 'enrichment', 'other line', ?)",
            (TS,),
        )


def test_attach_proposals_one_row_per_source_record():
    conn = connect(":memory:")
    migrations.migrate(conn)
    _seed_parents(conn)
    conn.execute(
        "INSERT INTO attach_proposals (proposal_id, source_record_id, source_document_id, kind, "
        " candidate_staged_ids, staged_input_json, status, created_at_utc) "
        "VALUES ('p1', 'doc-a:0', 'doc-a', 'unique', '[\"stx:one\"]', '{}', 'pending', ?)",
        (TS,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO attach_proposals (proposal_id, source_record_id, source_document_id, kind, "
            " candidate_staged_ids, staged_input_json, status, created_at_utc) "
            "VALUES ('p2', 'doc-a:0', 'doc-a', 'unique', '[\"stx:two\"]', '{}', 'pending', ?)",
            (TS,),
        )
