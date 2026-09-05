"""Phase 2b: end-to-end coverage for import -> auto-match -> approve.

No prior test spans the full chain: a real OFX import creates a staged row,
a pre-registered categorization rule fills its contra account via auto_match,
and the row is then approved. This is the shape an operator actually drives
through the CLI (`review loop`, or `auto-match` + `approve`), so it is worth
proving end to end rather than only at each stage in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.pipeline import run_import
from ironledger.review import state
from ironledger.review.rules import add_rule

FIXTURES = Path(__file__).parent / "fixtures"
OFX_IMPORTING_ACCOUNT = "Assets:Bank:Checking:SampleOfx"


@pytest.fixture
def env(tmp_path: Path):
    conn = connect(str(tmp_path / "ledger.db"))
    migrations.migrate(conn)
    config_dir = tmp_path / "config"
    (config_dir / "csv-profiles").mkdir(parents=True)
    paths = {
        "config_dir": config_dir,
        "evidence_dir": tmp_path / "evidence",
        "records_dir": tmp_path / "evidence" / "source_records",
    }
    return conn, paths


def test_import_then_auto_match_then_approve(env):
    from ironledger.ingest.pipeline import run_import

    conn, paths = env
    # Import first, with no rule registered yet, so the row lands pending with a
    # NULL contra -- exactly what auto_match is for.
    run_import(conn, FIXTURES / "sample_v1.ofx", csv_profile=None,
               importing_account=OFX_IMPORTING_ACCOUNT, now_utc="2026-09-03T10:00:00Z", **paths)
    conn.commit()

    add_rule(conn, match_type="exact", pattern="coffee bar", target_account="Expenses:Coffee",
             importing_account=OFX_IMPORTING_ACCOUNT, now_utc="2026-09-03T10:30:00Z")
    conn.commit()

    stx_id, status_before, contra_before = conn.execute(
        "SELECT t.staged_transaction_id, t.status, p.account "
        "FROM staged_transactions t "
        "JOIN staged_postings p ON p.staged_transaction_id = t.staged_transaction_id "
        "  AND p.role = 'contra' "
        "WHERE t.payee = 'COFFEE BAR'"
    ).fetchone()
    assert status_before == "pending"
    assert contra_before is None  # not filled until auto_match runs

    matched, candidates = state.auto_match(
        conn, importing_account=OFX_IMPORTING_ACCOUNT, now_utc="2026-09-03T11:00:00Z",
    )
    conn.commit()
    assert matched == 1
    assert candidates >= 1

    status_after_match, contra_after_match = conn.execute(
        "SELECT t.status, p.account FROM staged_transactions t "
        "JOIN staged_postings p ON p.staged_transaction_id = t.staged_transaction_id "
        "  AND p.role = 'contra' "
        "WHERE t.staged_transaction_id = ?", (stx_id,),
    ).fetchone()
    assert status_after_match == "categorized"
    assert contra_after_match == "Expenses:Coffee"

    state.approve(conn, stx_id, now_utc="2026-09-03T12:00:00Z")
    conn.commit()

    final_status = conn.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = ?", (stx_id,)
    ).fetchone()[0]
    assert final_status == "approved"
