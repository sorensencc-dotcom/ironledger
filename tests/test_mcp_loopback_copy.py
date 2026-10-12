from pathlib import Path

import pytest

from ironledger.db.connection import connect
from ironledger.mcp.loopback import (
    CONTAINER_DATABASE,
    COPY_NAME,
    LiveDatabaseRefused,
    assert_not_live,
    prepare_copy,
)


def test_refuses_repo_root_database(tmp_path: Path):
    live = tmp_path / "ironledger.db"
    live.write_bytes(b"")
    with pytest.raises(LiveDatabaseRefused):
        assert_not_live(live, tmp_path)


def test_refuses_container_database(tmp_path: Path):
    with pytest.raises(LiveDatabaseRefused):
        assert_not_live(Path(CONTAINER_DATABASE), tmp_path)


def test_prepare_copy_migrates_a_new_file_and_is_idempotent(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "ironledger.db").write_bytes(b"live")
    root = tmp_path / "copy-root"
    first = prepare_copy(root, repo)
    second = prepare_copy(root, repo)
    assert first.database == second.database
    assert first.database.name == COPY_NAME
    assert first.database.resolve() != (repo / "ironledger.db").resolve()
    assert (repo / "ironledger.db").read_bytes() == b"live"
    conn = connect(first.database)
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audit_events'"
        ).fetchone()
    finally:
        conn.close()
    assert row == (1,)


def test_module_does_not_call_serve_http():
    source = Path(__file__).resolve().parents[1] / "src" / "ironledger" / "mcp" / "loopback.py"
    text = source.read_text(encoding="utf-8")
    assert "serve_http" not in text.split('"""', 2)[-1]
