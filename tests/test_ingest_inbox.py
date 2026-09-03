"""Phase 2a: inbox path resolution rejects everything outside the configured root."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ironledger.ingest.errors import ConfigError, IngestPathError
from ironledger.ingest.inbox import load_inbox_root, resolve_inbox_path


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, Path]:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (config_dir / "filesystem-roots.json").write_text(
        json.dumps({"ingest_inbox": str(inbox)}), encoding="utf-8"
    )
    return config_dir, inbox


def test_missing_config_file_raises_config_error_naming_d4(tmp_path: Path):
    with pytest.raises(ConfigError) as exc:
        load_inbox_root(tmp_path / "config")
    assert "D-4" in str(exc.value)


def test_missing_key_raises_config_error(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "filesystem-roots.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_inbox_root(config_dir)


def test_valid_file_directly_in_inbox_resolves(workspace: tuple[Path, Path]):
    config_dir, inbox = workspace
    f = inbox / "statement.ofx"
    f.write_bytes(b"OFXHEADER:100")
    assert resolve_inbox_path(config_dir, f) == f.resolve()


def test_traversal_outside_the_root_is_rejected(workspace: tuple[Path, Path]):
    config_dir, inbox = workspace
    outside = inbox.parent / "secret.csv"
    outside.write_bytes(b"a,b")
    with pytest.raises(IngestPathError):
        resolve_inbox_path(config_dir, inbox / ".." / "secret.csv")


def test_symlink_escape_is_rejected(workspace: tuple[Path, Path]):
    config_dir, inbox = workspace
    target = inbox.parent / "real.csv"
    target.write_bytes(b"a,b")
    link = inbox / "link.csv"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available on this platform/user")
    with pytest.raises(IngestPathError):
        resolve_inbox_path(config_dir, link)


def test_disallowed_suffix_is_rejected(workspace: tuple[Path, Path]):
    config_dir, inbox = workspace
    f = inbox / "notes.txt"
    f.write_bytes(b"hello")
    with pytest.raises(IngestPathError):
        resolve_inbox_path(config_dir, f)


def test_directory_is_rejected(workspace: tuple[Path, Path]):
    config_dir, inbox = workspace
    sub = inbox / "sub.csv"
    sub.mkdir()
    with pytest.raises(IngestPathError):
        resolve_inbox_path(config_dir, sub)


def test_unc_path_is_rejected(workspace: tuple[Path, Path]):
    config_dir, inbox = workspace
    with pytest.raises(IngestPathError):
        resolve_inbox_path(config_dir, r"\\server\share\statement.csv")
    assert list(inbox.iterdir()) == []


def test_device_path_is_rejected(workspace: tuple[Path, Path]):
    config_dir, inbox = workspace
    with pytest.raises(IngestPathError):
        resolve_inbox_path(config_dir, r"\\.\PhysicalDrive0")
    assert list(inbox.iterdir()) == []
