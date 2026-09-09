import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.pipeline import run_import
from ironledger.review.rules import add_rule
from ironledger.web.app import create_app

FIXTURES = Path(__file__).parent / "fixtures"
OFX_IMPORTING_ACCOUNT = "Assets:Bank:Checking:SampleOfx"


@pytest.fixture
def app_client(tmp_path: Path):
    db_path = tmp_path / "ironledger.db"
    conn = connect(str(db_path))
    migrations.migrate(conn)
    config_dir = tmp_path / "config"
    (config_dir / "csv-profiles").mkdir(parents=True)
    paths = {
        "config_dir": config_dir,
        "evidence_dir": tmp_path / "evidence",
        "records_dir": tmp_path / "evidence" / "source_records",
    }
    # Import sample OFX
    run_import(
        conn,
        FIXTURES / "sample_v1.ofx",
        csv_profile=None,
        importing_account=OFX_IMPORTING_ACCOUNT,
        now_utc="2026-09-03T10:00:00Z",
        **paths,
    )
    conn.commit()

    # Add a sample rule
    rule_id = add_rule(
        conn,
        match_type="exact",
        pattern="coffee bar",
        target_account="Expenses:Coffee",
        importing_account=OFX_IMPORTING_ACCOUNT,
        now_utc="2026-09-03T10:30:00Z",
    )
    conn.commit()
    conn.close()

    app = create_app(db_path=db_path)
    client = TestClient(app)
    return client, db_path, rule_id


def test_list_rules(app_client):
    client, _, rule_id = app_client
    res = client.get("/api/rules")
    assert res.status_code == 200
    rules = res.json()
    assert isinstance(rules, list)
    assert len(rules) >= 1
    assert any(r["rule_id"] == rule_id for r in rules)


def test_create_and_disable_rule(app_client):
    client, _, _ = app_client
    create_payload = {
        "match_type": "prefix",
        "pattern": "WHOLE FOODS",
        "target_account": "Expenses:Groceries",
        "priority": 100,
        "active": True,
    }
    res = client.post("/api/rules", json=create_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    created_id = data["rule_id"]

    # Disable rule
    dis_res = client.post(f"/api/rules/{created_id}/disable")
    assert dis_res.status_code == 200
    dis_data = dis_res.json()
    assert dis_data["success"] is True


def test_generate_rule_candidate(app_client):
    client, _, _ = app_client
    # Get staged transactions
    stg_res = client.get("/api/staging")
    items = stg_res.json()
    stx_id = items[0]["staged_id"]

    cand_res = client.post("/api/rules/candidate", json={"staged_id": stx_id, "pattern_type": "exact"})
    assert cand_res.status_code == 200
    cand_data = cand_res.json()
    assert "suggested_pattern" in cand_data
    assert "target_account" in cand_data
    assert "retroactive_matches" in cand_data
    assert cand_data["retroactive_matches"] >= 1


def test_rule_drift_endpoint(app_client):
    client, _, rule_id = app_client
    drift_res = client.get(f"/api/rules/{rule_id}/drift")
    assert drift_res.status_code == 200
    drift_data = drift_res.json()
    assert drift_data["rule_id"] == rule_id
    assert "total_hits" in drift_data
    assert "override_count" in drift_data
    assert "override_rate" in drift_data
    assert "drift_status" in drift_data
    assert drift_data["drift_status"] in ("healthy", "warning", "stale")

