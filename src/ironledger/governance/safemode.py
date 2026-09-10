"""Safe-mode mutation gate, stateless HMAC step-up tokens, and centralized authorization."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Final

from ironledger.audit import append_audit_event
from ironledger.ingest.errors import AuthorizationError

__all__ = [
    "MAX_CLOCK_SKEW_SECONDS",
    "MAX_TTL_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "SafeModeAuthorizationError",
    "create_step_up_token",
    "verify_step_up_token",
    "safe_mode_enabled",
    "get_safe_mode_secret",
    "require_governed_authorization",
]

MAX_TTL_SECONDS: Final[int] = 900
MAX_CLOCK_SKEW_SECONDS: Final[int] = 30
DEFAULT_TTL_SECONDS: Final[int] = 300

# Legacy phrase prefixes for CLI backward compatibility
_PREFIX = {
    "import": "import",
    "fitid-trust-add": "trust",
    "review-approve": "approve",
    "review-reject": "reject",
    "review-reopen": "reopen",
    "review-auto-match": "auto-match",
    "rule-add": "rule",
    "rule-disable": "rule-disable",
    "review-session": "review-session",
    "compile": "authorize",
    "compile recover": "authorize",
    "project": "authorize",
}


class SafeModeAuthorizationError(AuthorizationError):
    """Raised when an operation is blocked by safe-mode policy or authorization fails."""


def create_step_up_token(
    secret: str | bytes,
    actor: str,
    scope: str,
    target_digest: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now_epoch: int | None = None,
    *,
    jti: str | None = None,
) -> str:
    """Create a stateless HMAC-SHA256 step-up authorization token.

    Format: base64url(payload) + "." + HMAC-SHA256 signature
    Payload: {jti, actor, scope, target_digest, iat, exp}
    """
    now = int(time.time()) if now_epoch is None else int(now_epoch)
    ttl = int(ttl_seconds)
    exp = now + ttl
    nonce = jti or secrets.token_hex(16)

    payload = {
        "jti": nonce,
        "actor": actor,
        "scope": scope,
        "target_digest": target_digest,
        "iat": now,
        "exp": exp,
    }

    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode("ascii").rstrip("=")

    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    signature = hmac.new(secret_bytes, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()

    return f"{payload_b64}.{signature}"


def verify_step_up_token(
    token: str,
    secret: str | bytes,
    expected_scope: str,
    expected_target_digest: str,
    now_epoch: int | None = None,
) -> dict[str, Any]:
    """Verify an HMAC step-up token against signature, scope, target digest, and temporal constraints.

    Enforces:
    - Signature validity via timing-safe comparison
    - Expiration (exp >= now)
    - Clock skew tolerance (iat <= now + 30s)
    - Maximum TTL (exp - iat <= 900s)
    - Scope matching
    - Target digest matching
    """
    now = int(time.time()) if now_epoch is None else int(now_epoch)

    if not isinstance(token, str) or "." not in token:
        raise SafeModeAuthorizationError("malformed step-up token: missing signature delimiter")

    parts = token.split(".")
    if len(parts) != 2:
        raise SafeModeAuthorizationError("malformed step-up token: invalid segment count")

    payload_b64, signature = parts

    # Base64url decode with padding restoration
    try:
        pad = len(payload_b64) % 4
        padded = payload_b64 + ("=" * (4 - pad) if pad else "")
        raw_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise SafeModeAuthorizationError(f"malformed step-up token payload: {exc}") from exc

    if not isinstance(payload, dict):
        raise SafeModeAuthorizationError("token payload must be a JSON object")

    for field in ("jti", "actor", "scope", "target_digest", "iat", "exp"):
        if field not in payload:
            raise SafeModeAuthorizationError(f"token payload missing required field: {field!r}")

    # Verify signature (supporting hexdigest, raw base64url, or padded base64url)
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    digest_bytes = hmac.new(secret_bytes, payload_b64.encode("ascii"), hashlib.sha256).digest()
    expected_sig_hex = digest_bytes.hex()
    expected_sig_b64 = base64.urlsafe_b64encode(digest_bytes).decode("ascii").rstrip("=")
    expected_sig_b64_pad = base64.urlsafe_b64encode(digest_bytes).decode("ascii")

    sig_match = (
        hmac.compare_digest(signature, expected_sig_hex)
        or hmac.compare_digest(signature, expected_sig_b64)
        or hmac.compare_digest(signature, expected_sig_b64_pad)
    )
    if not sig_match:
        raise SafeModeAuthorizationError("invalid step-up token signature")

    iat = payload["iat"]
    exp = payload["exp"]

    if not isinstance(iat, (int, float)):
        raise SafeModeAuthorizationError("token iat must be numeric")
    if not isinstance(exp, (int, float)):
        raise SafeModeAuthorizationError("token exp must be numeric")

    # Clock skew validation
    if iat > now + MAX_CLOCK_SKEW_SECONDS:
        raise SafeModeAuthorizationError(
            f"token issued in the future (iat: {iat}, now: {now}, skew exceeds {MAX_CLOCK_SKEW_SECONDS}s)"
        )

    # Maximum TTL validation
    if exp < iat:
        raise SafeModeAuthorizationError(f"token exp ({exp}) precedes iat ({iat})")
    if (exp - iat) > MAX_TTL_SECONDS:
        raise SafeModeAuthorizationError(
            f"token TTL {exp - iat}s exceeds maximum allowed {MAX_TTL_SECONDS}s"
        )

    # Expiration check
    if exp < now:
        raise SafeModeAuthorizationError(f"token expired at {exp} (current time: {now})")

    # Scope validation
    if payload["scope"] != expected_scope:
        raise SafeModeAuthorizationError(
            f"token scope mismatch: expected {expected_scope!r}, got {payload['scope']!r}"
        )

    # Target digest validation - strict 1:1 match required (no wildcard bypass)
    if payload["target_digest"] != expected_target_digest:
        raise SafeModeAuthorizationError(
            f"token target_digest mismatch: expected {expected_target_digest!r}, got {payload['target_digest']!r}"
        )

    return payload


def safe_mode_enabled(config_dir: str | Path) -> bool:
    """Check whether safe-mode is active. Fails closed (returns True) on any error."""
    if config_dir is None:
        return True
    path = Path(config_dir) / "safe-mode.json"
    if not path.is_file():
        return True
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        if not isinstance(data, dict):
            return True
        return bool(data.get("enabled", True))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return True


def get_safe_mode_secret(config_dir: str | Path) -> str:
    """Extract safe_mode_secret from configuration or environment. Fails closed if missing."""
    if config_dir is not None:
        path = Path(config_dir) / "safe-mode.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    sec = data.get("safe_mode_secret") or data.get("secret")
                    if sec and isinstance(sec, str) and sec.strip():
                        return sec.strip()
            except Exception:
                pass

        cfg_path = Path(config_dir) / "config.json"
        if cfg_path.is_file():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    sec = data.get("safe_mode_secret") or data.get("machine_secret") or data.get("secret")
                    if sec and isinstance(sec, str) and sec.strip():
                        return sec.strip()
            except Exception:
                pass

        machine_file = Path(config_dir) / "machine-id"
        if machine_file.is_file():
            try:
                m_id = machine_file.read_text(encoding="utf-8").strip()
                if m_id:
                    return f"ironledger-machine-{m_id}"
            except Exception:
                pass

    env_secret = os.environ.get("IRONLEDGER_SAFE_MODE_SECRET")
    if env_secret and env_secret.strip():
        return env_secret.strip()

    raise SafeModeAuthorizationError(
        "no safe mode secret configured in safe-mode.json, config.json, machine-id, or IRONLEDGER_SAFE_MODE_SECRET"
    )


def _matches_phrase(candidate: str, scope: str, target: str) -> bool:
    cand = candidate.strip()
    prefix = _PREFIX.get(scope)
    if prefix and cand == f"{prefix} {target}".strip():
        return True
    if cand == f"authorize {scope}":
        return True
    if cand == f"authorize {scope} {target}".strip():
        return True
    if cand == f"{scope} {target}".strip():
        return True
    return False


def require_governed_authorization(
    conn: sqlite3.Connection,
    *,
    token: str | None = None,
    phrase: str | None = None,
    scope: str,
    target_digest: str,
    config_dir: Path | str,
    actor: str = "operator",
) -> dict[str, Any]:
    """Enforce safe-mode policy gating for mutating actions.

    - If safe mode is off: allows execution with mechanism 'safe_mode_disabled'.
    - If safe mode is on: requires a valid signed HMAC step-up token or matching phrase.
    - Logs accepted step-up authorizations to audit_events.
    - Logs all denied authorization attempts directly to audit_events with result="denied"
      and raises SafeModeAuthorizationError.
    """
    if not safe_mode_enabled(config_dir):
        return {
            "authorized": True,
            "result": "authorized",
            "scope": scope,
            "actor": actor,
            "target_digest": target_digest,
            "mechanism": "safe_mode_disabled",
        }

    # Safe mode is active: Cryptographic step-up token is strictly required.
    # Plaintext confirmation phrases do not bypass the safe mode cryptographic gate.
    if not token or not isinstance(token, str) or not token.strip():
        reason = "safe mode is active: cryptographic step-up token required (no token provided)"
        append_audit_event(
            conn,
            actor=actor,
            action=f"{scope} (denied: {reason})",
            target=target_digest,
            result="denied",
        )
        conn.commit()
        raise SafeModeAuthorizationError(f"{scope} not authorized: {reason}")

    secret = get_safe_mode_secret(config_dir)
    try:
        payload = verify_step_up_token(
            token.strip(),
            secret,
            expected_scope=scope,
            expected_target_digest=target_digest,
        )
        effective_actor = payload.get("actor") or actor
        append_audit_event(
            conn,
            actor=effective_actor,
            action=f"authorize {scope} (step-up)",
            target=target_digest,
            result="ok",
        )
        conn.commit()
        return {
            "authorized": True,
            "result": "authorized",
            "scope": scope,
            "actor": effective_actor,
            "target_digest": target_digest,
            "mechanism": "token",
            "payload": payload,
        }
    except SafeModeAuthorizationError as exc:
        reason = f"token invalid ({exc})"
        append_audit_event(
            conn,
            actor=actor,
            action=f"{scope} (denied: {reason})",
            target=target_digest,
            result="denied",
        )
        conn.commit()
        raise SafeModeAuthorizationError(f"{scope} not authorized: {reason}") from exc
