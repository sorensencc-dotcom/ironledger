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
