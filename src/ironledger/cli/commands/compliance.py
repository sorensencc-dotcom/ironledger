"""CLI subcommands for compliance audit bundles."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from ironledger.compliance.bundle import (
    ComplianceBundleError,
    generate_compliance_bundle,
    verify_compliance_bundle,
)
from ironledger.db.connection import connect
from ironledger.governance.migrations import migrate_governed


def run_compliance_generate(
    db_path: str | Path,
    ledger_id: str,
    framework: str,
    period_start_utc: str,
    period_end_utc: str,
    output_dir: str | Path | None = None,
) -> int:
    """Generate a sealed compliance audit bundle."""
    resolved_db = Path(db_path).resolve()
    conn = connect(resolved_db)
    try:
        migrate_governed(conn, resolved_db)
        result = generate_compliance_bundle(
            conn=conn,
            ledger_id=ledger_id,
            framework=framework,
            period_start_utc=period_start_utc,
            period_end_utc=period_end_utc,
            output_dir=output_dir,
        )
        print(f"Compliance bundle generated: {result.bundle_id}")
        print(f"Framework: {result.framework}")
        print(f"Ledger ID: {result.ledger_id}")
        print(f"Record Count: {result.record_count}")
        print(f"Merkle Root: {result.merkle_root_hex}")
        print(f"Archive SHA-256: {result.sealed_archive_sha256}")
        return 0
    except (ComplianceBundleError, Exception) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def run_compliance_verify(
    archive_path: str | Path,
    expected_root: str | None = None,
    expected_sha: str | None = None,
) -> int:
    """Cryptographically verify a sealed compliance archive."""
    p = Path(archive_path).resolve()
    if not p.is_file():
        print(f"error: archive file not found: {p}", file=sys.stderr)
        return 2

    try:
        archive_bytes = p.read_bytes()
        result = verify_compliance_bundle(
            archive_bytes=archive_bytes,
            expected_merkle_root=expected_root,
            expected_sha256=expected_sha,
        )
        print(f"Verified compliance bundle: {result['bundle_id']}")
        print(f"Framework: {result['framework']}")
        print(f"Merkle Root: {result['merkle_root_hex']} (MATCH)")
        print(f"Archive SHA-256: {result['sealed_archive_sha256']} (MATCH)")
        print(f"Record Count: {result['record_count']}")
        return 0
    except (ComplianceBundleError, Exception) as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 1
