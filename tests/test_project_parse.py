from __future__ import annotations

from pathlib import Path

from ironledger.compile.render import format_amount
from ironledger.project.parse import parse_amount, parse_ledger, unescape_beancount_string
from tests.project_fixtures import make_jpy_set, make_sample_set, write_rendered_ledger


def test_parse_amount_inverts_format_amount():
    assert parse_amount(format_amount(-1234, 2), 2) == -1234
    assert parse_amount(format_amount(1234, 2), 2) == 1234
    assert parse_amount(format_amount(50, 2), 2) == 50
    assert parse_amount(format_amount(100, 0), 0) == 100
    assert parse_amount(format_amount(-5, 3), 3) == -5


def test_unescape_inverts_escape():
    assert unescape_beancount_string('Coffee \\"Shop\\"\\\\Cafe') == 'Coffee "Shop"\\Cafe'


def test_parse_ledger_round_trip_preserves_fields(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    parsed = parse_ledger(ledger_dir)

    assert parsed.operating_currencies == ("USD",)
    accounts = {a.account: a for a in parsed.accounts}
    assert accounts["Assets:Checking"].currency == "USD"
    assert accounts["Assets:Checking"].open_date == "2026-09-01"
    assert accounts["Expenses:Food"].currency == "USD"

    assert len(parsed.entries) == 1
    entry = parsed.entries[0]
    assert entry.entry_id == "stx-1"
    assert entry.staged_transaction_id == "stx-1"
    assert entry.entry_date == "2026-09-01"
    assert entry.payee == 'Coffee "Shop"\\Cafe'
    assert entry.narration == "Latte"
    assert len(entry.postings) == 2

    imported, contra = entry.postings
    assert imported.role == "imported"
    assert imported.posting_id == "stx-1:imported"
    assert imported.account == "Assets:Checking"
    assert imported.minor_units == -1234
    assert imported.currency == "USD"
    assert imported.minor_unit_scale == 2
    assert imported.source_document_id == "doc-1"
    assert imported.source_record_id == "rec-1"
    assert imported.identity_algo_version == 1
    assert imported.identity_method == "fitid"

    assert contra.role == "contra"
    assert contra.posting_id == "stx-1:contra"
    assert contra.account == "Expenses:Food"
    assert contra.minor_units == 1234


def test_parse_jpy_scale_zero_does_not_count_decimal_digits(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_jpy_set())
    parsed = parse_ledger(ledger_dir)
    imported = parsed.entries[0].postings[0]
    assert imported.currency == "JPY"
    assert imported.minor_unit_scale == 0
    assert imported.minor_units == -100
