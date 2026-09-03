"""Phase 2a: acquire copies a file into evidence once and reuses it on a repeat."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.acquire import acquire, detect_mime


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def test_detect_mime_by_suffix_and_magic(tmp_path: Path):
    csv_path = tmp_path / "a.csv"
    csv_path.write_bytes(b"a,b\n1,2\n")
    assert detect_mime(csv_path) == "text/csv"
    ofx_path = tmp_path / "a.ofx"
    ofx_path.write_bytes(b"OFXHEADER:100\n")
    assert detect_mime(ofx_path) == "application/x-ofx"


def test_acquire_writes_evidence_and_inserts_row(db: sqlite3.Connection, tmp_path: Path):
    src = tmp_path / "stmt.csv"
    src.write_bytes(b"Date,Amount\n2026-08-15,-1.00\n")
    evidence = tmp_path / "evidence"
    result = acquire(db, src, evidence_dir=evidence, provenance="example-bank/checking",
                     now_utc="2026-09-02T10:00:00Z")
    assert result.is_new is True
    stored = evidence / "source_documents" / result.content_sha256
    assert stored.read_bytes() == src.read_bytes()
    assert db.execute("SELECT count(*) FROM source_documents").fetchone()[0] == 1


def test_acquire_is_idempotent_on_content_regardless_of_filename(db: sqlite3.Connection, tmp_path: Path):
    body = b"Date,Amount\n2026-08-15,-1.00\n"
    a = tmp_path / "a.csv"; a.write_bytes(body)
    b = tmp_path / "b.csv"; b.write_bytes(body)
    evidence = tmp_path / "evidence"
    first = acquire(db, a, evidence_dir=evidence, provenance="p", now_utc="2026-09-02T10:00:00Z")
    second = acquire(db, b, evidence_dir=evidence, provenance="p", now_utc="2026-09-02T10:00:01Z")
    assert first.source_document_id == second.source_document_id
    assert second.is_new is False
    assert db.execute("SELECT count(*) FROM source_documents").fetchone()[0] == 1
