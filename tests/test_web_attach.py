"""Phase 15 T07: attach proposal HTTP surface."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.pipeline import run_import
from ironledger.web.app import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def test_list_and_confirm_attach_proposal(tmp_path: Path):
    db_path = tmp_path / "ironledger.db"
    conn = connect(str(db_path))
    migrations.migrate(conn)
    config_dir = tmp_path / "config"
    (config_dir / "csv-profiles").mkdir(parents=True)
    (config_dir / "csv-profiles" / "example-bank.json").write_text(
        Path("config/csv-profiles/example-bank.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    paths = {
        "config_dir": config_dir,
        "evidence_dir": tmp_path / "evidence",
        "records_dir": tmp_path / "evidence" / "source_records",
    }
    run_import(
        conn, FIXTURES / "sample_bank.csv", csv_profile="example-bank",
        now_utc="2026-09-02T10:00:00Z", **paths,
    )
    alt = tmp_path / "alt.csv"
    alt.write_text(
        "Date,Description,Notes,Amount\n"
        "2026-08-15,OTHER CAFE,card 1234,-12.99\n"
        "2026-08-16,OTHER PAYROLL,,2000.00\n"
        "2026-08-17,OTHER PARENS,,(45.00)\n",
        encoding="utf-8",
    )
    run_import(conn, alt, csv_profile="example-bank", now_utc="2026-09-02T10:10:00Z", **paths)
    conn.commit()
    conn.close()

    app = create_app(db_path=db_path)
    app.state.op_token = "secret-token"
    client = TestClient(app)

    denied = client.post(
        "/api/staging/proposals/nope/confirm",
        json={"chosen_staged_id": "stx:x"},
    )
    assert denied.status_code == 401

    listed = client.get("/api/staging/proposals")
    assert listed.status_code == 200
    props = listed.json()
    assert len(props) == 3
    assert props[0]["item_type"] == "attach"
    assert props[0]["kind"] == "unique"
    assert props[0]["candidates"]
    chosen = props[0]["candidates"][0]["staged_id"]
    ok = client.post(
        f"/api/staging/proposals/{props[0]['proposal_id']}/confirm",
        json={"chosen_staged_id": chosen},
        headers={"X-IronLedger-Op-Token": "secret-token"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "confirmed"
    remaining = client.get("/api/staging/proposals").json()
    assert len(remaining) == 2
