"""Parse OFX 1.x SGML, OFX 2.x XML, and QFX into a ParsedFile via ofxtools."""

from __future__ import annotations

import io

from ironledger.ingest.errors import ParseError
from ironledger.ingest.formats.model import ParsedFile, ParsedRow

__all__ = ["parse_ofx"]


def parse_ofx(raw: bytes) -> ParsedFile:
    """Return a ParsedFile for one OFX/QFX statement. Raise ParseError on anything unusable."""
    try:
        from ofxtools.Parser import OFXTree
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ParseError(f"ofxtools is not installed: {exc}") from exc

    tree = OFXTree()
    try:
        tree.parse(io.BytesIO(raw))
        ofx = tree.convert()
    except Exception as exc:  # ofxtools raises a range of parse/convert errors
        raise ParseError(f"could not parse OFX: {exc}") from exc

    statements = getattr(ofx, "statements", None) or []
    if not statements:
        raise ParseError("OFX file contains no statements")
    stmt = statements[0]

    acct = getattr(stmt, "account", None)
    institution_id = str(getattr(acct, "bankid", "") or getattr(acct, "brokerid", "") or "")
    account_id = str(getattr(acct, "acctid", "") or "")
    if not institution_id or not account_id:
        raise ParseError("OFX statement is missing BANKACCTFROM/CCACCTFROM identity")

    default_currency = str(getattr(stmt, "curdef", "") or "") or None

    transactions = list(getattr(stmt, "transactions", []) or [])
    if not transactions:
        raise ParseError("OFX statement has no transactions")

    rows: list[ParsedRow] = []
    for txn in transactions:
        dt = getattr(txn, "dtposted", None)
        if dt is None:
            raise ParseError("OFX transaction is missing DTPOSTED")
        posted_date = dt.date().isoformat()
        amount = getattr(txn, "trnamt", None)
        if amount is None:
            raise ParseError("OFX transaction is missing TRNAMT")
        rows.append(
            ParsedRow(
                posted_date=posted_date,
                amount_text=str(amount),
                payee=str(getattr(txn, "name", "") or ""),
                memo=str(getattr(txn, "memo", "") or ""),
                txn_type=str(getattr(txn, "trntype", "") or ""),
                fitid=str(getattr(txn, "fitid", "") or ""),
                currency=str(getattr(txn, "currency", "") or "") or None,
            )
        )

    return ParsedFile(
        rows=tuple(rows),
        institution_id=institution_id,
        account_id=account_id,
        account=None,
        default_currency=default_currency,
    )
