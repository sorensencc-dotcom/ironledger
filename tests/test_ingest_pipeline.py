"""Phase 2a: the end-to-end import pipeline — idempotency, auditing, all-or-nothing."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.errors import ParseError
from ironledger.ingest.pipeline import run_import

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def env(tmp_path: Path) -> tuple[sqlite3.Connection, dict]:
    conn = connect(str(tmp_path / "ledger.db"))
    migrations.migrate(conn)
    config_dir = tmp_path / "config"
    (config_dir / "csv-profiles").mkdir(parents=True)
    (config_dir / "csv-profiles" / "example-bank.json").write_text(
        (Path("config/csv-profiles/example-bank.json")).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return conn, {
        "config_dir": config_dir,
        "evidence_dir": tmp_path / "evidence",
        "records_dir": tmp_path / "evidence" / "source_records",
    }


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in ("source_documents", "source_records", "staged_transactions",
                  "staged_postings", "audit_events")
    }


def test_ofx_import_stages_rows_and_writes_one_audit_event(env):
    conn, paths = env
    result = run_import(
        conn, FIXTURES / "sample_v1.ofx",
        csv_profile=None, now_utc="2026-09-02T10:00:00Z", **paths,
    )
    c = _counts(conn)
    assert (c["source_records"], c["staged_transactions"], c["staged_postings"]) == (2, 2, 4)
    assert c["audit_events"] == 1
    assert result.records_created == 2 and result.short_circuited is False


def test_reimport_short_circuits_with_zero_records_and_one_more_audit_event(env):
    conn, paths = env
    run_import(conn, FIXTURES / "sample_v1.ofx", csv_profile=None,
               now_utc="2026-09-02T10:00:00Z", **paths)
    result = run_import(conn, FIXTURES / "sample_v1.ofx", csv_profile=None,
                        now_utc="2026-09-02T10:05:00Z", **paths)
    c = _counts(conn)
    assert (c["source_records"], c["staged_transactions"]) == (2, 2)
    assert c["audit_events"] == 2
    assert result.records_created == 0 and result.short_circuited is True


def test_csv_import_uses_the_profile(env):
    conn, paths = env
    run_import(conn, FIXTURES / "sample_bank.csv", csv_profile="example-bank",
               now_utc="2026-09-02T10:00:00Z", **paths)
    accounts = {
        a for (a,) in conn.execute(
            "SELECT DISTINCT account FROM staged_postings WHERE role='imported'"
        )
    }
    assert accounts == {"Assets:Bank:Checking:ExampleBank"}


def test_bad_row_rolls_back_the_whole_file_and_audits_error(env, tmp_path: Path):
    conn, paths = env
    bad = paths["config_dir"].parent / "bad.csv"  # not used; write into a temp inbox-like path
    src = tmp_path / "bad.csv"
    src.write_text("Date,Description,Notes,Amount\n2026-08-15,X,,-1.00\n99-99-9999,Y,,-2.00\n",
                   encoding="utf-8")
    with pytest.raises(ParseError):
        run_import(conn, src, csv_profile="example-bank",
                   now_utc="2026-09-02T10:00:00Z", **paths)
    c = _counts(conn)
    assert (c["source_records"], c["staged_transactions"]) == (0, 0)
    assert c["audit_events"] == 1
    assert conn.execute("SELECT result FROM audit_events").fetchone()[0] == "error"


def test_ofx_unresolvable_curdef_audits_error_and_rolls_back(env, tmp_path: Path):
    """An OFX <CURDEF> that ofxtools accepts but IronLedger's pinned ISO-4217
    table rejects (EEK) must surface as a ParseError inside run_import's outer
    handler: one error audit event, zero staged rows, CLI exit 4."""
    conn, paths = env
    raw = (FIXTURES / "sample_v1.ofx").read_bytes().replace(b"<CURDEF>USD", b"<CURDEF>EEK")
    src = tmp_path / "bad_curdef.ofx"
    src.write_bytes(raw)
    with pytest.raises(ParseError):
        run_import(conn, src, csv_profile=None,
                   now_utc="2026-09-02T10:00:00Z", **paths)
    c = _counts(conn)
    assert (c["source_records"], c["staged_transactions"]) == (0, 0)
    assert c["audit_events"] == 1
    assert conn.execute("SELECT result FROM audit_events").fetchone()[0] == "error"
