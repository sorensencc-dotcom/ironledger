"""Typed ingestion failures. Every failure path in Phase 2a raises one of these."""

from __future__ import annotations

__all__ = [
    "IngestError",
    "IngestPathError",
    "ParseError",
    "StageError",
    "ConfigError",
    "AuthorizationError",
]


class IngestError(Exception):
    """Base class for every Phase 2a ingestion failure."""


class IngestPathError(IngestError):
    """A path is outside the inbox root, or is a traversal, symlink, UNC, or device path."""


class ParseError(IngestError):
    """A source file could not be parsed into valid rows."""

    def __init__(self, message: str, *, row_index: int | None = None) -> None:
        super().__init__(message)
        self.row_index = row_index


class StageError(IngestError):
    """Writing staged rows failed a database constraint."""


class ConfigError(IngestError):
    """Required configuration is missing or malformed."""


class AuthorizationError(IngestError):
    """An operator-authorization point was reached without valid authorization."""
