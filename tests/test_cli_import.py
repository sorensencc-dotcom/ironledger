"""Phase 2a: the `ironledger import` command end to end."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ironledger.cli.__main__ import main
from ironledger.db import migrations
from ironledger.db.connection import connect


@pytest.fixture
def workspace(tmp_path: Path) -> dict:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    config_dir = tmp_path / "config"
    (config_dir / "csv-profiles").mkdir(parents=True)
    (config_dir / "filesystem-roots.json").write_text(
        json.dumps({"ingest_inbox": str(inbox)}), encoding="utf-8"
    )
    (config_dir / "safe-mode.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
    (config_dir / "csv-profiles" / "example-bank.json").write_text(
        Path("config/csv-profiles/example-bank.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    fixture = Path("tests/fixtures/sample_v1.ofx").read_bytes()
    (inbox / "sample_v1.ofx").write_bytes(fixture)
    db_path = tmp_path / "ledger.db"
    conn = connect(str(db_path))
    migrations.migrate(conn)
    conn.close()
    return {
        "db": str(db_path), "config_dir": str(config_dir),
        "evidence_dir": str(tmp_path / "evidence"), "inbox": inbox,
    }


def test_import_without_confirm_exits_3(workspace: dict):
    code = main([
        "--db", workspace["db"], "--config-dir", workspace["config_dir"],
        "--evidence-dir", workspace["evidence_dir"],
        "import", str(workspace["inbox"] / "sample_v1.ofx"),
    ])
    assert code == 3


def test_import_with_matching_confirm_exits_0_and_stages(workspace: dict):
    path = workspace["inbox"] / "sample_v1.ofx"
    code = main([
        "--db", workspace["db"], "--config-dir", workspace["config_dir"],
        "--evidence-dir", workspace["evidence_dir"],
        "import", str(path), "--importing-account", "Assets:Bank:Checking:SampleOfx",
        "--confirm", f"import {path.resolve()}",
    ])
    assert code == 0
    conn = connect(workspace["db"])
    assert conn.execute("SELECT count(*) FROM staged_transactions").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 1


def test_pdf_import_uses_profile_account_and_rejects_importing_account(workspace: dict):
    from tests.test_ingest_pdf import _minimal_pdf

    config = Path(workspace["config_dir"])
    (config / "pdf-profiles").mkdir(parents=True)
    (config / "pdf-profiles" / "example-card.json").write_text(
        Path("config/pdf-profiles/example-card.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    path = workspace["inbox"] / "stmt.pdf"
    path.write_bytes(_minimal_pdf("2026-09-01  CAFE  -12.99"))
    denied = main([
        "--db", workspace["db"], "--config-dir", workspace["config_dir"],
        "--evidence-dir", workspace["evidence_dir"],
        "import", str(path), "--pdf-profile", "example-card",
        "--importing-account", "Assets:Bank:Checking:ExampleBank",
        "--confirm", f"import {path.resolve()}",
    ])
    assert denied == 4
    code = main([
        "--db", workspace["db"], "--config-dir", workspace["config_dir"],
        "--evidence-dir", workspace["evidence_dir"],
        "import", str(path), "--pdf-profile", "example-card",
        "--confirm", f"import {path.resolve()}",
    ])
    assert code == 0
    conn = connect(workspace["db"])
    account = conn.execute(
        "SELECT account FROM staged_postings WHERE role='imported'"
    ).fetchone()[0]
    assert account == "Liabilities:CreditCard:ExampleCard"


def test_import_outside_inbox_exits_4(workspace: dict, tmp_path: Path):
    stray = tmp_path / "stray.ofx"
    stray.write_bytes(Path("tests/fixtures/sample_v1.ofx").read_bytes())
    code = main([
        "--db", workspace["db"], "--config-dir", workspace["config_dir"],
        "--evidence-dir", workspace["evidence_dir"],
        "import", str(stray), "--confirm", f"import {stray.resolve()}",
    ])
    assert code == 4
