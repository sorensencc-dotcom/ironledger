import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.pipeline import run_import
from ironledger.review import state
from ironledger.web.app import create_app

FIXTURES = Path(__file__).parent / "fixtures"
OFX_IMPORTING_ACCOUNT = "Assets:Bank:Checking:SampleOfx"


@pytest.fixture
def app_env(tmp_path: Path):
    db_path = tmp_path / "ironledger.db"
    conn = connect(str(db_path))
    migrations.migrate(conn)

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "csv-profiles").mkdir(parents=True)
    (config_dir / "safe-mode.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir(parents=True)
    proj_dir = tmp_path / "projection"
    proj_dir.mkdir(parents=True)

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
    conn.commit()

    # Categorize and approve one transaction
    stx_id = conn.execute("SELECT staged_transaction_id FROM staged_transactions LIMIT 1").fetchone()[0]
    state.categorize(conn, stx_id, "Expenses:Groceries", now_utc="2026-09-03T11:00:00Z")
    state.approve(conn, stx_id, now_utc="2026-09-03T12:00:00Z")
    conn.commit()
    conn.close()

    app = create_app(
        db_path=db_path,
        projection_db_path=proj_dir / "projection.sqlite",
        config_dir=config_dir,
    )
    app.state.ledger_dir = ledger_dir
    app.state.projection_dir = proj_dir

    client = TestClient(app)
    return client, db_path, config_dir, ledger_dir, proj_dir


def test_safe_mode_blocks_unauthorized_compile(app_env):
    client, db_path, config_dir, _, _ = app_env
    # Safe mode is ON by default in app_env
    res = client.post("/api/compile", json={"dry_run": False})
    assert res.status_code in (400, 403)
    data = res.json()
    assert "safe mode" in str(data).lower() or "not authorized" in str(data).lower()


def test_dry_run_simulation_succeeds_under_safe_mode_without_modifications(app_env):
    client, db_path, _, ledger_dir, _ = app_env
    # Count audit events before
    conn = connect(str(db_path))
    audit_count_before = conn.execute("SELECT count(*) FROM audit_events").fetchone()[0]
    conn.close()

    res = client.post("/api/compile/simulate", json={})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["dry_run"] is True
    assert data["entries_compiled"] >= 1
    assert data["diff_preview"] is not None

    # Verify zero disk writes to ledger_dir
    assert len(list(ledger_dir.glob("*.beancount"))) == 0

    # Verify zero new audit events
    conn = connect(str(db_path))
    audit_count_after = conn.execute("SELECT count(*) FROM audit_events").fetchone()[0]
    conn.close()
    assert audit_count_after == audit_count_before


from unittest.mock import patch
from ironledger.compile.beancheck import BeanCheckResult


def test_compile_succeeds_when_safe_mode_disabled(app_env):
    client, db_path, config_dir, ledger_dir, proj_dir = app_env
    # Disable safe mode in config
    (config_dir / "safe-mode.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")

    success_res = BeanCheckResult(
        ok=True,
        exit_code=0,
        stdout="",
        stderr="",
        beancount_version="3.2.3",
        compiler_version="0.1.0",
    )

    with patch("ironledger.compile.writer.run_bean_check", return_value=success_res):
        res = client.post("/api/compile", json={"dry_run": False, "rebuild_projection": True})

    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["dry_run"] is False
    assert data["run_id"] is not None
    assert (ledger_dir / "main.beancount").exists()
    assert (proj_dir / "projection.sqlite").exists()


def test_system_safe_mode_status(app_env):
    client, _, _, _, _ = app_env
    res = client.get("/api/system/safe-mode")
    assert res.status_code == 200
    data = res.json()
    assert "enabled" in data
    assert data["enabled"] is True

