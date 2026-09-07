# tests/test_cli_auth_phase3.py
"""Phase 3: compile and recovery authorization phrases and safe-mode gating.

Adapted from the task-12 brief per controller ruling PF-1: the brief's snippets
assume an ``expected_phrase=``/``confirm_flag=`` API and an ``IRONLEDGER_SAFE_MODE``
env var that do not exist in this repo. The real ``require_operator`` is gated by
a ``safe-mode.json`` file under ``config_dir`` and takes ``subject=``/``confirm=``.
Each test below preserves the intent of its brief counterpart against that API.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.cli.auth import (
    require_operator,
    AuthorizationError,
    COMPILE_PHRASE,
    COMPILE_RECOVER_PHRASE,
)


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _safe_mode_off(tmp_path: Path) -> Path:
    """A config dir with safe mode explicitly disabled."""
    d = tmp_path / "config"
    d.mkdir()
    (d / "safe-mode.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
    return d


def _safe_mode_default_on(tmp_path: Path) -> Path:
    """A config dir with no safe-mode.json -> safe mode ON by default."""
    d = tmp_path / "config-empty"
    d.mkdir()
    return d


def test_compile_phrases_defined():
    assert COMPILE_PHRASE == "authorize compile"
    assert COMPILE_RECOVER_PHRASE == "authorize compile recover"


def test_compile_authorized_with_confirm_flag(db: sqlite3.Connection, tmp_path: Path):
    res = require_operator(
        db,
        action="compile",
        subject="compile",
        confirm=COMPILE_PHRASE,
        stdin_isatty=False,
        config_dir=_safe_mode_off(tmp_path),
    )
    assert res == "confirm-flag"


def test_compile_denied_with_wrong_phrase(db: sqlite3.Connection, tmp_path: Path):
    with pytest.raises(AuthorizationError):
        require_operator(
            db,
            action="compile",
            subject="compile",
            confirm="wrong phrase",
            stdin_isatty=False,
            config_dir=_safe_mode_off(tmp_path),
        )
    row = db.execute(
        "SELECT action, result FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert row[1] == "denied"
    assert row[0].startswith("compile")


def test_safe_mode_blocks_compile_and_recover(db: sqlite3.Connection, tmp_path: Path):
    cfg = _safe_mode_default_on(tmp_path)
    with pytest.raises(AuthorizationError, match="safe mode"):
        require_operator(
            db,
            action="compile",
            subject="compile",
            confirm=COMPILE_PHRASE,
            stdin_isatty=False,
            config_dir=cfg,
        )
    with pytest.raises(AuthorizationError, match="safe mode"):
        require_operator(
            db,
            action="compile recover",
            subject="compile recover",
            confirm=COMPILE_RECOVER_PHRASE,
            stdin_isatty=False,
            config_dir=cfg,
        )
