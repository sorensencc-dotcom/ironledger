import stat
import os
from pathlib import Path
import pytest
from ironledger.mcp.token import load_or_create_token, rotate_token, verify_bearer


def test_create_hex_and_reuse(tmp_path: Path):
    token = load_or_create_token(tmp_path / "projection")
    assert len(token) == 64
    int(token, 16)
    again = load_or_create_token(tmp_path / "projection")
    assert again == token
    assert not (tmp_path / "projection" / "projection.sqlite").exists()


def test_mode_0600(tmp_path: Path):
    if os.name == "nt":
        pytest.skip("Windows chmod subset")
    load_or_create_token(tmp_path)
    mode = (tmp_path / ".mcp-token").stat().st_mode & 0o777
    assert mode == 0o600


def test_rotate_changes(tmp_path: Path):
    a = load_or_create_token(tmp_path)
    b = rotate_token(tmp_path)
    assert a != b
    assert load_or_create_token(tmp_path) == b


def test_verify_bearer():
    token = "ab" * 32
    assert verify_bearer(f"Bearer {token}", token) is True
    assert verify_bearer(f"Bearer {'cd' * 32}", token) is False
    assert verify_bearer(None, token) is False
    assert verify_bearer("Bearer", token) is False
    assert verify_bearer(f"bearer {token}", token) is False


def test_corrupt_token_rewritten(tmp_path: Path):
    path = tmp_path / ".mcp-token"
    path.write_text("nope", encoding="utf-8")
    token = load_or_create_token(tmp_path)
    assert len(token) == 64
    int(token, 16)
    assert path.read_text(encoding="utf-8").strip() == token
    assert verify_bearer("Bearer nope", token) is False


def test_reuse_chmods_0600(tmp_path: Path):
    if os.name == "nt":
        pytest.skip("Windows chmod subset")
    token = load_or_create_token(tmp_path)
    path = tmp_path / ".mcp-token"
    os.chmod(path, 0o644)
    again = load_or_create_token(tmp_path)
    assert again == token
    assert path.stat().st_mode & 0o777 == 0o600
