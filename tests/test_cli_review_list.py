"""Phase 2a: `ironledger review list` is read-only and reflects staged rows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ironledger.cli.__main__ import main
from ironledger.db import migrations
from ironledger.db.connection import connect


@pytest.fixture
def staged_ws(tmp_path: Path) -> dict:
    inbox = tmp_path / "inbox"; inbox.mkdir()
    config_dir = tmp_path / "config"; (config_dir / "csv-profiles").mkdir(parents=True)
    (config_dir / "filesystem-roots.json").write_text(json.dumps({"ingest_inbox": str(inbox)}), encoding="utf-8")
    (config_dir / "safe-mode.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
    (inbox / "sample_v1.ofx").write_bytes(Path("tests/fixtures/sample_v1.ofx").read_bytes())
    db_path = tmp_path / "l.db"
    conn = connect(str(db_path)); migrations.migrate(conn); conn.close()
    base = ["--db", str(db_path), "--config-dir", str(config_dir), "--evidence-dir", str(tmp_path / "e")]
    path = inbox / "sample_v1.ofx"
    main(base + ["import", str(path), "--confirm", f"import {path.resolve()}"])
    return {"base": base, "db": str(db_path)}


def test_review_list_json_returns_two_rows(staged_ws: dict, capsys):
    code = main(staged_ws["base"] + ["review", "list", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 2
    assert {"staged_transaction_id", "proposed_date", "status", "payee", "posting_summary"} <= set(payload[0])


def test_review_list_does_not_mutate(staged_ws: dict):
    before = connect(staged_ws["db"]).execute("SELECT count(*) FROM audit_events").fetchone()[0]
    main(staged_ws["base"] + ["review", "list"])
    after = connect(staged_ws["db"]).execute("SELECT count(*) FROM audit_events").fetchone()[0]
    assert before == after
