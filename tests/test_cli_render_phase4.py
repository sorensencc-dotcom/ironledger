# tests/test_cli_render_phase4.py
from __future__ import annotations

import json

from ironledger.cli.render import (
    render_balances,
    render_project_status,
    render_search_hits,
)
from ironledger.project.query import BalanceRow, SearchHit


def test_render_search_human_and_json():
    hit = SearchHit(
        entry_date="2026-09-01",
        payee="Coffee Shop",
        narration="Latte",
        account="Expenses:Food",
        minor_units=1234,
        currency="USD",
        staged_transaction_id="stx-1",
        posting_id="stx-1:contra",
    )
    human = render_search_hits([hit], as_json=False)
    assert "2026-09-01" in human
    assert "Coffee Shop" in human
    assert "Latte" in human
    assert "Expenses:Food" in human
    assert "1234" in human
    assert "USD" in human
    assert "stx-1" in human
    payload = json.loads(render_search_hits([hit], as_json=True))
    assert payload[0]["staged_transaction_id"] == "stx-1"


def test_render_balances_never_nets_currencies():
    rows = [
        BalanceRow("Assets:Checking", -1234, "USD", 2),
        BalanceRow("Assets:Checking", -100, "EUR", 2),
    ]
    human = render_balances(rows, as_json=False)
    assert "USD" in human and "EUR" in human
    assert human.count("Assets:Checking") == 2


def test_render_project_status_omits_compile_when_absent():
    text = render_project_status(
        {"status": "ok", "ledger_output_hash": "a" * 64, "hash_matches_files": True},
        as_json=True,
    )
    payload = json.loads(text)
    assert "latest_run" not in payload
