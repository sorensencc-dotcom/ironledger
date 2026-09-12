"""Tests for compliance and anomaly CLI subcommands."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ironledger.cli.__main__ import main
from ironledger.governance.migrations import migrate_governed


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "cli_test.db"
    conn = sqlite3.connect(p)
    migrate_governed(conn, p)
    conn.execute(
        "INSERT INTO ledgers (ledger_id, name, base_currency) VALUES (?, ?, ?)",
        ("corp", "Corporate", "USD"),
    )
    conn.commit()
    conn.close()
    return p


def test_compliance_cli_generate_and_verify(db_path: Path, tmp_path: Path, capsys):
    ret = main([
        "--db", str(db_path),
        "compliance", "generate",
        "--ledger-id", "corp",
        "--framework", "SOC2_TYPE2",
        "--start", "2026-01-01T00:00:00Z",
        "--end", "2026-12-31T23:59:59Z",
        "--output-dir", str(tmp_path),
    ])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Compliance bundle generated" in captured.out

    # Find the generated archive file
    archives = list(tmp_path.glob("compliance_bundle_corp_*.tar"))
    assert len(archives) == 1
    archive_file = archives[0]

    # Verify via CLI
    ret_ver = main([
        "compliance", "verify",
        "--archive", str(archive_file),
    ])
    assert ret_ver == 0
    captured_ver = capsys.readouterr()
    assert "Verified compliance bundle" in captured_ver.out


def test_anomaly_cli_scan_list_resolve(db_path: Path, capsys):
    conn = sqlite3.connect(db_path)
    # Insert source document & records
    conn.execute(
        """
        INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("doc_1", "text/csv", "utf-8", "manual", "2026-06-01T10:00:00Z", "0" * 64, "evidence/doc_1.raw", "2026-06-01T10:00:00Z"),
    )
    conn.execute(
        """
        INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("rec_1", "doc_1", 0, "{}", "1" * 64, "2026-06-01T10:00:00Z"),
    )
    conn.execute(
        """
        INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("rec_2", "doc_1", 1, "{}", "2" * 64, "2026-06-01T10:00:00Z"),
    )
    # Staged transactions
    conn.execute(
        """
        INSERT INTO staged_transactions (
            staged_transaction_id, source_record_id, status, proposed_date, payee, narration,
            identity_algo_version, identity_method, identity_fingerprint, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("stg_1", "rec_1", "pending", "2026-06-01", "Luxury Vendor", "Diamond Watch", 1, "sha256_fallback", "3" * 64, "2026-06-01T12:00:00Z"),
    )
    conn.execute(
        """
        INSERT INTO staged_transactions (
            staged_transaction_id, source_record_id, status, proposed_date, payee, narration,
            identity_algo_version, identity_method, identity_fingerprint, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("stg_2", "rec_2", "pending", "2026-06-01", "Luxury Vendor", "Diamond Watch", 1, "sha256_fallback", "4" * 64, "2026-06-01T12:05:00Z"),
    )
    # Staged postings
    conn.execute(
        """
        INSERT INTO staged_postings (
            staged_posting_id, staged_transaction_id, source_record_id, role, posting_index,
            account, minor_units, currency, minor_unit_scale, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("post_1", "stg_1", "rec_1", "imported", 0, "Assets:Checking", 500000, "USD", 2, "2026-06-01T12:00:00Z"),
    )
    conn.execute(
        """
        INSERT INTO staged_postings (
            staged_posting_id, staged_transaction_id, source_record_id, role, posting_index,
            account, minor_units, currency, minor_unit_scale, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("post_2", "stg_2", "rec_2", "imported", 0, "Assets:Checking", 500000, "USD", 2, "2026-06-01T12:05:00Z"),
    )
    conn.commit()
    conn.close()

    # Scan via CLI
    ret_scan = main([
        "--db", str(db_path),
        "anomaly", "scan",
        "--ledger-id", "corp",
    ])
    assert ret_scan == 0
    captured = capsys.readouterr()
    assert "Scanned 2 transactions" in captured.out
    assert "Detected and persisted" in captured.out

    # List via CLI
    ret_list = main([
        "--db", str(db_path),
        "anomaly", "list",
        "--ledger-id", "corp",
        "--status", "OPEN",
    ])
    assert ret_list == 0
    captured_list = capsys.readouterr()
    assert "Found" in captured_list.out

    # Extract a flag ID from listing
    lines = [line.strip() for line in captured_list.out.splitlines() if line.strip().startswith("- ")]
    assert len(lines) >= 1
    flag_id = lines[0].split(":")[0].replace("- ", "")

    # Resolve via CLI
    ret_res = main([
        "--db", str(db_path),
        "anomaly", "resolve",
        "--ledger-id", "corp",
        "--flag-id", flag_id,
        "--status", "RESOLVED_VALID",
        "--actor", "lead_reviewer",
        "--reason", "Legitimate corporate purchase",
    ])
    assert ret_res == 0
    captured_res = capsys.readouterr()
    assert "Resolved flag" in captured_res.out
