# tests/test_cli_auth_phase4.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ironledger.cli.auth import PROJECT_PHRASE, AuthorizationError, expected_phrase, require_operator
from ironledger.db import migrations
from ironledger.db.connection import connect


def _off(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    (d / "safe-mode.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
    return d


def test_project_phrase_defined():
    assert PROJECT_PHRASE == "authorize project"
    assert expected_phrase("project", "project") == PROJECT_PHRASE


def test_project_authorized_with_confirm(tmp_path: Path):
    conn = connect(":memory:")
    migrations.migrate(conn)
    res = require_operator(
        conn,
        action="project",
        subject="project",
        confirm=PROJECT_PHRASE,
        stdin_isatty=False,
        config_dir=_off(tmp_path),
    )
    assert res == "confirm-flag"


def test_project_denied_wrong_phrase(tmp_path: Path):
    conn = connect(":memory:")
    migrations.migrate(conn)
    with pytest.raises(AuthorizationError):
        require_operator(
            conn,
            action="project",
            subject="project",
            confirm="wrong phrase",
            stdin_isatty=False,
            config_dir=_off(tmp_path),
        )
    row = conn.execute("SELECT result FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    assert row[0] == "denied"


def test_project_denied_safe_mode(tmp_path: Path):
    conn = connect(":memory:")
    migrations.migrate(conn)
    d = tmp_path / "config-empty"
    d.mkdir()
    with pytest.raises(AuthorizationError, match="safe mode"):
        require_operator(
            conn,
            action="project",
            subject="project",
            confirm=PROJECT_PHRASE,
            stdin_isatty=False,
            config_dir=d,
        )
