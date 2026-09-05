"""Phase 2b: the review and rule CLI command trees end to end via main(argv)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ironledger.cli.__main__ import main
from ironledger.db import migrations
from ironledger.db.connection import connect


@pytest.fixture
def env(tmp_path: Path):
    db = tmp_path / "ledger.db"
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "safe-mode.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
    conn = connect(str(db))
    migrations.migrate(conn)
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, "
        " acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        f"VALUES ('doc-1','text/csv','utf-8','p','2026-09-02T10:00:00Z','{'a'*64}',"
        " 'evidence/source_documents/doc-1','2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, "
        f" canonical_payload, content_sha256, created_at_utc) VALUES ('doc-1:0','doc-1',0,'{{}}',"
        f" '{'b'*64}','2026-09-02T10:00:00Z')"
    )
    from ironledger.ingest.stage import StagedInput, upsert_staged
    stx_id, _ = upsert_staged(
        conn,
        StagedInput(
            source_record_id="doc-1:0", account="Assets:Bank:Checking", iso_date="2026-08-15",
            minor_units=-1299, currency="USD", scale=2, payee="COFFEE BAR", fitid="",
            identity_method="sha256_fallback", identity_fingerprint="d" * 64,
            institution_account_key="b/c1",
        ),
        now_utc="2026-09-02T10:00:00Z",
    )
    conn.commit()
    conn.close()
    return db, cfg, stx_id


def _argv(db, cfg, *rest):
    return ["--db", str(db), "--config-dir", str(cfg), *rest]


def test_rule_add_then_list(env, capsys):
    db, cfg, _ = env
    rc = main(_argv(db, cfg, "rule", "add", "--match-type", "exact", "--pattern", "coffee bar",
                    "--account", "Expenses:Coffee", "--confirm", "rule Expenses:Coffee"))
    assert rc == 0
    rc = main(_argv(db, cfg, "rule", "list"))
    assert rc == 0
    assert "Expenses:Coffee" in capsys.readouterr().out


def test_categorize_then_approve(env, capsys):
    db, cfg, stx = env
    rc = main(_argv(db, cfg, "review", "categorize", stx, "Expenses:Coffee"))
    assert rc == 0
    rc = main(_argv(db, cfg, "review", "approve", stx, "--confirm", f"approve {stx}"))
    assert rc == 0
    conn = connect(str(db))
    assert conn.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = ?", (stx,)
    ).fetchone()[0] == "approved"


def test_approve_without_categorize_is_denied(env):
    db, cfg, stx = env
    rc = main(_argv(db, cfg, "review", "approve", stx, "--confirm", f"approve {stx}"))
    assert rc == 3
    conn = connect(str(db))
    action, result = conn.execute(
        "SELECT action, result FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert result == "denied"
    assert action.startswith("review approve (denied:")


def test_approve_without_confirm_on_non_tty_is_denied(env):
    db, cfg, stx = env
    main(_argv(db, cfg, "review", "categorize", stx, "Expenses:Coffee"))
    rc = main(_argv(db, cfg, "review", "approve", stx))
    assert rc == 3


def test_reject_with_reason_and_reopen(env):
    db, cfg, stx = env
    assert main(_argv(db, cfg, "review", "reject", stx, "--reason", "dupe",
                      "--confirm", f"reject {stx}")) == 0
    assert main(_argv(db, cfg, "review", "reopen", stx, "--confirm", f"reopen {stx}")) == 0
    conn = connect(str(db))
    assert conn.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = ?", (stx,)
    ).fetchone()[0] == "pending"


def test_categorize_persist_rule_creates_rule(env):
    db, cfg, stx = env
    rc = main(_argv(db, cfg, "review", "categorize", stx, "Expenses:Coffee", "--persist-rule"))
    assert rc == 0
    conn = connect(str(db))
    assert conn.execute("SELECT count(*) FROM categorization_rules").fetchone()[0] == 1


def test_review_list_status_categorized(env, capsys):
    db, cfg, stx = env
    main(_argv(db, cfg, "review", "categorize", stx, "Expenses:Coffee"))
    rc = main(_argv(db, cfg, "review", "list", "--status", "categorized"))
    assert rc == 0
    assert stx[:16] in capsys.readouterr().out


def test_safe_mode_blocks_categorize(env):
    db, cfg, stx = env
    (cfg / "safe-mode.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    rc = main(_argv(db, cfg, "review", "categorize", stx, "Expenses:Coffee"))
    assert rc == 3


def _enable_safe_mode(cfg: Path) -> None:
    (cfg / "safe-mode.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")


def test_safe_mode_blocks_reject(env):
    db, cfg, stx = env
    _enable_safe_mode(cfg)
    rc = main(_argv(db, cfg, "review", "reject", stx, "--confirm", f"reject {stx}"))
    assert rc == 3
    conn = connect(str(db))
    action, result = conn.execute(
        "SELECT action, result FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert result == "denied"
    assert action == "review-reject (denied: safe mode is on)"


def test_safe_mode_blocks_reopen(env):
    db, cfg, stx = env
    _enable_safe_mode(cfg)
    rc = main(_argv(db, cfg, "review", "reopen", stx, "--confirm", f"reopen {stx}"))
    assert rc == 3
    conn = connect(str(db))
    assert conn.execute(
        "SELECT result FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()[0] == "denied"


def test_safe_mode_blocks_auto_match(env):
    db, cfg, stx = env
    _enable_safe_mode(cfg)
    rc = main(_argv(db, cfg, "review", "auto-match", "--confirm", "auto-match all"))
    assert rc == 3
    conn = connect(str(db))
    assert conn.execute(
        "SELECT result FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()[0] == "denied"


def test_safe_mode_blocks_rule_add(env):
    db, cfg, stx = env
    _enable_safe_mode(cfg)
    rc = main(_argv(db, cfg, "rule", "add", "--match-type", "exact", "--pattern", "coffee bar",
                    "--account", "Expenses:Coffee", "--confirm", "rule Expenses:Coffee"))
    assert rc == 3
    conn = connect(str(db))
    assert conn.execute("SELECT count(*) FROM categorization_rules").fetchone()[0] == 0
    assert conn.execute(
        "SELECT result FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()[0] == "denied"


def test_review_show_and_json_emit_no_audit_event(env, capsys):
    db, cfg, stx = env
    main(_argv(db, cfg, "review", "categorize", stx, "Expenses:Coffee"))
    conn = connect(str(db))
    before = conn.execute("SELECT count(*) FROM audit_events").fetchone()[0]
    conn.close()
    rc = main(_argv(db, cfg, "review", "show", stx))
    assert rc == 0
    out = capsys.readouterr().out
    assert stx in out and "Expenses:Coffee" in out
    rc = main(_argv(db, cfg, "review", "show", stx, "--json"))
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["staged_transaction_id"] == stx
    rc = main(_argv(db, cfg, "rule", "list"))
    assert rc == 0
    conn = connect(str(db))
    after = conn.execute("SELECT count(*) FROM audit_events").fetchone()[0]
    assert after == before


def test_review_show_uncompilable_regex_suggestion_writes_no_audit(env):
    db, cfg, stx = env
    conn = connect(str(db))
    conn.execute(
        "INSERT INTO categorization_rules (rule_id, match_type, pattern, importing_account, "
        " target_account, priority, active, created_at_utc) VALUES "
        "('bad', 'regex', '(unclosed', NULL, 'Expenses:X', 10, 1, '2026-09-03T10:00:00Z')"
    )
    conn.commit()
    before = conn.execute("SELECT count(*) FROM audit_events").fetchone()[0]
    conn.close()
    rc = main(_argv(db, cfg, "review", "show", stx))
    assert rc == 0
    conn = connect(str(db))
    after = conn.execute("SELECT count(*) FROM audit_events").fetchone()[0]
    assert after == before


def test_safe_mode_blocks_rule_disable(env):
    db, cfg, stx = env
    rc = main(_argv(db, cfg, "rule", "add", "--match-type", "exact", "--pattern", "coffee bar",
                    "--account", "Expenses:Coffee", "--confirm", "rule Expenses:Coffee"))
    assert rc == 0
    conn = connect(str(db))
    rule_id = conn.execute("SELECT rule_id FROM categorization_rules").fetchone()[0]
    conn.close()
    _enable_safe_mode(cfg)
    rc = main(_argv(db, cfg, "rule", "disable", rule_id, "--confirm", f"rule-disable {rule_id}"))
    assert rc == 3
    conn = connect(str(db))
    assert conn.execute(
        "SELECT active FROM categorization_rules WHERE rule_id = ?", (rule_id,)
    ).fetchone()[0] == 1
