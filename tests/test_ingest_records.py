"""Phase 2a: canonical record normalization and the idempotent source_records writer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.formats.model import ParsedRow
from ironledger.ingest.records import canonical_json, normalize_row, write_source_record


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, "
        " acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        f"VALUES ('doc-1', 'text/csv', 'utf-8', 'test', '2026-09-02T10:00:00Z', '{'a'*64}', "
        " 'evidence/source_documents/doc-1', '2026-09-02T10:00:00Z')"
    )
    conn.commit()
    return conn


def _row(payee: str = "  COFFEE   BAR  ") -> ParsedRow:
    return ParsedRow(
        posted_date="2026-08-15", amount_text="-12.99", payee=payee, memo="",
        txn_type="DEBIT", fitid="f1", currency="USD",
    )


def test_normalize_collapses_whitespace_and_nfc():
    canonical = normalize_row(_row("Café  \t Noir"))
    assert canonical["payee"] == "Café Noir"


def test_canonical_json_is_deterministic():
    a = canonical_json(normalize_row(_row()))
    b = canonical_json(normalize_row(_row("COFFEE BAR")))
    assert a == b


def test_write_source_record_inserts_row_and_file(db: sqlite3.Connection, tmp_path: Path):
    rid = write_source_record(db, "doc-1", 0, normalize_row(_row()), records_dir=tmp_path)
    assert rid == "doc-1:0"
    assert db.execute("SELECT count(*) FROM source_records").fetchone()[0] == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_write_source_record_is_idempotent(db: sqlite3.Connection, tmp_path: Path):
    first = write_source_record(db, "doc-1", 0, normalize_row(_row()), records_dir=tmp_path)
    second = write_source_record(db, "doc-1", 0, normalize_row(_row("COFFEE BAR")), records_dir=tmp_path)
    assert first == second
    assert db.execute("SELECT count(*) FROM source_records").fetchone()[0] == 1
