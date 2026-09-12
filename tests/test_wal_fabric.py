"""Tests for SQLite WAL frame inspector and replication state protocols."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from ironledger.replication.wal_parser import (
    WAL_FRAME_HEADER_SIZE,
    WAL_HEADER_SIZE,
    WAL_MAGIC_BE,
    WAL_MAGIC_LE,
    WalFormatError,
    _compute_wal_checksum,
    parse_wal_frames,
    parse_wal_header,
)


def _build_wal_header(
    magic: int = WAL_MAGIC_LE,
    version: int = 3007000,
    page_size: int = 4096,
    seq: int = 1,
    salt1: int = 0x12345678,
    salt2: int = 0x87654321,
) -> bytes:
    is_be = (magic == WAL_MAGIC_BE)
    header_prefix = struct.pack(">IIIIII", magic, version, page_size, seq, salt1, salt2)
    c1, c2 = _compute_wal_checksum(header_prefix, is_big_endian=is_be)
    return header_prefix + struct.pack(">II", c1, c2)


def test_parse_wal_header_valid_le():
    header_bytes = _build_wal_header(magic=WAL_MAGIC_LE, page_size=4096)
    header = parse_wal_header(header_bytes)
    assert header.magic == WAL_MAGIC_LE
    assert header.page_size == 4096
    assert header.is_big_endian_checksum is False
    assert header.salt1 == 0x12345678
    assert header.salt2 == 0x87654321


def test_parse_wal_header_valid_be():
    header_bytes = _build_wal_header(magic=WAL_MAGIC_BE, page_size=4096)
    header = parse_wal_header(header_bytes)
    assert header.magic == WAL_MAGIC_BE
    assert header.page_size == 4096
    assert header.is_big_endian_checksum is True


def test_parse_wal_header_invalid_magic():
    bad_bytes = struct.pack(">IIIIIIII", 0x12345678, 3007000, 4096, 1, 0, 0, 0, 0)
    with pytest.raises(WalFormatError, match="Invalid WAL magic number"):
        parse_wal_header(bad_bytes)


def test_parse_wal_header_corrupt_checksum():
    header_bytes = bytearray(_build_wal_header())
    header_bytes[25] ^= 0xFF
    with pytest.raises(WalFormatError, match="WAL header checksum mismatch"):
        parse_wal_header(bytes(header_bytes))


def test_parse_wal_frames_valid_stream():
    page_size = 512
    header_bytes = _build_wal_header(magic=WAL_MAGIC_LE, page_size=page_size)
    header = parse_wal_header(header_bytes)

    # Construct frame 1
    page1_data = b"A" * page_size
    f1_prefix = struct.pack(">II", 1, 0)  # page 1, non-commit
    chk_s1, chk_s2 = _compute_wal_checksum(f1_prefix, is_big_endian=False, s1_init=header.checksum1, s2_init=header.checksum2)
    chk_s1, chk_s2 = _compute_wal_checksum(page1_data, is_big_endian=False, s1_init=chk_s1, s2_init=chk_s2)
    f1_header = f1_prefix + struct.pack(">IIII", header.salt1, header.salt2, chk_s1, chk_s2)

    # Construct frame 2 (commit frame, 2 pages in db)
    page2_data = b"B" * page_size
    f2_prefix = struct.pack(">II", 2, 2)  # page 2, commit page count 2
    chk2_s1, chk2_s2 = _compute_wal_checksum(f2_prefix, is_big_endian=False, s1_init=chk_s1, s2_init=chk_s2)
    chk2_s1, chk2_s2 = _compute_wal_checksum(page2_data, is_big_endian=False, s1_init=chk2_s1, s2_init=chk2_s2)
    f2_header = f2_prefix + struct.pack(">IIII", header.salt1, header.salt2, chk2_s1, chk2_s2)

    wal_data = header_bytes + f1_header + page1_data + f2_header + page2_data

    hdr, frames = parse_wal_frames(wal_data)
    assert len(frames) == 2
    assert frames[0].frame_index == 1
    assert frames[0].page_number == 1
    assert frames[0].is_commit is False

    assert frames[1].frame_index == 2
    assert frames[1].page_number == 2
    assert frames[1].is_commit is True
    assert frames[1].commit_page_count == 2
