"""Compliance audit bundle generation, deterministic sealing, and verification.

Implements tamper-evident archive bundles for SOC2 Type II, ISO27001, SOX,
and custom compliance frameworks.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import tarfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from ironledger.compliance.merkle import MerkleTree, hash_leaf
from ironledger.conventions import ConventionError, validate_utc_timestamp


VALID_FRAMEWORKS: Final[tuple[str, ...]] = ("SOC2_TYPE2", "ISO27001", "SOX", "CUSTOM")
MAX_ARCHIVE_ENTRIES: Final[int] = 1000
MAX_ARCHIVE_BYTES: Final[int] = 100 * 1024 * 1024  # 100 MB


class ComplianceBundleError(ValueError):
    """Raised when compliance bundle generation or verification fails."""


@dataclass(frozen=True)
class ComplianceBundleResult:
    """Canonical compliance bundle summary."""

    ledger_id: str
    bundle_id: str
    framework: str
    period_start_utc: str
    period_end_utc: str
    merkle_root_hex: str
    sealed_archive_sha256: str
    record_count: int
    manifest: dict[str, Any]
    archive_bytes: bytes


def _canonical_json_bytes(obj: Any) -> bytes:
    """Return deterministic canonical UTF-8 bytes for a JSON-serializable object."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def generate_compliance_bundle(
    conn: sqlite3.Connection,
    ledger_id: str,
    framework: str,
    period_start_utc: str,
    period_end_utc: str,
    output_dir: Path | str | None = None,
    bundle_id: str | None = None,
) -> ComplianceBundleResult:
    """Generate a deterministic, sealed compliance audit archive bundle."""
    if framework not in VALID_FRAMEWORKS:
        raise ComplianceBundleError(f"Invalid framework: {framework}. Must be one of {VALID_FRAMEWORKS}")

    validate_utc_timestamp(period_start_utc)
    validate_utc_timestamp(period_end_utc)
    if period_start_utc > period_end_utc:
        raise ComplianceBundleError(f"period_start_utc ({period_start_utc}) must be <= period_end_utc ({period_end_utc})")

    assigned_bundle_id = bundle_id or f"bundle_{uuid.uuid4().hex[:16]}"
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Fetch stream data within period
    # 1. Governance Audit Events
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT seq, actor, action, target, before_state_json, after_state_json, envelope_hash, timestamp_utc
        FROM governance_audit_events
        WHERE ledger_id = ? AND timestamp_utc >= ? AND timestamp_utc <= ?
        ORDER BY seq ASC
        """,
        (ledger_id, period_start_utc, period_end_utc),
    )
    gov_rows = cursor.fetchall()
    gov_events: list[dict[str, Any]] = [
        {
            "stream": "governance_audit",
            "seq": row[0],
            "actor": row[1],
            "action": row[2],
            "target": row[3],
            "before_state": json.loads(row[4]) if row[4] else {},
            "after_state": json.loads(row[5]) if row[5] else {},
            "envelope_hash": row[6],
            "timestamp_utc": row[7],
        }
        for row in gov_rows
    ]

    # 2. Mutation Events (if table exists and scoped to ledger)
    mutation_events: list[dict[str, Any]] = []
    try:
        cursor.execute(
            """
            SELECT m.seq, m.mutation_id, m.operation, m.author, m.target_table, m.record_count,
                   m.prev_event_hash, m.event_hash, m.timestamp_utc
            FROM mutation_events m
            WHERE m.ledger_id = ? AND m.timestamp_utc >= ? AND m.timestamp_utc <= ?
            ORDER BY m.seq ASC
            """,
            (ledger_id, period_start_utc, period_end_utc),
        )
        for row in cursor.fetchall():
            mutation_events.append(
                {
                    "stream": "mutation",
                    "seq": row[0],
                    "mutation_id": row[1],
                    "operation": row[2],
                    "author": row[3],
                    "target_table": row[4],
                    "record_count": row[5],
                    "prev_event_hash": row[6],
                    "event_hash": row[7],
                    "timestamp_utc": row[8],
                }
            )
    except sqlite3.OperationalError:
        pass

    # 3. Core Audit Events
    audit_events: list[dict[str, Any]] = []
    try:
        cursor.execute(
            """
            SELECT seq, ts_utc, actor, action, target, result, projection_version,
                   compile_run_id, input_hash, output_hash, prev_event_hash, event_hash
            FROM audit_events
            WHERE ts_utc >= ? AND ts_utc <= ?
            ORDER BY seq ASC
            """,
            (period_start_utc, period_end_utc),
        )
        for row in cursor.fetchall():
            audit_events.append(
                {
                    "stream": "audit",
                    "seq": row[0],
                    "ts_utc": row[1],
                    "actor": row[2],
                    "action": row[3],
                    "target": row[4],
                    "result": row[5],
                    "projection_version": row[6],
                    "compile_run_id": row[7],
                    "input_hash": row[8],
                    "output_hash": row[9],
                    "prev_event_hash": row[10],
                    "event_hash": row[11],
                }
            )
    except sqlite3.OperationalError:
        pass

    # Build canonical leaves in deterministic order: (stream, seq/timestamp)
    all_records: list[dict[str, Any]] = sorted(
        gov_events + mutation_events + audit_events,
        key=lambda x: (x.get("stream", ""), x.get("seq", 0), x.get("timestamp_utc", x.get("ts_utc", ""))),
    )

    canonical_leaves = [_canonical_json_bytes(rec) for rec in all_records]
    merkle_tree = MerkleTree(canonical_leaves)
    merkle_root_hex = merkle_tree.root_hex
    record_count = len(all_records)

    # Build manifest
    manifest: dict[str, Any] = {
        "manifest_version": "1.0.0",
        "bundle_id": assigned_bundle_id,
        "ledger_id": ledger_id,
        "framework": framework,
        "period_start_utc": period_start_utc,
        "period_end_utc": period_end_utc,
        "merkle_root_hex": merkle_root_hex,
        "record_count": record_count,
        "stream_counts": {
            "governance_audit": len(gov_events),
            "mutation": len(mutation_events),
            "audit": len(audit_events),
        },
        "created_at_utc": now_utc,
    }

    manifest_bytes = _canonical_json_bytes(manifest)

    # Package into deterministic uncompressed TAR
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        # Helper to add entry with fixed metadata
        def add_file(name: str, data: bytes) -> None:
            ti = tarfile.TarInfo(name=name)
            ti.size = len(data)
            ti.mtime = 0
            ti.uid = 0
            ti.gid = 0
            ti.uname = ""
            ti.gname = ""
            ti.mode = 0o644
            ti.type = tarfile.REGTYPE
            tar.addfile(ti, io.BytesIO(data))

        # Add manifest.json
        add_file("manifest.json", manifest_bytes)

        # Add stream files
        gov_stream_data = b"".join(_canonical_json_bytes(e) + b"\n" for e in gov_events)
        add_file("streams/governance_audit.jsonl", gov_stream_data)

        mut_stream_data = b"".join(_canonical_json_bytes(e) + b"\n" for e in mutation_events)
        add_file("streams/mutation_events.jsonl", mut_stream_data)

        aud_stream_data = b"".join(_canonical_json_bytes(e) + b"\n" for e in audit_events)
        add_file("streams/audit_events.jsonl", aud_stream_data)

    archive_bytes = tar_buffer.getvalue()
    import hashlib
    sealed_archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()

    # Persist bundle record
    cursor.execute(
        """
        INSERT INTO compliance_audit_bundles (
            ledger_id, bundle_id, framework, period_start_utc, period_end_utc,
            merkle_root_hex, sealed_archive_sha256, record_count, manifest_json, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ledger_id,
            assigned_bundle_id,
            framework,
            period_start_utc,
            period_end_utc,
            merkle_root_hex,
            sealed_archive_sha256,
            record_count,
            json.dumps(manifest, sort_keys=True),
            now_utc,
        ),
    )

    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        file_path = out_path / f"compliance_bundle_{ledger_id}_{assigned_bundle_id}.tar"
        file_path.write_bytes(archive_bytes)

    return ComplianceBundleResult(
        ledger_id=ledger_id,
        bundle_id=assigned_bundle_id,
        framework=framework,
        period_start_utc=period_start_utc,
        period_end_utc=period_end_utc,
        merkle_root_hex=merkle_root_hex,
        sealed_archive_sha256=sealed_archive_sha256,
        record_count=record_count,
        manifest=manifest,
        archive_bytes=archive_bytes,
    )


def verify_compliance_bundle(
    archive_bytes: bytes,
    expected_merkle_root: str | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Cryptographically verify a sealed compliance audit archive bundle."""
    import hashlib

    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise ComplianceBundleError(f"Archive exceeds maximum size limit ({MAX_ARCHIVE_BYTES} bytes)")

    actual_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
        raise ComplianceBundleError(
            f"Archive SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )

    # Safe extraction & verification
    tar_buffer = io.BytesIO(archive_bytes)
    try:
        with tarfile.open(fileobj=tar_buffer, mode="r") as tar:
            members = tar.getmembers()
            if len(members) > MAX_ARCHIVE_ENTRIES:
                raise ComplianceBundleError(f"Archive exceeds max entries limit ({MAX_ARCHIVE_ENTRIES})")

            # Check for path traversal or hostile member types
            for m in members:
                if m.name.startswith("/") or ".." in m.name:
                    raise ComplianceBundleError(f"Hostile archive member name detected: {m.name}")
                if not (m.isreg() or m.isdir()):
                    raise ComplianceBundleError(f"Unsupported archive member type: {m.name}")

            manifest_member = tar.extractfile("manifest.json")
            if not manifest_member:
                raise ComplianceBundleError("manifest.json missing from archive")

            manifest = json.loads(manifest_member.read().decode("utf-8"))

            # Extract records from all streams
            extracted_records: list[dict[str, Any]] = []
            for m in members:
                if m.name.startswith("streams/") and m.name.endswith(".jsonl") and m.isreg():
                    stream_file = tar.extractfile(m)
                    if stream_file:
                        for line in stream_file:
                            line = line.strip()
                            if line:
                                extracted_records.append(json.loads(line.decode("utf-8")))

            # Sort records in canonical order
            extracted_records.sort(
                key=lambda x: (x.get("stream", ""), x.get("seq", 0), x.get("timestamp_utc", x.get("ts_utc", "")))
            )

            canonical_leaves = [_canonical_json_bytes(rec) for rec in extracted_records]
            reconstructed_tree = MerkleTree(canonical_leaves)
            reconstructed_root = reconstructed_tree.root_hex

            if reconstructed_root.lower() != manifest["merkle_root_hex"].lower():
                raise ComplianceBundleError(
                    f"Merkle root mismatch: manifest={manifest['merkle_root_hex']}, reconstructed={reconstructed_root}"
                )

            if expected_merkle_root and reconstructed_root.lower() != expected_merkle_root.lower():
                raise ComplianceBundleError(
                    f"Expected Merkle root mismatch: expected={expected_merkle_root}, actual={reconstructed_root}"
                )

            if len(extracted_records) != manifest["record_count"]:
                raise ComplianceBundleError(
                    f"Record count mismatch: manifest={manifest['record_count']}, extracted={len(extracted_records)}"
                )

            return {
                "is_valid": True,
                "bundle_id": manifest["bundle_id"],
                "ledger_id": manifest["ledger_id"],
                "framework": manifest["framework"],
                "merkle_root_hex": reconstructed_root,
                "sealed_archive_sha256": actual_sha256,
                "record_count": len(extracted_records),
                "manifest": manifest,
            }

    except Exception as e:
        if isinstance(e, ComplianceBundleError):
            raise
        raise ComplianceBundleError(f"Failed to verify compliance archive: {e}") from e
