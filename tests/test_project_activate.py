# tests/test_project_activate.py
from __future__ import annotations

from pathlib import Path

import pytest

from ironledger.compile.errors import CompileLockedError
from ironledger.compile.writer import acquire_compile_lock
from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.project.activate import rebuild_projection
from ironledger.project.errors import ProjectHashMismatchError, ProjectLockedError
from ironledger.project.parse import parse_ledger
from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger


@pytest.fixture
def world(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / "ironledger.db"
    seed_successful_compile_run(db_path, ledger_dir, "run-1")
    conn = connect(str(db_path))
    migrations.migrate(conn)
    return conn, ledger_dir, tmp_path / "projection"


def test_rebuild_writes_live_sqlite_and_manifest(world):
    conn, ledger_dir, projection_dir = world
    summary = rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    assert summary.compile_run_id == "run-1"
    assert (projection_dir / "projection.sqlite").is_file()
    assert (projection_dir / "projection.manifest.json").is_file()
    parsed = parse_ledger(ledger_dir)
    live = connect(projection_dir / "projection.sqlite")
    n_entries = live.execute("SELECT count(*) FROM proj_entries").fetchone()[0]
    n_postings = live.execute("SELECT count(*) FROM proj_postings").fetchone()[0]
    assert n_entries == len(parsed.entries)
    assert n_postings == sum(len(e.postings) for e in parsed.entries)
    live.close()


def test_hash_mismatch_leaves_live_untouched(world):
    conn, ledger_dir, projection_dir = world
    (ledger_dir / "accounts.beancount").write_bytes(
        (ledger_dir / "accounts.beancount").read_bytes() + b"\n"
    )
    with pytest.raises(ProjectHashMismatchError):
        rebuild_projection(conn, ledger_dir, projection_dir)
    assert not (projection_dir / "projection.sqlite").exists()


def test_held_compile_lock_refuses(world):
    conn, ledger_dir, projection_dir = world
    with acquire_compile_lock(ledger_dir):
        with pytest.raises(CompileLockedError):
            rebuild_projection(conn, ledger_dir, projection_dir)
    assert not (projection_dir / "projection.sqlite").exists()
