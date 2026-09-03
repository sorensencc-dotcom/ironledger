"""Copy an inbox file into evidence/source_documents, keyed by content hash."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["AcquireResult", "detect_mime", "acquire"]


@dataclass(frozen=True)
class AcquireResult:
    source_document_id: str
    content_sha256: str
    is_new: bool
    raw_path: Path


def detect_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "text/csv"
    if suffix in (".ofx", ".qfx"):
        head = path.read_bytes()[:64].lstrip()
        if head.startswith(b"<?xml") or head.upper().startswith(b"OFXHEADER") or head.startswith(b"<?OFX"):
            return "application/x-ofx"
    return "application/octet-stream"


def acquire(
    conn: sqlite3.Connection,
    src_path: Path,
    *,
    evidence_dir: Path,
    provenance: str,
    now_utc: str | None = None,
) -> AcquireResult:
    raw = Path(src_path).read_bytes()
    content_sha256 = hashlib.sha256(raw).hexdigest()
    docs_dir = Path(evidence_dir) / "source_documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    stored = docs_dir / content_sha256
    if not stored.exists():
        stored.write_bytes(raw)

    row = conn.execute(
        "SELECT source_document_id FROM source_documents WHERE content_sha256 = ?",
        (content_sha256,),
    ).fetchone()
    if row is not None:
        return AcquireResult(row[0], content_sha256, is_new=False, raw_path=stored)

    ts = now_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, "
        " acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            content_sha256,
            detect_mime(Path(src_path)),
            "utf-8",
            provenance,
            ts,
            content_sha256,
            f"evidence/source_documents/{content_sha256}",
            ts,
        ),
    )
    return AcquireResult(content_sha256, content_sha256, is_new=True, raw_path=stored)
