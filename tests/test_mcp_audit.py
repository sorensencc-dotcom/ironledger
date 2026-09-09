import pytest
from pathlib import Path
from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.project.activate import rebuild_projection
from ironledger.mcp.tools import call_tool
from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger

@pytest.fixture
def mcp_env(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / "ironledger.db"
    seed_successful_compile_run(db_path, ledger_dir)
    conn = connect(str(db_path))
    migrations.migrate(conn)
    projection_dir = tmp_path / "projection"
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    conn.close()
    return ledger_dir, projection_dir, str(db_path)

def test_tool_audit_no_query_leak(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    res = call_tool("search", {"query": "Coffee"}, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert res["isError"] is False

    conn = connect(db)
    rows = conn.execute("SELECT actor, action, target, result, input_hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    conn.close()
    assert rows is not None
    actor, action, target, result, input_hash = rows
    assert actor == "operator"
    assert action == "mcp search"
    assert target == "search"
    assert result == "ok"
    assert "Coffee" not in (target, input_hash or "")

def test_audit_failure_yields_error_no_hits(mcp_env, monkeypatch):
    ledger_dir, projection_dir, db = mcp_env
    def bad_audit(*a, **kw):
        raise RuntimeError("audit disk full")
    monkeypatch.setattr("ironledger.mcp.tools.append_audit_event", bad_audit)

    res = call_tool("search", {"query": "Coffee"}, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert res["isError"] is True
    text = res["content"][0]["text"]
    assert "Coffee" not in text
    assert "stx-1" not in text
