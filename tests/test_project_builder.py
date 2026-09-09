# tests/test_project_builder.py
from __future__ import annotations

from pathlib import Path

import pytest

from ironledger.db.connection import connect
from ironledger.project.builder import write_staging_projection
from ironledger.project.parse import parse_ledger
from tests.project_fixtures import make_sample_set, write_rendered_ledger


def test_builder_balances_equal_sum_of_postings(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    parsed = parse_ledger(ledger_dir)
    staging = tmp_path / "projection" / ".staging" / "build-1"
    sqlite_path = write_staging_projection(
        parsed,
        staging,
        compile_run_id="run-1",
        ledger_input_hash="a" * 64,
        ledger_output_hash="b" * 64,
        beancount_version="3.2.3",
        compiler_version="0.1.0",
        built_at_utc="2026-09-08T12:00:00Z",
    )
    assert sqlite_path.name == "projection.sqlite"
    assert not (staging / "projection.sqlite-wal").exists()
    assert (staging / "projection.manifest.json").is_file()

    conn = connect(sqlite_path)
    meta = conn.execute(
        "SELECT compile_run_id, schema_version FROM projection_meta WHERE singleton = 1"
    ).fetchone()
    assert meta == ("run-1", 1)
    rows = conn.execute(
        "SELECT b.account, b.currency, b.minor_units, "
        " (SELECT SUM(p.minor_units) FROM proj_postings p "
        "  WHERE p.account = b.account AND p.currency = b.currency) "
        "FROM proj_balances b"
    ).fetchall()
    assert rows
    for account, currency, bal, summed in rows:
        assert bal == summed, (account, currency, bal, summed)
    hits = conn.execute(
        "SELECT posting_id FROM proj_fts WHERE proj_fts MATCH 'Coffee' ORDER BY posting_id"
    ).fetchall()
    assert hits  # payee is indexed
    conn.close()


def test_second_currency_on_one_account_refuses(tmp_path: Path):
    from ironledger.project.errors import ProjectInputError, ProjectParseError
    from ironledger.project.parse import parse_ledger
    from tests.project_fixtures import make_sample_set, write_rendered_ledger

    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    accounts = ledger_dir / "accounts.beancount"
    accounts.write_text(
        accounts.read_text(encoding="utf-8") + "2026-09-01 open Assets:Checking EUR\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises((ProjectInputError, ProjectParseError)):
        parsed = parse_ledger(ledger_dir)
        write_staging_projection(
            parsed,
            tmp_path / "staging",
            compile_run_id="run-1",
            ledger_input_hash="a" * 64,
            ledger_output_hash="b" * 64,
            beancount_version="3.2.3",
            compiler_version="0.1.0",
            built_at_utc="2026-09-08T12:00:00Z",
        )
