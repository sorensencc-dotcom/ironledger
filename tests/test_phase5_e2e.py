"""Phase 5 End-to-End Acceptance Tests for IronLedger Operator Workbench."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.pipeline import run_import
from ironledger.compile.beancheck import BeanCheckResult
from ironledger.web.app import create_app


FIXTURES = Path(__file__).parent / "fixtures"
OFX_IMPORTING_ACCOUNT = "Assets:Bank:Checking:SampleOfx"


@pytest.fixture
def e2e_env(tmp_path: Path):
    db_path = tmp_path / "ironledger.db"
    proj_dir = tmp_path / "projection"
    proj_db_path = proj_dir / "projection.sqlite"
    config_dir = tmp_path / "config"
    ledger_dir = tmp_path / "ledger"
    config_dir.mkdir(parents=True, exist_ok=True)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    proj_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "csv-profiles").mkdir(parents=True, exist_ok=True)

    # Initialize DB schema
    conn = connect(str(db_path))
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
    conn.commit()
    conn.close()

    # Configure safe mode config allowing operations
    safe_mode_config = {
        "enabled": False,
        "operator_token": "valid-operator-token",
        "bypass_active": True,
    }
    (config_dir / "safe-mode.json").write_text(json.dumps(safe_mode_config), encoding="utf-8")

    app = create_app(
        db_path=db_path,
        projection_db_path=proj_db_path,
        config_dir=config_dir,
    )
    app.state.ledger_dir = ledger_dir
    app.state.projection_dir = proj_dir
    client = TestClient(app)

    return {
        "client": client,
        "db_path": db_path,
        "proj_db_path": proj_db_path,
        "config_dir": config_dir,
        "ledger_dir": ledger_dir,
        "proj_dir": proj_dir,
    }


def test_full_phase5_operator_workflow(e2e_env) -> None:
    client: TestClient = e2e_env["client"]
    ledger_dir: Path = e2e_env["ledger_dir"]

    # 1. Query Staging Queue
    resp = client.get("/api/staging")
    assert resp.status_code == 200
    staged = resp.json()
    assert len(staged) >= 2
    stx_1 = staged[0]
    stx_2 = staged[1]

    # 2. Rule Candidate Extraction
    cand_resp = client.post(
        "/api/rules/candidate",
        json={"staged_id": stx_1["staged_id"], "pattern_type": "exact"},
    )
    assert cand_resp.status_code == 200
    cand_data = cand_resp.json()
    assert "suggested_pattern" in cand_data

    # 3. Create Rule & Verify Drift
    rule_resp = client.post(
        "/api/rules",
        json={
            "match_type": "exact",
            "pattern": cand_data["suggested_pattern"],
            "account": "Expenses:Groceries",
            "priority": 100,
        },
    )
    assert rule_resp.status_code == 200
    rule_id = rule_resp.json()["rule_id"]

    drift_resp = client.get(f"/api/rules/{rule_id}/drift")
    assert drift_resp.status_code == 200
    assert drift_resp.json()["drift_status"] == "healthy"

    # 4. Split Transaction stx_2
    imported_amt = stx_2["postings"][0]["minor_units"]
    contra_amt_1 = -imported_amt // 2
    contra_amt_2 = -imported_amt - contra_amt_1
    split_resp = client.post(
        f"/api/staging/{stx_2['staged_id']}/split",
        json={
            "postings": [
                {"account": "Expenses:Food", "minor_units": contra_amt_1, "currency": "USD", "scale": 2},
                {"account": "Expenses:General", "minor_units": contra_amt_2, "currency": "USD", "scale": 2},
            ]
        },
    )
    assert split_resp.status_code == 200
    assert split_resp.json()["status"] == "categorized"
    assert len(split_resp.json()["postings"]) == 3

    # Categorize stx_1 if not categorized
    cat_resp = client.post(
        f"/api/staging/{stx_1['staged_id']}/categorize",
        json={"contra_account": "Expenses:Utilities"},
    )
    assert cat_resp.status_code == 200

    # 5. Approve stx_1
    app_1 = client.post(f"/api/staging/{stx_1['staged_id']}/approve")
    assert app_1.status_code == 200
    assert app_1.json()["status"] == "approved"

    # 6. Dry-Run Simulation
    sim_resp = client.post(
        "/api/compile/simulate",
        json={"ledger_dir": str(ledger_dir)},
    )
    assert sim_resp.status_code == 200
    sim_data = sim_resp.json()
    assert sim_data["success"] is True
    assert sim_data["entries_compiled"] >= 1
    assert "diff_preview" in sim_data

    # 7. Compile Approved Transactions to Ledger
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
        compile_resp = client.post(
            "/api/compile",
            json={"ledger_dir": str(ledger_dir)},
        )
        assert compile_resp.status_code == 200
        comp_data = compile_resp.json()
        assert comp_data["success"] is True
        assert comp_data["entries_compiled"] >= 1

    # 8. Rebuild Analytics Projection
    proj_resp = client.post(
        "/api/project/rebuild",
        json={"ledger_dir": str(ledger_dir)},
    )
    assert proj_resp.status_code == 200
    assert proj_resp.json()["success"] is True

    # 9. Query Balances
    bal_resp = client.get("/api/balances")
    assert bal_resp.status_code == 200
    balances = bal_resp.json()
    assert isinstance(balances, list)
    assert len(balances) > 0

    # 10. FTS Search
    query_word = stx_1["payee"].split()[0] if stx_1["payee"] else "Groceries"
    search_resp = client.get(f"/api/search?q={query_word}")
    assert search_resp.status_code == 200
    hits = search_resp.json()
    assert isinstance(hits, list)

    # 11. Freshness Latency Check
    fresh_resp = client.get("/api/projection/freshness")
    assert fresh_resp.status_code == 200
    assert fresh_resp.json()["is_fresh"] is True

    # 12. Safe Mode and Audit History Verification
    sys_resp = client.get("/api/system/safe-mode")
    assert sys_resp.status_code == 200

    audit_resp = client.get("/api/system/audit")
    assert audit_resp.status_code == 200
    assert len(audit_resp.json()["events"]) > 0

