"""Tests for the IronLedger append-only Meta-Ledger (`mutation_events`)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.beancheck import BeanCheckResult
from ironledger.compile.writer import compile_approved
from ironledger.ingest.pipeline import run_import
from ironledger.review import state
from ironledger.mutation import (
    GENESIS_MUTATION_PREV_HASH,
    MutationEvent,
    MutationVerificationError,
    append_mutation_event,
    load_mutation_events,
    verify_mutation_chain,
)
from ironledger.web.app import create_app

FIXTURES = Path(__file__).parent / "fixtures"
OFX_IMPORTING_ACCOUNT = "Assets:Bank:Checking:SampleOfx"


def test_mutation_event_hash_chaining(tmp_path: Path) -> None:
    db_file = tmp_path / "test_mutations.db"
    conn = connect(str(db_file))
    migrations.migrate(conn)

    sha_before = "a" * 64
    sha_after_1 = "b" * 64
    sha_after_2 = "c" * 64

    # Event 1 (Genesis)
    ev1 = append_mutation_event(
        conn,
        operator_session="sess_1",
        action="compile",
        staged_count=10,
        rules_applied=8,
        rules_created=2,
        sha256_before=sha_before,
        sha256_after=sha_after_1,
        ts_utc="2026-09-09T10:00:00Z",
    )
    assert ev1.seq == 1
    assert ev1.prev_mutation_hash == GENESIS_MUTATION_PREV_HASH
    assert len(ev1.mutation_hash) == 64

    # Event 2
    ev2 = append_mutation_event(
        conn,
        operator_session="sess_2",
        action="compile",
        staged_count=5,
        rules_applied=5,
        rules_created=0,
        sha256_before=sha_after_1,
        sha256_after=sha_after_2,
        ts_utc="2026-09-09T11:00:00Z",
    )
    assert ev2.seq == 2
    assert ev2.prev_mutation_hash == ev1.mutation_hash
    assert len(ev2.mutation_hash) == 64

    # Verify chain
    result = verify_mutation_chain(conn)
    assert result.is_valid is True
    assert result.mutation_count == 2
    assert result.head_hash == ev2.mutation_hash

    conn.close()


def test_mutation_event_tamper_detection(tmp_path: Path) -> None:
    db_file = tmp_path / "test_tamper.db"
    conn = connect(str(db_file))
    migrations.migrate(conn)

    append_mutation_event(
        conn,
        operator_session="sess_1",
        action="compile",
        staged_count=3,
        rules_applied=3,
        rules_created=0,
        sha256_before="1" * 64,
        sha256_after="2" * 64,
        ts_utc="2026-09-09T10:00:00Z",
    )
    append_mutation_event(
        conn,
        operator_session="sess_2",
        action="compile",
        staged_count=4,
        rules_applied=4,
        rules_created=0,
        sha256_before="2" * 64,
        sha256_after="3" * 64,
        ts_utc="2026-09-09T11:00:00Z",
    )

    events = load_mutation_events(conn)
    assert len(events) == 2

    # Tamper payload of event 1
    tampered_event = MutationEvent(
        seq=events[0].seq,
        mutation_id=events[0].mutation_id,
        ts_utc=events[0].ts_utc,
        operator_session=events[0].operator_session,
        action="compile",
        staged_count=999,  # tampered!
        rules_applied=events[0].rules_applied,
        rules_created=events[0].rules_created,
        sha256_before=events[0].sha256_before,
        sha256_after=events[0].sha256_after,
        prev_mutation_hash=events[0].prev_mutation_hash,
        mutation_hash=events[0].mutation_hash,
    )

    tampered_list = [tampered_event, events[1]]
    with pytest.raises(MutationVerificationError, match="hash mismatch"):
        verify_mutation_chain(tampered_list)

    conn.close()


def test_mutation_events_append_only_triggers(tmp_path: Path) -> None:
    db_file = tmp_path / "test_triggers.db"
    conn = connect(str(db_file))
    migrations.migrate(conn)

    ev = append_mutation_event(
        conn,
        operator_session="sess_1",
        action="compile",
        staged_count=1,
        rules_applied=1,
        rules_created=0,
        sha256_before="0" * 64,
        sha256_after="1" * 64,
        ts_utc="2026-09-09T10:00:00Z",
    )

    # UPDATE forbidden
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="mutation_events is append-only: UPDATE is forbidden"):
        conn.execute("UPDATE mutation_events SET staged_count = 100 WHERE seq = ?", (ev.seq,))

    # DELETE forbidden
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="mutation_events is append-only: DELETE is forbidden"):
        conn.execute("DELETE FROM mutation_events WHERE seq = ?", (ev.seq,))

    conn.close()


def test_compile_records_mutation_event(tmp_path: Path) -> None:
    db_file = tmp_path / "test_compile_mut.db"
    ledger_dir = tmp_path / "ledger"
    config_dir = tmp_path / "config"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)

    conn = connect(str(db_file))
    migrations.migrate(conn)

    paths = {
        "config_dir": config_dir,
        "evidence_dir": tmp_path / "evidence",
        "records_dir": tmp_path / "evidence" / "source_records",
    }
    run_import(
        conn,
        FIXTURES / "sample_v1.ofx",
        csv_profile=None,
        importing_account=OFX_IMPORTING_ACCOUNT,
        now_utc="2026-09-03T10:00:00Z",
        **paths,
    )

    # Categorize and approve
    stx_id = conn.execute("SELECT staged_transaction_id FROM staged_transactions LIMIT 1").fetchone()[0]
    state.categorize(conn, stx_id, "Expenses:Groceries", now_utc="2026-09-03T11:00:00Z")
    state.approve(conn, stx_id, now_utc="2026-09-03T12:00:00Z")
    conn.commit()

    with patch(
        "ironledger.compile.writer.run_bean_check",
        return_value=BeanCheckResult(
            ok=True,
            exit_code=0,
            stdout="",
            stderr="",
            beancount_version="3.0.0",
            compiler_version="0.1.0",
        ),
    ):
        summary = compile_approved(conn, ledger_dir)
        conn.commit()

    mutations = load_mutation_events(conn)
    assert len(mutations) >= 1
    last_mut = mutations[-1]
    assert last_mut.action == "compile"
    assert last_mut.staged_count == 1
    assert last_mut.sha256_after == summary.output_hash

    # Verify chain
    assert verify_mutation_chain(conn).is_valid is True
    conn.close()


def test_system_mutations_endpoint(tmp_path: Path) -> None:
    db_file = tmp_path / "test_api_mut.db"
    conn = connect(str(db_file))
    migrations.migrate(conn)

    append_mutation_event(
        conn,
        operator_session="test_sess",
        action="compile",
        staged_count=2,
        rules_applied=1,
        rules_created=1,
        sha256_before="0" * 64,
        sha256_after="f" * 64,
        ts_utc="2026-09-09T12:00:00Z",
    )
    conn.commit()
    conn.close()

    app = create_app(db_path=db_file)
    client = TestClient(app)

    resp = client.get("/api/system/mutations")
    assert resp.status_code == 200
    data = resp.json()
    assert "mutations" in data
    assert len(data["mutations"]) == 1
    assert data["mutations"][0]["action"] == "compile"
    assert data["mutations"][0]["staged_count"] == 2
