"""Phase 2a: the operator-authorization gate for import and fitid-trust add."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.errors import AuthorizationError
from ironledger.cli.auth import expected_phrase, require_operator, safe_mode_enabled


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _config(tmp_path: Path, safe: bool) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    (d / "safe-mode.json").write_text(json.dumps({"enabled": safe}), encoding="utf-8")
    return d


def test_safe_mode_defaults_to_enabled_when_file_absent(tmp_path: Path):
    d = tmp_path / "config"
    d.mkdir()
    assert safe_mode_enabled(d) is True


def test_safe_mode_on_denies_and_audits(db: sqlite3.Connection, tmp_path: Path):
    config_dir = _config(tmp_path, safe=True)
    with pytest.raises(AuthorizationError):
        require_operator(db, action="import", subject="/inbox/a.ofx", confirm="import /inbox/a.ofx",
                         stdin_isatty=False, config_dir=config_dir)
    row = db.execute("SELECT action, result FROM audit_events").fetchone()
    assert row[1] == "denied"


def test_confirm_flag_match_authorizes(db: sqlite3.Connection, tmp_path: Path):
    config_dir = _config(tmp_path, safe=False)
    phrase = expected_phrase("import", "/inbox/a.ofx")
    mechanism = require_operator(db, action="import", subject="/inbox/a.ofx", confirm=phrase,
                                stdin_isatty=False, config_dir=config_dir)
    assert mechanism == "confirm-flag"
    assert db.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 0


def test_confirm_flag_mismatch_denies_and_audits(db: sqlite3.Connection, tmp_path: Path):
    config_dir = _config(tmp_path, safe=False)
    with pytest.raises(AuthorizationError):
        require_operator(db, action="import", subject="/inbox/a.ofx", confirm="wrong",
                         stdin_isatty=False, config_dir=config_dir)
    assert db.execute("SELECT result FROM audit_events").fetchone()[0] == "denied"


def test_tty_prompt_match_authorizes(db: sqlite3.Connection, tmp_path: Path):
    config_dir = _config(tmp_path, safe=False)
    phrase = expected_phrase("fitid-trust-add", "bank/acct")
    mechanism = require_operator(
        db, action="fitid-trust-add", subject="bank/acct", confirm=None,
        stdin_isatty=True, prompt=lambda _p: phrase, config_dir=config_dir,
    )
    assert mechanism == "tty"


def test_no_confirmation_at_all_denies(db: sqlite3.Connection, tmp_path: Path):
    config_dir = _config(tmp_path, safe=False)
    with pytest.raises(AuthorizationError):
        require_operator(db, action="import", subject="/inbox/a.ofx", confirm=None,
                         stdin_isatty=False, config_dir=config_dir)
