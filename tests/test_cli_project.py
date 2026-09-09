# tests/test_cli_project.py
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from ironledger.cli.__main__ import main
from ironledger.compile.beancheck import BeanCheckResult
from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger


@pytest.fixture
def env(tmp_path: Path):
    db_path = tmp_path / "ironledger.db"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "safe-mode.json").write_text('{"enabled": false}', encoding="utf-8")
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    seed_successful_compile_run(db_path, ledger_dir)
    return db_path, config_dir, ledger_dir, tmp_path / "projection"


def test_help_lists_project_search_balances(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "project" in out
    assert "search" in out
    assert "balances" in out
    assert "python -m ironledger.cli" in out
    assert "authorize project" in out


def test_project_accepts_db_after_subcommand(env, capsys):
    """README / compile next-step / stale Fix all put --db after `project`."""
    db_path, config_dir, ledger_dir, projection_dir = env
    rc = main([
        "--config-dir", str(config_dir),
        "project",
        "--db", str(db_path),
        "--ledger-dir", str(ledger_dir),
        "--projection-dir", str(projection_dir),
        "--confirm", "authorize project",
    ])
    assert rc == 0
    assert "Projection rebuilt" in capsys.readouterr().out


def test_readme_golden_path_subprocess(tmp_path: Path):
    """Subprocess the exact README argv. main() with reordered flags hid this."""
    db_path = tmp_path / "ironledger.db"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "safe-mode.json").write_text('{"enabled": false}', encoding="utf-8")
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    seed_successful_compile_run(db_path, ledger_dir)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path("src").resolve())
    env["PYTHONIOENCODING"] = "utf-8"
    project = subprocess.run(
        [
            sys.executable, "-m", "ironledger.cli",
            "project", "--db", "ironledger.db", "--ledger-dir", "ledger",
            "--confirm", "authorize project",
        ],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False,
    )
    assert project.returncode == 0, project.stderr
    assert "Projection rebuilt" in project.stdout
    search = subprocess.run(
        [
            sys.executable, "-m", "ironledger.cli",
            "search", "--ledger-dir", "ledger", "coffee",
        ],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False,
    )
    assert search.returncode == 0, search.stderr
    assert "Coffee" in search.stdout
    assert "1234" in search.stdout
    balances = subprocess.run(
        [
            sys.executable, "-m", "ironledger.cli",
            "balances", "--ledger-dir", "ledger",
        ],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False,
    )
    assert balances.returncode == 0, balances.stderr
    assert "Assets:Checking" in balances.stdout
    assert "-1234" in balances.stdout


def test_search_parses_without_db(env, capsys):
    db_path, config_dir, ledger_dir, projection_dir = env
    assert main([
        "--config-dir", str(config_dir),
        "--db", str(db_path),
        "project",
        "--ledger-dir", str(ledger_dir),
        "--projection-dir", str(projection_dir),
        "--confirm", "authorize project",
    ]) == 0
    rc = main([
        "--ledger-dir", str(ledger_dir),
        "search",
        "--projection-dir", str(projection_dir),
        "Coffee",
    ])
    assert rc == 0
    assert "Coffee" in capsys.readouterr().out


def test_project_wrong_phrase_exits_3(env):
    db_path, config_dir, ledger_dir, projection_dir = env
    rc = main([
        "--db", str(db_path),
        "--config-dir", str(config_dir),
        "project",
        "--ledger-dir", str(ledger_dir),
        "--projection-dir", str(projection_dir),
        "--confirm", "wrong phrase",
    ])
    assert rc == 3


def test_search_and_balances_do_not_require_operator(env, capsys):
    db_path, config_dir, ledger_dir, projection_dir = env
    main([
        "--config-dir", str(config_dir), "--db", str(db_path), "project",
        "--ledger-dir", str(ledger_dir), "--projection-dir", str(projection_dir),
        "--confirm", "authorize project",
    ])
    assert main(["--ledger-dir", str(ledger_dir), "balances", "--projection-dir", str(projection_dir)]) == 0
    out = capsys.readouterr().out
    assert "Assets:Checking" in out
    assert "-1234" in out


def test_compile_success_prints_next_project(tmp_path: Path, capsys):
    from ironledger.db import migrations
    from ironledger.db.connection import connect

    db_path = tmp_path / "ironledger.db"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "safe-mode.json").write_text('{"enabled": false}', encoding="utf-8")
    conn = connect(str(db_path))
    migrations.migrate(conn)
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
    ledger_dir = tmp_path / "ledger"
    success = BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0")
    with patch("ironledger.compile.writer.run_bean_check", return_value=success):
        rc = main([
            "--db", str(db_path), "--config-dir", str(config_dir),
            "compile", "--ledger-dir", str(ledger_dir), "--confirm", "authorize compile",
        ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "authorize project" in out
    assert "python -m ironledger.cli project" in out


def test_readme_argv_smoke(env, capsys):
    db_path, config_dir, ledger_dir, projection_dir = env
    assert main([
        "--db", str(db_path), "--config-dir", str(config_dir),
        "project", "--ledger-dir", str(ledger_dir),
        "--projection-dir", str(projection_dir),
        "--confirm", "authorize project",
    ]) == 0
    assert main(["--ledger-dir", str(ledger_dir), "search", "--projection-dir", str(projection_dir), "coffee"]) in {0, 1}
    # MATCH is case-insensitive under unicode61; either 0 with hits or 0 with empty is fine if query token matches payee
    rc_search = main(["--ledger-dir", str(ledger_dir), "search", "--projection-dir", str(projection_dir), "Coffee"])
    assert rc_search == 0
    rc_bal = main(["--ledger-dir", str(ledger_dir), "balances", "--projection-dir", str(projection_dir)])
    assert rc_bal == 0


def test_readme_golden_path_text():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "python -m ironledger.cli project --db ironledger.db --ledger-dir ledger" in text
    assert "python -m ironledger.cli search --ledger-dir ledger coffee" in text
    assert "python -m ironledger.cli balances --ledger-dir ledger" in text
    assert "authorize project" in text
    assert "safe-mode.json" in text


def test_phase_banner_is_current():
    import tomllib
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert data["tool"]["ironledger"]["phase"] >= 4
    from ironledger import __doc__ as pkg_doc
    assert "Phase 1 scope only" not in (pkg_doc or "")
