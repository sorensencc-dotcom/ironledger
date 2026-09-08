# tests/test_cli_compile.py
"""CLI tests for compile, compile status, and compile recover."""

from __future__ import annotations

import sqlite3
import os
from pathlib import Path
from unittest.mock import patch
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.beancheck import BeanCheckResult
from ironledger.cli.__main__ import main
from ironledger.compile.writer import compile_approved


@pytest.fixture
def env(tmp_path: Path):
    db_path = tmp_path / "ironledger.db"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "safe-mode.json").write_text('{"enabled": false}', encoding="utf-8")
    conn = connect(str(db_path))
    migrations.migrate(conn)
    conn.close()
    return db_path, config_dir


def _seed(p: Path):
    conn = connect(str(p))
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        f"VALUES ('doc-1', 'text/csv', 'utf-8', 'p', '2026-09-01T10:00:00Z', '{'a'*64}', 'ref-1', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc) "
        f"VALUES ('rec-1', 'doc-1', 0, '{{}}', '{'b'*64}', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, proposed_date, payee, narration, identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc) "
        f"VALUES ('stx-1', 'rec-1', 'approved', '2026-09-01', 'Store', '', 1, 'fitid', '{'c'*64}', '2026-09-01T10:00:00Z', '2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        "VALUES ('sp-1', 'stx-1', 'rec-1', 'imported', 0, 'Assets:Checking', -1000, 'USD', 2, '2026-09-01T10:00:00Z'), "
        "       ('sp-2', 'stx-1', 'rec-1', 'contra', 1, 'Expenses:Food', 1000, 'USD', 2, '2026-09-01T10:00:00Z')"
    )
    conn.commit()
    conn.close()


def test_cli_compile_success(env, tmp_path: Path, capsys):
    db_path, config_dir = env
    _seed(db_path)
    ledger_dir = tmp_path / "ledger"
    success_res = BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0")

    with patch("ironledger.compile.writer.run_bean_check", return_value=success_res):
        rc = main([
            "--db", str(db_path),
            "--config-dir", str(config_dir),
            "compile",
            "--ledger-dir", str(ledger_dir),
            "--confirm", "authorize compile"
        ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "succeeded" in captured.out


def test_cli_compile_status_read_only(env, tmp_path: Path, capsys):
    db_path, config_dir = env
    ledger_dir = tmp_path / "ledger"
    rc = main([
        "--db", str(db_path),
        "--config-dir", str(config_dir),
        "compile", "status",
        "--ledger-dir", str(ledger_dir)
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Compile Status:" in captured.out


def test_cli_compile_auth_failure_exits_code_3(env, tmp_path: Path):
    db_path, config_dir = env
    ledger_dir = tmp_path / "ledger"
    rc = main([
        "--db", str(db_path),
        "--config-dir", str(config_dir),
        "compile",
        "--ledger-dir", str(ledger_dir),
        "--confirm", "wrong phrase"
    ])
    assert rc == 3


def test_cli_compile_bad_input_exits_code_1(env, tmp_path: Path):
    db_path, config_dir = env
    _seed(db_path)
    conn = connect(str(db_path))
    conn.execute("UPDATE staged_postings SET minor_units = 999 WHERE role = 'contra'")
    conn.commit(); conn.close()
    assert main(["--db", str(db_path), "--config-dir", str(config_dir), "compile", "--ledger-dir", str(tmp_path / "ledger"), "--confirm", "authorize compile"]) == 1


def test_cli_compile_recover_none(env, tmp_path: Path, capsys):
    db_path, config_dir = env
    assert main(["--db", str(db_path), "--config-dir", str(config_dir), "compile", "recover", "--ledger-dir", str(tmp_path / "ledger"), "--confirm", "authorize compile recover"]) == 0
    assert "no dangling compile run to recover" in capsys.readouterr().out.lower()


def test_cli_compile_recover_started_run(env, tmp_path: Path):
    db_path, config_dir = env
    _seed(db_path)
    ledger_dir = tmp_path / "ledger"
    success = BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0")
    conn = connect(str(db_path))
    original = os.replace
    count = {"n": 0}
    def crash_second(src, dst):
        count["n"] += 1
        if count["n"] == 2:
            raise OSError("crash")
        return original(src, dst)
    with patch("ironledger.compile.writer.run_bean_check", return_value=success), patch("os.replace", side_effect=crash_second):
        with pytest.raises(OSError):
            compile_approved(conn, ledger_dir)
    conn.close()
    assert main(["--db", str(db_path), "--config-dir", str(config_dir), "compile", "recover", "--ledger-dir", str(ledger_dir), "--confirm", "authorize compile recover"]) == 0
