"""Connection policy: foreign keys must be enforced.

Full constraint-rejection coverage is Phase 1 task 3. This only proves the
helper actually turns enforcement on, so task 2's structural tests are
meaningful.
"""

from ironledger.db.connection import connect


def test_connection_has_foreign_keys_on():
    conn = connect(":memory:")
    (state,) = conn.execute("PRAGMA foreign_keys").fetchone()
    assert state == 1


def test_journal_mode_override(monkeypatch, tmp_path):
    monkeypatch.setenv("IRONLEDGER_JOURNAL_MODE", "DELETE")
    conn = connect(tmp_path / "journal.db")
    (mode,) = conn.execute("PRAGMA journal_mode").fetchone()
    assert mode == "delete"


def test_restricted_delete_raises_with_enforcement_live(tmp_path):
    import sqlite3

    import pytest

    from ironledger.db import migrations

    conn = connect(tmp_path / "primary.db")
    migrations.migrate(conn)
    conn.execute(
        "INSERT INTO source_documents "
        "(source_document_id, mime_type, encoding, provenance, acquisition_time_utc, "
        " content_sha256, raw_payload_ref, created_at_utc) VALUES "
        "('doc-1', 'text/csv', 'utf-8', 'test', '2026-08-31T00:00:00Z', "
        f"'{'a' * 64}', 'evidence/source_documents/doc-1', '2026-08-31T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records "
        "(source_record_id, source_document_id, record_index, canonical_payload, "
        " content_sha256, created_at_utc) VALUES "
        f"('rec-1', 'doc-1', 0, '{{}}', '{'b' * 64}', '2026-08-31T00:00:00Z')"
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM source_documents WHERE source_document_id = 'doc-1'")


def test_connect_raises_when_foreign_keys_not_enforced(monkeypatch):
    import sqlite3
    import pytest
    from ironledger.db.connection import ForeignKeysNotEnforced

    class DummyCursor:
        def fetchone(self):
            return (0,)

    class DummyConn:
        def execute(self, sql):
            return DummyCursor()

        def close(self):
            pass

    monkeypatch.setattr(sqlite3, "connect", lambda _: DummyConn())

    with pytest.raises(ForeignKeysNotEnforced):
        connect(":memory:")

