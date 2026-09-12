"""SQLite Write-Ahead Log (WAL) frame inspector and replication state model.

Implements high-precision parsing of SQLite 32-byte WAL headers, 24-byte
frame headers, dual magic numbers (0x377f0682, 0x377f0683), checksum chaining,
and replica sync state machines.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import Final, Sequence


WAL_MAGIC_LE: Final[int] = 0x377F0682  # 931071618 (little-endian checksums)
WAL_MAGIC_BE: Final[int] = 0x377F0683  # 931071619 (big-endian checksums)
WAL_HEADER_SIZE: Final[int] = 32
WAL_FRAME_HEADER_SIZE: Final[int] = 24


class WalFormatError(ValueError):
    """Raised when SQLite WAL header or frame parsing encounters invalid data."""


@dataclass(frozen=True)
class WalHeader:
    """Parsed SQLite 32-byte WAL header."""

    magic: int
    version: int
    page_size: int
    checkpoint_seq: int
    salt1: int
    salt2: int
    checksum1: int
    checksum2: int
    is_big_endian_checksum: bool


@dataclass(frozen=True)
class WalFrame:
    """Parsed SQLite WAL frame."""

    frame_index: int  # 1-based index in WAL file
    page_number: int  # 1-based database page index
    commit_page_count: int  # > 0 on commit frame (total db pages), 0 otherwise
    salt1: int
    salt2: int
    checksum1: int
    checksum2: int
    page_data_sha256: str
    is_commit: bool


@dataclass(frozen=True)
class ReplicationPosition:
    """Replica synchronization state."""

    node_id: str
    salt1: int
    salt2: int
    last_frame_index: int
    last_commit_pages: int
    is_synced: bool


def _compute_wal_checksum(
    data: bytes,
    is_big_endian: bool,
    s1_init: int = 0,
    s2_init: int = 0,
) -> tuple[int, int]:
    """Compute SQLite native 64-bit checksum (s1, s2) over 8-byte aligned bytes."""
    if len(data) % 8 != 0:
        raise WalFormatError(f"Data length must be multiple of 8 bytes for WAL checksum, got {len(data)}")

    s1 = s1_init & 0xFFFFFFFF
    s2 = s2_init & 0xFFFFFFFF
    endian = ">" if is_big_endian else "<"

    num_pairs = len(data) // 8
    for i in range(num_pairs):
        offset = i * 8
        v0, v1 = struct.unpack_from(f"{endian}II", data, offset)
        s1 = (s1 + v0 + s2) & 0xFFFFFFFF
        s2 = (s2 + v1 + s1) & 0xFFFFFFFF

    return s1, s2


def parse_wal_header(header_bytes: bytes) -> WalHeader:
    """Parse and validate 32-byte SQLite WAL header."""
    if len(header_bytes) < WAL_HEADER_SIZE:
        raise WalFormatError(f"WAL header too short: {len(header_bytes)} bytes (expected {WAL_HEADER_SIZE})")

    # Magic is always big-endian in the header
    magic = struct.unpack_from(">I", header_bytes, 0)[0]
    if magic == WAL_MAGIC_BE:
        is_be = True
    elif magic == WAL_MAGIC_LE:
        is_be = False
    else:
        raise WalFormatError(f"Invalid WAL magic number: 0x{magic:08x}")

    version, page_size, seq, salt1, salt2, c1, c2 = struct.unpack_from(">IIIIIII", header_bytes, 4)

    if page_size < 512 or page_size > 65536 or (page_size & (page_size - 1)) != 0:
        raise WalFormatError(f"Invalid WAL page size: {page_size}")

    # Verify header checksum over first 24 bytes
    calc_s1, calc_s2 = _compute_wal_checksum(header_bytes[:24], is_big_endian=is_be)
    if calc_s1 != c1 or calc_s2 != c2:
        raise WalFormatError(
            f"WAL header checksum mismatch: expected ({c1:#x}, {c2:#x}), computed ({calc_s1:#x}, {calc_s2:#x})"
        )

    return WalHeader(
        magic=magic,
        version=version,
        page_size=page_size,
        checkpoint_seq=seq,
        salt1=salt1,
        salt2=salt2,
        checksum1=c1,
        checksum2=c2,
        is_big_endian_checksum=is_be,
    )


def parse_wal_frames(wal_bytes: bytes, header: WalHeader | None = None) -> tuple[WalHeader, list[WalFrame]]:
    """Parse SQLite WAL file bytes into header and sequence of verified frames."""
    if len(wal_bytes) < WAL_HEADER_SIZE:
        raise WalFormatError("WAL file smaller than header size")

    active_header = header or parse_wal_header(wal_bytes[:WAL_HEADER_SIZE])
    page_size = active_header.page_size
    frame_size = WAL_FRAME_HEADER_SIZE + page_size
    is_be = active_header.is_big_endian_checksum

    offset = WAL_HEADER_SIZE
    frame_index = 1
    frames: list[WalFrame] = []

    # Running checksum starts from header checksum
    running_s1 = active_header.checksum1
    running_s2 = active_header.checksum2

    while offset + frame_size <= len(wal_bytes):
        frame_header_bytes = wal_bytes[offset : offset + WAL_FRAME_HEADER_SIZE]
        page_data = wal_bytes[offset + WAL_FRAME_HEADER_SIZE : offset + frame_size]

        page_num, commit_pages, f_salt1, f_salt2, f_c1, f_c2 = struct.unpack_from(
            ">IIIIII", frame_header_bytes, 0
        )

        # Salt check
        if f_salt1 != active_header.salt1 or f_salt2 != active_header.salt2:
            # Salt mismatch marks the end of valid frames in this WAL generation
            break

        # Checksum verification: frame header first 8 bytes + page data
        chk_s1, chk_s2 = _compute_wal_checksum(
            frame_header_bytes[:8], is_big_endian=is_be, s1_init=running_s1, s2_init=running_s2
        )
        chk_s1, chk_s2 = _compute_wal_checksum(
            page_data, is_big_endian=is_be, s1_init=chk_s1, s2_init=chk_s2
        )

        if chk_s1 != f_c1 or chk_s2 != f_c2:
            # Checksum failure indicates torn write or corrupted frame
            break

        running_s1 = chk_s1
        running_s2 = chk_s2

        page_sha = hashlib.sha256(page_data).hexdigest()
        frames.append(
            WalFrame(
                frame_index=frame_index,
                page_number=page_num,
                commit_page_count=commit_pages,
                salt1=f_salt1,
                salt2=f_salt2,
                checksum1=f_c1,
                checksum2=f_c2,
                page_data_sha256=page_sha,
                is_commit=(commit_pages > 0),
            )
        )

        offset += frame_size
        frame_index += 1

    return active_header, frames
