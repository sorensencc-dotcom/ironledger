import json
from pathlib import Path
import pytest
from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.project.activate import rebuild_projection
from ironledger.mcp.tools import TOOL_NAMES, list_tools, call_tool
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


def test_list_tools_order_and_schemas():
    tools = list_tools()
    names = [t["name"] for t in tools]
    assert names == ["search", "balances", "projection_status"]
    assert TOOL_NAMES == ("search", "balances", "projection_status")

    search_tool = next(t for t in tools if t["name"] == "search")
    schema = search_tool["inputSchema"]
    assert "query" in schema["required"]
    assert schema["properties"]["limit"]["maximum"] == 500
    assert "path" not in schema["properties"]

    balances_tool = next(t for t in tools if t["name"] == "balances")
    assert balances_tool["inputSchema"]["type"] == "object"


def test_call_tool_search_parity_and_integers(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    res = call_tool(
        "search",
        {"query": "Coffee"},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db,
    )
    assert res["isError"] is False
    data = json.loads(res["content"][0]["text"])
    assert "hits" in data
    hits = data["hits"]
    assert len(hits) >= 1
    first = hits[0]
    assert first["staged_transaction_id"] == "stx-1"
    assert isinstance(first["minor_units"], int) and not isinstance(first["minor_units"], bool)


def test_call_tool_unknown_does_not_rebuild(mcp_env, monkeypatch):
    ledger_dir, projection_dir, db = mcp_env
    called = False
    def fake_rebuild(*a, **kw):
        nonlocal called
        called = True
    monkeypatch.setattr("ironledger.project.activate.rebuild_projection", fake_rebuild)

    res = call_tool(
        "compile",
        {},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db,
    )
    assert res["isError"] is True
    assert not called
