"""Phase 2a: the generic CSV engine — sniffing, sign conventions, currency resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ironledger.ingest.errors import ConfigError, ParseError
from ironledger.ingest.formats.csv_engine import (
    CsvProfile,
    load_profile,
    parse_amount_to_text,
    parse_csv,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _write_profile(config_dir: Path, name: str, body: dict) -> None:
    d = config_dir / "csv-profiles"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")


BASE_PROFILE = {
    "name": "b",
    "institution_id": "b",
    "account_id": "c1",
    "account": "Assets:Bank:Checking:B",
    "date_column": "Date",
    "date_formats": ["%Y-%m-%d", "%m/%d/%Y"],
    "amount_column": "Amount",
    "debit_column": None,
    "credit_column": None,
    "payee_column": "Description",
    "memo_column": "Notes",
    "currency_column": None,
    "default_currency": "USD",
    "delimiter": ",",
}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("-12.99", "-12.99"),
        ("(45.00)", "-45.00"),
        ("45.00-", "-45.00"),
        ("$1,234.56", "1234.56"),
        ("1,000.00", "1000.00"),
    ],
)
def test_parse_amount_to_text_sign_and_separator_conventions(raw: str, expected: str):
    assert parse_amount_to_text(raw) == expected


def test_parse_amount_rejects_non_decimal_residue():
    with pytest.raises(ParseError):
        parse_amount_to_text("twelve dollars")


@pytest.mark.parametrize("raw", ["(-45.00)", "(45.00-)", "(+45.00)"])
def test_parse_amount_rejects_ambiguous_paren_and_explicit_sign(raw: str):
    with pytest.raises(ParseError):
        parse_amount_to_text(raw)


def test_profile_without_currency_source_is_rejected(tmp_path: Path):
    body = dict(BASE_PROFILE, currency_column=None, default_currency=None)
    _write_profile(tmp_path, "nocur", body)
    with pytest.raises(ConfigError):
        load_profile(tmp_path, "nocur")


def test_profile_without_amount_source_is_rejected(tmp_path: Path):
    body = dict(BASE_PROFILE, amount_column=None, debit_column=None, credit_column=None)
    _write_profile(tmp_path, "noamt", body)
    with pytest.raises(ConfigError):
        load_profile(tmp_path, "noamt")


def test_single_amount_column_with_default_currency(tmp_path: Path):
    _write_profile(tmp_path, "b", BASE_PROFILE)
    profile = load_profile(tmp_path, "b")
    pf = parse_csv((FIXTURES / "sample_bank.csv").read_bytes(), profile)
    assert [r.amount_text for r in pf.rows] == ["-12.99", "2000.00", "-45.00"]
    assert [r.posted_date for r in pf.rows] == ["2026-08-15", "2026-08-16", "2026-08-17"]
    assert all((r.currency or pf.default_currency) == "USD" for r in pf.rows)
    assert pf.account == "Assets:Bank:Checking:B"


def test_split_debit_credit_columns(tmp_path: Path):
    body = dict(
        BASE_PROFILE,
        amount_column=None,
        debit_column="Debit",
        credit_column="Credit",
        memo_column=None,
    )
    _write_profile(tmp_path, "split", body)
    profile = load_profile(tmp_path, "split")
    pf = parse_csv((FIXTURES / "sample_split_cols.csv").read_bytes(), profile)
    assert [r.amount_text for r in pf.rows] == ["-12.99", "2000.00"]
    assert pf.rows[0].posted_date == "2026-08-15"


def test_multi_currency_file_is_accepted_per_row(tmp_path: Path):
    body = dict(BASE_PROFILE, currency_column="Currency", default_currency=None, memo_column=None)
    _write_profile(tmp_path, "mc", body)
    profile = load_profile(tmp_path, "mc")
    pf = parse_csv((FIXTURES / "sample_multi_currency.csv").read_bytes(), profile)
    assert [r.currency for r in pf.rows] == ["USD", "EUR"]


def test_unparseable_date_raises_parse_error_with_row_index(tmp_path: Path):
    _write_profile(tmp_path, "b", BASE_PROFILE)
    profile = load_profile(tmp_path, "b")
    bad = b"Date,Description,Notes,Amount\n31-13-2026,X,,-1.00\n"
    with pytest.raises(ParseError) as exc:
        parse_csv(bad, profile)
    assert exc.value.row_index == 0


def test_floating_point_like_amount_with_exponent_is_rejected(tmp_path: Path):
    _write_profile(tmp_path, "b", BASE_PROFILE)
    profile = load_profile(tmp_path, "b")
    bad = b"Date,Description,Notes,Amount\n2026-08-15,X,,1e3\n"
    with pytest.raises(ParseError):
        parse_csv(bad, profile)
