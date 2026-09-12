"""High-availability WAL frame inspection and replication protocols."""

from __future__ import annotations

from ironledger.replication.wal_parser import (
    ReplicationPosition,
    WAL_FRAME_HEADER_SIZE,
    WAL_HEADER_SIZE,
    WAL_MAGIC_BE,
    WAL_MAGIC_LE,
    WalFormatError,
    WalFrame,
    WalHeader,
    parse_wal_frames,
    parse_wal_header,
)

__all__ = [
    "ReplicationPosition",
    "WAL_FRAME_HEADER_SIZE",
    "WAL_HEADER_SIZE",
    "WAL_MAGIC_BE",
    "WAL_MAGIC_LE",
    "WalFormatError",
    "WalFrame",
    "WalHeader",
    "parse_wal_frames",
    "parse_wal_header",
]
