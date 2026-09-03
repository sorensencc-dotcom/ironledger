"""Phase 2a: `ironledger fitid-trust add/list`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ironledger.cli.__main__ import main
from ironledger.db import migrations
from ironledger.db.connection import connect


@pytest.fixture
def ws(tmp_path: Path) -> dict:
    config_dir = tmp_path / "config"; config_dir.mkdir()
    (config_dir / "safe-mode.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
    (config_dir / "filesystem-roots.json").write_text(json.dumps({"ingest_inbox": str(tmp_path)}), encoding="utf-8")
    db_path = tmp_path / "l.db"
    conn = connect(str(db_path)); migrations.migrate(conn); conn.close()
    return {"base": ["--db", str(db_path), "--config-dir", str(config_dir),
                     "--evidence-dir", str(tmp_path / "e")], "db": str(db_path)}


def test_add_requires_matching_confirm(ws: dict):
    assert main(ws["base"] + ["fitid-trust", "add", "--institution", "b", "--account", "c1"]) == 3


def test_add_then_list(ws: dict, capsys):
    code = main(ws["base"] + ["fitid-trust", "add", "--institution", "b", "--account", "c1",
                              "--confirm", "trust b/c1"])
    assert code == 0
    rows = connect(ws["db"]).execute("SELECT institution_id, account_id FROM fitid_trust_records").fetchall()
    assert rows == [("b", "c1")]
    capsys.readouterr()
    assert main(ws["base"] + ["fitid-trust", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["institution_id"] == "b"


def test_add_emits_exactly_one_ok_audit_event(ws: dict):
    code = main(ws["base"] + ["fitid-trust", "add", "--institution", "b", "--account", "c1",
                              "--confirm", "trust b/c1"])
    assert code == 0
    rows = connect(ws["db"]).execute(
        "SELECT action, result FROM audit_events"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "ok"
