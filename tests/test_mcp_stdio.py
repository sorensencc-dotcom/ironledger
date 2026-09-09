import json, io, pytest
from pathlib import Path
from ironledger.mcp.stdio import run_stdio
from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.project.activate import rebuild_projection
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

def test_stdio_roundtrip(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    init_req = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test"}}
    }).encode("utf-8") + b"\n"
    sin = io.BytesIO(init_req)
    sout = io.BytesIO()
    serr = io.StringIO()
    rc = run_stdio(sin, sout, serr, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert rc == 0
    lines = sout.getvalue().splitlines()
    assert len(lines) == 1
    d = json.loads(lines[0])
    assert d["result"]["serverInfo"]["name"] == "ironledger"

def test_stdio_oversize_line_and_recovery(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    oversize = b"{\"test\":\"" + (b"a" * 1048581) + b"\"}\n"
    init_req = json.dumps({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "ping"
    }).encode("utf-8") + b"\n"
    sin = io.BytesIO(oversize + init_req)
    sout = io.BytesIO()
    serr = io.StringIO()
    rc = run_stdio(sin, sout, serr, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert rc == 0
    lines = sout.getvalue().splitlines()
    assert len(lines) == 2
    err_obj = json.loads(lines[0])
    assert err_obj["error"]["code"] == -32700
    ping_obj = json.loads(lines[1])
    assert ping_obj["result"] == {}
