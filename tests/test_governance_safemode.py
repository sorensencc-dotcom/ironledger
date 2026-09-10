"""Tests for safe-mode mutation gate and stateless HMAC step-up tokens."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.governance.safemode import (
    MAX_CLOCK_SKEW_SECONDS,
    MAX_TTL_SECONDS,
    SafeModeAuthorizationError,
    create_step_up_token,
    get_safe_mode_secret,
    require_governed_authorization,
    safe_mode_enabled,
    verify_step_up_token,
)


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    return cfg


# --- Token Creation and Verification ---


def test_token_creation_and_structure():
    secret = "my-test-secret-key-1234567890"
    now = 1700000000
    token = create_step_up_token(
        secret,
        actor="operator_1",
        scope="compile",
        target_digest="a" * 64,
        ttl_seconds=300,
        now_epoch=now,
    )
    assert isinstance(token, str)
    assert "." in token
    parts = token.split(".")
    assert len(parts) == 2

    payload = verify_step_up_token(
        token,
        secret,
        expected_scope="compile",
        expected_target_digest="a" * 64,
        now_epoch=now + 10,
    )
    assert payload["actor"] == "operator_1"
    assert payload["scope"] == "compile"
    assert payload["target_digest"] == "a" * 64
    assert payload["iat"] == now
    assert payload["exp"] == now + 300
    assert "jti" in payload
    assert len(payload["jti"]) >= 16


def test_token_tampered_payload_rejected():
    secret = "secret-key-123"
    token = create_step_up_token(
        secret,
        actor="op",
        scope="compile",
        target_digest="b" * 64,
        ttl_seconds=300,
    )
    payload_b64, sig = token.split(".")
    tampered_token = ("a" + payload_b64[1:]) + "." + sig
    with pytest.raises(SafeModeAuthorizationError, match="signature|payload"):
        verify_step_up_token(tampered_token, secret, "compile", "b" * 64)


def test_token_tampered_signature_rejected():
    secret = "secret-key-123"
    token = create_step_up_token(
        secret,
        actor="op",
        scope="compile",
        target_digest="c" * 64,
        ttl_seconds=300,
    )
    payload_b64, sig = token.split(".")
    tampered_sig = "0" * len(sig)
    with pytest.raises(SafeModeAuthorizationError, match="signature"):
        verify_step_up_token(f"{payload_b64}.{tampered_sig}", secret, "compile", "c" * 64)


def test_token_wrong_secret_rejected():
    token = create_step_up_token(
        "secret-1",
        actor="op",
        scope="compile",
        target_digest="c" * 64,
        ttl_seconds=300,
    )
    with pytest.raises(SafeModeAuthorizationError, match="signature"):
        verify_step_up_token(token, "secret-2", "compile", "c" * 64)


def test_token_expiration():
    secret = "test-secret"
    now = int(time.time())
    token = create_step_up_token(
        secret,
        actor="ops",
        scope="compile",
        target_digest="a" * 64,
        ttl_seconds=10,
        now_epoch=now - 20,
    )
    with pytest.raises(SafeModeAuthorizationError, match="expired"):
        verify_step_up_token(token, secret, "compile", "a" * 64, now_epoch=now)


def test_token_clock_skew_future_rejected():
    secret = "test-secret"
    now = 1700000000
    # iat is 40 seconds in the future (exceeds 30s skew tolerance)
    token = create_step_up_token(
        secret,
        actor="ops",
        scope="compile",
        target_digest="a" * 64,
        ttl_seconds=300,
        now_epoch=now + 40,
    )
    with pytest.raises(SafeModeAuthorizationError, match="future|clock skew"):
        verify_step_up_token(token, secret, "compile", "a" * 64, now_epoch=now)


def test_token_clock_skew_within_window_accepted():
    secret = "test-secret"
    now = 1700000000
    # iat is 20 seconds in future (within 30s tolerance)
    token = create_step_up_token(
        secret,
        actor="ops",
        scope="compile",
        target_digest="a" * 64,
        ttl_seconds=300,
        now_epoch=now + 20,
    )
    payload = verify_step_up_token(token, secret, "compile", "a" * 64, now_epoch=now)
    assert payload["actor"] == "ops"


def test_token_max_ttl_exceeded_rejected():
    secret = "test-secret"
    now = 1700000000
    # TTL is 901s (exceeds max 900s)
    token = create_step_up_token(
        secret,
        actor="ops",
        scope="compile",
        target_digest="a" * 64,
        ttl_seconds=901,
        now_epoch=now,
    )
    with pytest.raises(SafeModeAuthorizationError, match="exceeds"):
        verify_step_up_token(token, secret, "compile", "a" * 64, now_epoch=now)


def test_token_scope_mismatch_rejected():
    secret = "test-secret"
    token = create_step_up_token(
        secret,
        actor="ops",
        scope="compile",
        target_digest="a" * 64,
        ttl_seconds=300,
    )
    with pytest.raises(SafeModeAuthorizationError, match="scope mismatch"):
        verify_step_up_token(token, secret, "project", "a" * 64)


def test_token_target_digest_mismatch_rejected():
    secret = "test-secret"
    token = create_step_up_token(
        secret,
        actor="ops",
        scope="compile",
        target_digest="a" * 64,
        ttl_seconds=300,
    )
    with pytest.raises(SafeModeAuthorizationError, match="target_digest mismatch"):
        verify_step_up_token(token, secret, "compile", "b" * 64)


# --- Safe-Mode Enabled & Secret Extraction ---


def test_safe_mode_enabled_fails_closed_when_file_missing(config_dir: Path):
    assert safe_mode_enabled(config_dir) is True


def test_safe_mode_enabled_fails_closed_when_corrupted_json(config_dir: Path):
    (config_dir / "safe-mode.json").write_text("{invalid-json-content", encoding="utf-8")
    assert safe_mode_enabled(config_dir) is True


def test_safe_mode_enabled_fails_closed_when_non_dict_json(config_dir: Path):
    (config_dir / "safe-mode.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert safe_mode_enabled(config_dir) is True


def test_safe_mode_enabled_explicit_false(config_dir: Path):
    (config_dir / "safe-mode.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
    assert safe_mode_enabled(config_dir) is False


def test_safe_mode_enabled_explicit_true(config_dir: Path):
    (config_dir / "safe-mode.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    assert safe_mode_enabled(config_dir) is True


def test_get_safe_mode_secret_from_config(config_dir: Path):
    (config_dir / "safe-mode.json").write_text(
        json.dumps({"enabled": True, "safe_mode_secret": "configured-secret-key-999"}),
        encoding="utf-8",
    )
    secret = get_safe_mode_secret(config_dir)
    assert secret == "configured-secret-key-999"


def test_get_safe_mode_secret_fails_closed_when_no_secret_configured(config_dir: Path):
    (config_dir / "safe-mode.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    with pytest.raises(SafeModeAuthorizationError, match="no safe mode secret configured"):
        get_safe_mode_secret(config_dir)


# --- Governed Authorization Gate ---


def test_require_governed_authorization_when_safe_mode_disabled(db: sqlite3.Connection, config_dir: Path):
    (config_dir / "safe-mode.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
    res = require_governed_authorization(
        db,
        token=None,
        phrase=None,
        scope="compile",
        target_digest="ledger",
        config_dir=config_dir,
    )
    assert res["authorized"] is True
    assert res["result"] == "authorized"
    # Safe mode disabled does not append denial events
    assert db.execute("SELECT count(*) FROM audit_events WHERE result = 'denied'").fetchone()[0] == 0


def test_require_governed_authorization_active_with_valid_token(db: sqlite3.Connection, config_dir: Path):
    secret = "governance-secret-123"
    (config_dir / "safe-mode.json").write_text(
        json.dumps({"enabled": True, "safe_mode_secret": secret}), encoding="utf-8"
    )
    token = create_step_up_token(
        secret,
        actor="sec_admin",
        scope="compile",
        target_digest="ledger",
        ttl_seconds=300,
    )
    res = require_governed_authorization(
        db,
        token=token,
        phrase=None,
        scope="compile",
        target_digest="ledger",
        config_dir=config_dir,
        actor="sec_admin",
    )
    assert res["authorized"] is True
    assert res["result"] == "authorized"
    assert res["mechanism"] == "token"

    # Verify audit event recorded for accepted step-up authorization
    row = db.execute(
        "SELECT actor, action, target, result FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert row[0] == "sec_admin"
    assert "compile" in row[1]
    assert row[3] in ("ok", "authorized")


def test_require_governed_authorization_active_denies_phrase_when_token_required(db: sqlite3.Connection, config_dir: Path):
    secret = "governance-secret-123"
    (config_dir / "safe-mode.json").write_text(
        json.dumps({"enabled": True, "safe_mode_secret": secret}), encoding="utf-8"
    )
    with pytest.raises(SafeModeAuthorizationError, match="cryptographic step-up token required"):
        require_governed_authorization(
            db,
            token=None,
            phrase="authorize compile",
            scope="compile",
            target_digest="compile",
            config_dir=config_dir,
            actor="operator",
        )

    # Denial audit record is written
    row = db.execute("SELECT actor, action, result FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    assert row[0] == "operator"
    assert "denied" in row[1]
    assert row[2] == "denied"


def test_require_governed_authorization_active_denied_no_credentials(db: sqlite3.Connection, config_dir: Path):
    (config_dir / "safe-mode.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    with pytest.raises(SafeModeAuthorizationError, match="safe mode|not authorized"):
        require_governed_authorization(
            db,
            token=None,
            phrase=None,
            scope="compile",
            target_digest="ledger",
            config_dir=config_dir,
        )

    # Verify denied audit event written
    row = db.execute(
        "SELECT actor, action, target, result FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert row[0] == "operator"
    assert row[3] == "denied"


def test_require_governed_authorization_active_denied_invalid_token(db: sqlite3.Connection, config_dir: Path):
    secret = "governance-secret-123"
    (config_dir / "safe-mode.json").write_text(
        json.dumps({"enabled": True, "safe_mode_secret": secret}), encoding="utf-8"
    )
    with pytest.raises(SafeModeAuthorizationError):
        require_governed_authorization(
            db,
            token="invalid.token.signature",
            phrase=None,
            scope="compile",
            target_digest="ledger",
            config_dir=config_dir,
        )

    row = db.execute(
        "SELECT actor, action, target, result FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert row[3] == "denied"
