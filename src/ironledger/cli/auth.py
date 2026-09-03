"""Operator-authorization gate. Safe mode plus a typed or --confirm phrase."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Callable

from ironledger.audit import append_audit_event
from ironledger.ingest.errors import AuthorizationError

__all__ = ["expected_phrase", "safe_mode_enabled", "require_operator"]

_PREFIX = {"import": "import", "fitid-trust-add": "trust"}


def expected_phrase(action: str, subject: str) -> str:
    try:
        prefix = _PREFIX[action]
    except KeyError as exc:
        raise ValueError(f"no phrase defined for action {action!r}") from exc
    return f"{prefix} {subject}"


def safe_mode_enabled(config_dir: str | Path) -> bool:
    path = Path(config_dir) / "safe-mode.json"
    if not path.is_file():
        return True
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("enabled", True))
    except json.JSONDecodeError:
        return True


def require_operator(
    conn: sqlite3.Connection,
    *,
    action: str,
    subject: str,
    confirm: str | None,
    stdin_isatty: bool,
    config_dir: str | Path,
    prompt: Callable[[str], str] = input,
) -> str:
    """Return the mechanism string, or raise AuthorizationError after a denied audit event."""
    want = expected_phrase(action, subject)

    def deny(reason: str) -> AuthorizationError:
        append_audit_event(
            conn, actor="operator", action=f"{action} (denied: {reason})",
            target=subject, result="denied",
        )
        conn.commit()
        return AuthorizationError(f"{action} not authorized: {reason}")

    if safe_mode_enabled(config_dir):
        raise deny("safe mode is on")

    if stdin_isatty and confirm is None:
        typed = prompt(f"Type the confirmation phrase to authorize this {action}: ")
        if typed.strip() == want:
            return "tty"
        raise deny("typed phrase did not match")

    if confirm is not None:
        if confirm.strip() == want:
            return "confirm-flag"
        raise deny("--confirm phrase did not match")

    raise deny("no confirmation supplied")
