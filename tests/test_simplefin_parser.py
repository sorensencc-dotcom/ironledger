# tests/test_simplefin_parser.py
import pytest
from ironledger.ingest.errors import ParseError
from ironledger.ingest.formats.simplefin_engine import parse_amount, simplefin_external_id


@pytest.mark.parametrize("amount_str,expected", [
    ("-12", -1200), ("-0.34", -34), ("+12", 1200),
    ("12", 1200), ("0", 0), ("0.00", 0),
    ("1.50", 150), ("-1.50", -150), ("99.99", 9999),
])
def test_parse_amount_valid(amount_str, expected):
    assert parse_amount(amount_str) == expected


@pytest.mark.parametrize("bad", [
    "1,000", "1.234", "1e2", " 12", "12 ", "", "abc",
])
def test_parse_amount_invalid(bad):
    with pytest.raises(ParseError):
        parse_amount(bad)


def test_primary_id_when_tx_id_present():
    eid = simplefin_external_id("acct123", "tx456", posted_date="2024-01-01",
                                 amount_cents=-1200, currency="USD", description="Coffee", memo="")
    assert eid == "simplefin:id:acct123:tx456"


def test_composite_id_when_tx_id_absent():
    eid = simplefin_external_id("acct123", None, posted_date="2024-01-01",
                                 amount_cents=-1200, currency="USD", description="Coffee", memo="")
    assert eid.startswith("composite:v1:")
    assert len(eid) == len("composite:v1:") + 64


def test_composite_id_when_tx_id_empty_string():
    eid = simplefin_external_id("acct123", "", posted_date="2024-01-01",
                                 amount_cents=-1200, currency="USD", description="Coffee", memo="")
    assert eid.startswith("composite:v1:")
    assert len(eid) == len("composite:v1:") + 64


def test_composite_id_is_account_scoped():
    kwargs = dict(tx_id=None, posted_date="2024-01-01", amount_cents=100,
                  currency="USD", description="X", memo="")
    assert simplefin_external_id("A", **kwargs) != simplefin_external_id("B", **kwargs)


def test_composite_id_is_stable():
    kwargs = dict(account_id="acct123", tx_id=None, posted_date="2024-01-15",
                  amount_cents=500, currency="USD", description="Gas", memo="Station X")
    assert simplefin_external_id(**kwargs) == simplefin_external_id(**kwargs)
