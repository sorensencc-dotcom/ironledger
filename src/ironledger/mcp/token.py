"""Bearer token management for IronLedger MCP."""
import hmac
import os
import secrets
from pathlib import Path

TOKEN_NAME = ".mcp-token"


def _is_valid_hex_token(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
        return True
    except ValueError:
        return False


def _chmod_0600(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def rotate_token(projection_dir: Path) -> str:
    """Generate a new 64-hex token and atomically write it to .mcp-token."""
    projection_dir.mkdir(parents=True, exist_ok=True)
    live_path = projection_dir / TOKEN_NAME
    tmp_path = projection_dir / f"{TOKEN_NAME}.tmp"

    token = secrets.token_bytes(32).hex().lower()
    tmp_path.write_text(f"{token}\n", encoding="utf-8")
    _chmod_0600(tmp_path)
    os.replace(tmp_path, live_path)
    _chmod_0600(live_path)
    return token


def load_or_create_token(projection_dir: Path) -> str:
    """Load an existing 64-hex token, or generate and save a new one."""
    live_path = projection_dir / TOKEN_NAME
    if live_path.is_file():
        try:
            content = live_path.read_text(encoding="utf-8").strip()
            if _is_valid_hex_token(content):
                _chmod_0600(live_path)
                return content
        except OSError:
            pass

    return rotate_token(projection_dir)


def verify_bearer(header: str | None, token: str) -> bool:
    """Verify that header is 'Bearer <token>' using compare_digest."""
    if not header or not header.startswith("Bearer "):
        return False
    parts = header.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        return False
    return hmac.compare_digest(parts[1], token)
