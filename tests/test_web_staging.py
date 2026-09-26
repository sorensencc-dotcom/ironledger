import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.pipeline import run_import
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
    # Import sample OFX so we have pending staged transactions
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

    app = create_app(db_path=db_path)
    app.state.op_token = "test-token"
    client = TestClient(app)
    client.headers.update({"X-IronLedger-Op-Token": "test-token"})
    return client, db_path


def test_get_staging_list(app_client):
    client, _ = app_client
    response = client.get("/api/staging")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    item = data[0]
    assert "staged_id" in item
    assert "payee" in item
    assert "minor_units" in item
    assert "postings" in item
    assert item["status"] == "pending"


def test_auto_match_endpoint_retargets_unassigned(app_client):
    from ironledger.review.rules import add_rule

    client, db_path = app_client
    conn = connect(str(db_path))
    add_rule(
        conn,
        match_type="exact",
        pattern="coffee bar",
        target_account="Expenses:Coffee",
        now_utc="2026-09-03T10:30:00Z",
    )
    conn.execute(
        "UPDATE staged_postings SET account = 'Expenses:Unassigned' WHERE role = 'contra'"
    )
    conn.commit()
    conn.close()

    res = client.post("/api/staging/auto-match")
    assert res.status_code == 200
    body = res.json()
    assert body["matched"] >= 1
    assert body["candidates"] >= body["matched"]

    items = client.get("/api/staging").json()
    coffee = next(tx for tx in items if (tx.get("payee") or "").lower() == "coffee bar")
    contra = next(p["account"] for p in coffee["postings"] if p["account"] != OFX_IMPORTING_ACCOUNT)
    assert contra == "Expenses:Coffee"
    assert coffee["status"] == "categorized"


def test_categorize_staged_transaction(app_client):
    client, _ = app_client
    # Get the pending list
    res = client.get("/api/staging")
    items = res.json()
    stx_id = items[0]["staged_id"]

    # Categorize
    cat_res = client.post(
        f"/api/staging/{stx_id}/categorize",
        json={"target_account": "Expenses:Groceries", "notes": "Weekly market"},
    )
    assert cat_res.status_code == 200
    cat_data = cat_res.json()
    assert cat_data["success"] is True
    assert cat_data["status"] == "categorized"


def test_approve_staged_transaction(app_client):
    client, _ = app_client
    res = client.get("/api/staging")
    items = res.json()
    stx_id = items[0]["staged_id"]

    # First categorize
    client.post(
        f"/api/staging/{stx_id}/categorize",
        json={"target_account": "Expenses:Dining"},
    )

    # Approve
    appr_res = client.post(f"/api/staging/{stx_id}/approve", json={})
    assert appr_res.status_code == 200
    appr_data = appr_res.json()
    assert appr_data["success"] is True
    assert appr_data["status"] == "approved"


def test_reject_staged_transaction(app_client):
    client, _ = app_client
    res = client.get("/api/staging")
    items = res.json()
    stx_id = items[0]["staged_id"]

    rej_res = client.post(
        f"/api/staging/{stx_id}/reject",
        json={"reason": "Duplicate entry"},
    )
    assert rej_res.status_code == 200
    rej_data = rej_res.json()
    assert rej_data["success"] is True
    assert rej_data["status"] == "rejected"


def test_reopen_rejected_transaction_then_categorize(app_client):
    client, _ = app_client
    stx_id = client.get("/api/staging").json()[0]["staged_id"]
    assert client.post(f"/api/staging/{stx_id}/reject", json={}).status_code == 200

    reopen_res = client.post(f"/api/staging/{stx_id}/reopen")
    assert reopen_res.status_code == 200
    assert reopen_res.json()["status"] == "pending"

    categorize_res = client.post(
        f"/api/staging/{stx_id}/categorize",
        json={"target_account": "Expenses:CreditCardPayment"},
    )
    assert categorize_res.status_code == 200
    assert categorize_res.json()["status"] == "categorized"


def test_split_staged_transaction(app_client):
    client, _ = app_client
    res = client.get("/api/staging")
    items = res.json()
    # Find item
    stx = items[0]
    stx_id = stx["staged_id"]
    total_minor = stx["minor_units"]
    currency = stx["currency"]
    scale = stx["scale"]

    # Contra sum must be -total_minor
    contra_total = -total_minor
    half1 = contra_total // 2
    half2 = contra_total - half1

    split_payload = {
        "postings": [
            {
                "account": "Expenses:General:PartA",
                "currency": currency,
                "minor_units": half1,
                "scale": scale,
            },
            {
                "account": "Expenses:General:PartB",
                "currency": currency,
                "minor_units": half2,
                "scale": scale,
            },
        ]
    }
    split_res = client.post(f"/api/staging/{stx_id}/split", json=split_payload)
    assert split_res.status_code == 200
    split_data = split_res.json()
    assert split_data["success"] is True
    assert len(split_data["postings"]) == 3  # 1 imported + 2 split contras

