"""Phase 2a: OFX 1.x SGML and OFX 2.x XML parsing into a ParsedFile."""

from __future__ import annotations

from pathlib import Path

import pytest

from ironledger.ingest.errors import ParseError
from ironledger.ingest.formats.model import institution_account_key
from ironledger.ingest.formats.ofx import parse_ofx

FIXTURES = Path(__file__).parent / "fixtures"


def test_parses_sgml_v1_statement():
    pf = parse_ofx((FIXTURES / "sample_v1.ofx").read_bytes())
    assert pf.institution_id == "121000248"
    assert pf.account_id == "1234567890"
    assert institution_account_key(pf) == "121000248/1234567890"
    assert len(pf.rows) == 2
    debit = pf.rows[0]
    assert debit.posted_date == "2026-08-15"
    assert debit.amount_text == "-12.99"
    assert debit.payee == "COFFEE BAR"
    assert debit.fitid == "2026081500001"
    assert (debit.currency or pf.default_currency) == "USD"


def test_parses_xml_v2_statement():
    pf = parse_ofx((FIXTURES / "sample_v2.ofx").read_bytes())
    assert pf.institution_id == "99900001"
    assert pf.default_currency == "EUR"
    assert pf.rows[0].payee == "BAKERY"
    assert pf.rows[0].posted_date == "2026-08-10"


def test_malformed_ofx_raises_parse_error():
    with pytest.raises(ParseError):
        parse_ofx(b"this is not ofx at all")


def test_empty_statement_raises_parse_error():
    empty = b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102

<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>USD
<BANKACCTFROM><BANKID>1<ACCTID>2<ACCTTYPE>CHECKING</BANKACCTFROM>
<BANKTRANLIST><DTSTART>20260801<DTEND>20260831</BANKTRANLIST>
</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""
    with pytest.raises(ParseError):
        parse_ofx(empty)
