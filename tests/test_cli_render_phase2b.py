"""Phase 2b: render helpers for review show and rule list."""

from __future__ import annotations

import json

from ironledger.cli.render import render_review_show, render_rule_list


def _row():
    return {
        "staged_transaction_id": "stx:abc", "status": "categorized", "payee": "COFFEE BAR",
        "proposed_date": "2026-08-15", "identity_method": "sha256_fallback",
        "identity_fingerprint": "d" * 64, "source_record_id": "doc-1:0",
    }


def _postings():
    return [
        {"role": "imported", "account": "Assets:Bank:Checking", "minor_units": -1299, "currency": "USD"},
        {"role": "contra", "account": "Expenses:Coffee", "minor_units": 1299, "currency": "USD"},
    ]


def test_review_show_text_contains_key_fields():
    out = render_review_show(_row(), _postings(), None, as_json=False)
    assert "stx:abc" in out and "COFFEE BAR" in out and "Expenses:Coffee" in out


def test_review_show_json_roundtrips():
    out = render_review_show(_row(), _postings(), "Expenses:Coffee", as_json=True)
    data = json.loads(out)
    assert data["rule_suggestion"] == "Expenses:Coffee"
    assert len(data["postings"]) == 2


def test_rule_list_empty():
    assert render_rule_list([], as_json=False) == "no categorization rules"


def test_rule_list_text_line():
    rows = [{
        "rule_id": "rule:1", "match_type": "exact", "pattern": "coffee bar",
        "importing_account": None, "target_account": "Expenses:Coffee",
        "priority": 50, "active": 1, "created_at_utc": "2026-09-03T10:00:00Z",
        "disabled_at_utc": None,
    }]
    out = render_rule_list(rows, as_json=False)
    assert "rule:1" in out and "Expenses:Coffee" in out and "active" in out
