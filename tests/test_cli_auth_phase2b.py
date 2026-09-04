# tests/test_cli_auth_phase2b.py
"""Phase 2b: auth-gate extensions for review and rule actions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.errors import AuthorizationError
from ironledger.cli.auth import expected_phrase, require_operator, require_safe_mode_off


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


def test_phrases():
    assert expected_phrase("review-approve", "stx:abc") == "approve stx:abc"
    assert expected_phrase("review-reject", "stx:abc") == "reject stx:abc"
    assert expected_phrase("review-reopen", "stx:abc") == "reopen stx:abc"
    assert expected_phrase("review-auto-match", "all") == "auto-match all"
    assert expected_phrase("rule-add", "Expenses:Coffee") == "rule Expenses:Coffee"
    assert expected_phrase("rule-disable", "rule:abc") == "rule-disable rule:abc"
    assert expected_phrase("review-session", "ledger.db") == "review-session ledger.db"


def test_require_operator_authorizes_approve_with_confirm(db, tmp_path):
    cfg = _config(tmp_path, safe=False)
    phrase = expected_phrase("review-approve", "stx:abc")
    mech = require_operator(db, action="review-approve", subject="stx:abc", confirm=phrase,
                            stdin_isatty=False, config_dir=cfg)
    assert mech == "confirm-flag"


def test_safe_mode_off_helper_denies_and_audits(db, tmp_path):
    cfg = _config(tmp_path, safe=True)
    with pytest.raises(AuthorizationError):
        require_safe_mode_off(db, action="review categorize", subject="stx:abc", config_dir=cfg)
    action, result = db.execute(
        "SELECT action, result FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert result == "denied"
    assert action == "review categorize (denied: safe mode is on)"


def test_safe_mode_off_helper_passes_when_off(db, tmp_path):
    cfg = _config(tmp_path, safe=False)
    assert require_safe_mode_off(db, action="review categorize", subject="stx:abc", config_dir=cfg) is None
