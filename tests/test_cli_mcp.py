import json, pytest
from pathlib import Path
from ironledger.cli.__main__ import main
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

def test_cli_mcp_argv_exits(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    # Missing --db -> 2
    assert main(["mcp", "--ledger-dir", str(ledger_dir)]) == 2

    # --bind without --port -> 2
    assert main(["mcp", "--db", db, "--ledger-dir", str(ledger_dir), "--bind", "127.0.0.1"]) == 2

    # --port without --bind -> 2
    assert main(["mcp", "--db", db, "--ledger-dir", str(ledger_dir), "--port", "8765"]) == 2

    # --rotate-token without --bind -> 2
    assert main(["mcp", "--db", db, "--ledger-dir", str(ledger_dir), "--rotate-token"]) == 2

    # --bind 0.0.0.0 -> exit 1
    assert main(["mcp", "--db", db, "--ledger-dir", str(ledger_dir), "--bind", "0.0.0.0", "--port", "8765"]) == 1

    # Bearer rotation belongs to serve_http. --bind starts the loopback daemon.
    assert main(["mcp", "--db", db, "--ledger-dir", str(ledger_dir), "--bind", "127.0.0.1", "--port", "8766", "--rotate-token"]) == 2


def test_cli_mcp_bind_starts_loopback_copy(mcp_env, monkeypatch, tmp_path):
    ledger_dir, _projection_dir, db = mcp_env
    copy_root = tmp_path / "daemon-root"
    monkeypatch.setenv("IRONLEDGER_MCP_COPY_ROOT", str(copy_root))
    seen = {}

    def fake_serve(copy, *, host, port):
        seen["host"] = host
        seen["port"] = port
        seen["database"] = copy.database

    monkeypatch.setattr("ironledger.mcp.loopback.serve", fake_serve)
    code = main(["mcp", "--db", db, "--ledger-dir", str(ledger_dir), "--bind", "127.0.0.1", "--port", "8766"])
    assert code == 0
    assert seen["host"] == "127.0.0.1"
    assert seen["port"] == 8766
    assert seen["database"].name == "ironledger.daemon-copy.db"
    assert Path(db).resolve() != seen["database"].resolve()


def test_cli_mcp_bind_refuses_live_database(mcp_env, monkeypatch):
    from ironledger.mcp.loopback import repo_root

    ledger_dir, _projection_dir, _db = mcp_env
    live = repo_root() / "ironledger.db"

    def fail_serve(*_args, **_kwargs):
        raise AssertionError("serve must not run")

    monkeypatch.setattr("ironledger.mcp.loopback.serve", fail_serve)
    code = main(["mcp", "--db", str(live), "--ledger-dir", str(ledger_dir), "--bind", "127.0.0.1", "--port", "8766"])
    assert code == 1
