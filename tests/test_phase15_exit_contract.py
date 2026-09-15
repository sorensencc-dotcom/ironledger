"""Phase 15 exit contract: attach-not-duplicate, integer money path, no beancount import."""

from __future__ import annotations

import ast
from pathlib import Path

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.pipeline import run_import

FIXTURES = Path(__file__).parent / "fixtures"
NEW_MODULES = [
    Path("src/ironledger/ingest/attach.py"),
    Path("src/ironledger/ingest/formats/pdf_engine.py"),
]


def _visitor_flags(path: Path) -> tuple[bool, bool]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    has_div = any(isinstance(node, ast.Div) for node in ast.walk(tree))
    has_beancount = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            has_beancount = has_beancount or any(a.name.split(".")[0] == "beancount" for a in node.names)
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "beancount":
            has_beancount = True
    return has_div, has_beancount


def test_new_modules_forbid_float_div_and_beancount_import():
    for path in NEW_MODULES:
        has_div, has_beancount = _visitor_flags(path)
        assert has_div is False, f"{path} contains ast.Div"
        assert has_beancount is False, f"{path} imports beancount"


def test_confirm_attach_does_not_increase_posting_count(tmp_path: Path):
    conn = connect(str(tmp_path / "ledger.db"))
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
    before_stx = conn.execute("SELECT count(*) FROM staged_transactions").fetchone()[0]
    before_post = conn.execute("SELECT count(*) FROM staged_postings").fetchone()[0]
    from ironledger.review.state import confirm_attach

    prop, cands = conn.execute(
        "SELECT proposal_id, candidate_staged_ids FROM attach_proposals LIMIT 1"
    ).fetchone()
    import json
    confirm_attach(conn, prop, json.loads(cands)[0], now_utc="2026-09-02T10:20:00Z")
    after_stx = conn.execute("SELECT count(*) FROM staged_transactions").fetchone()[0]
    after_post = conn.execute("SELECT count(*) FROM staged_postings").fetchone()[0]
    assert after_stx == before_stx
    assert after_post == before_post
    evidence = conn.execute("SELECT count(*) FROM event_evidence").fetchone()[0]
    assert evidence == 1
