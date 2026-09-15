"""Resolve and validate the operator ingest inbox path.

The inbox is an absolute path outside the repository, configured by decision
D-4 in config/filesystem-roots.json. IronLedger only ever reads from it.
"""

from __future__ import annotations

import json
from pathlib import Path

from ironledger.ingest.errors import ConfigError, IngestPathError

__all__ = ["ALLOWED_SUFFIXES", "load_inbox_root", "resolve_inbox_path"]

ALLOWED_SUFFIXES = frozenset({".csv", ".ofx", ".qfx", ".pdf"})

_ROOTS_FILE = "filesystem-roots.json"
_INBOX_KEY = "ingest_inbox"


def load_inbox_root(config_dir: str | Path) -> Path:
    """Return the resolved absolute ingest inbox directory from config."""
    roots_path = Path(config_dir) / _ROOTS_FILE
    if not roots_path.is_file():
        raise ConfigError(
            f"{roots_path} is missing. Set the ingest inbox path (decision D-4) "
            f"by creating it with an {_INBOX_KEY!r} key holding an absolute directory path."
        )
    try:
        data = json.loads(roots_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{roots_path} is not valid JSON: {exc}") from exc
    raw = data.get(_INBOX_KEY)
    if not raw or not isinstance(raw, str):
        raise ConfigError(
            f"{roots_path} has no {_INBOX_KEY!r} string (decision D-4). "
            f"Set it to the absolute path of the directory where you drop files to import."
        )
    root = Path(raw)
    if not root.is_absolute():
        raise ConfigError(f"{_INBOX_KEY} must be an absolute path, got {raw!r}")
    if not root.is_dir():
        raise ConfigError(f"{_INBOX_KEY} path {raw!r} is not an existing directory")
    return root.resolve()


def resolve_inbox_path(config_dir: str | Path, candidate: str | Path) -> Path:
    """Return the resolved file path when it is a regular file directly in the inbox root."""
    root = load_inbox_root(config_dir)
    candidate_path = Path(candidate)

    # Reject UNC and device paths before any filesystem call.
    raw = str(candidate_path)
    if raw.startswith("\\\\") or raw.startswith("//"):
        raise IngestPathError(f"UNC paths are not allowed: {raw!r}")
    if raw.upper().startswith("\\\\.\\") or raw.upper().startswith("\\\\?\\"):
        raise IngestPathError(f"device paths are not allowed: {raw!r}")

    try:
        resolved = candidate_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise IngestPathError(f"path could not be resolved: {candidate!r} ({exc})") from exc

    if resolved.parent != root:
        raise IngestPathError(
            f"{resolved} is not a file directly inside the inbox root {root}"
        )
    if not resolved.is_file():
        raise IngestPathError(f"{resolved} is not a regular file")
    if resolved.suffix.lower() not in ALLOWED_SUFFIXES:
        raise IngestPathError(
            f"{resolved.name} has an unsupported type; allowed: {sorted(ALLOWED_SUFFIXES)}"
        )
    return resolved
