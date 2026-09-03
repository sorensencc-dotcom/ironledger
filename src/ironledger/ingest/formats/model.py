"""The common shape every format parser produces."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ParsedRow", "ParsedFile", "institution_account_key"]


@dataclass(frozen=True)
class ParsedRow:
    """One transaction as it appeared in the source file, before normalization."""

    posted_date: str          # YYYY-MM-DD, institution local calendar date, unaltered
    amount_text: str          # raw amount string exactly as it appeared
    payee: str
    memo: str
    txn_type: str
    fitid: str                # "" when the record carried no FITID
    currency: str | None      # ISO code when the record carried one


@dataclass(frozen=True)
class ParsedFile:
    """A parsed statement: its rows plus the identity of the source account."""

    rows: tuple[ParsedRow, ...]
    institution_id: str
    account_id: str
    account: str | None       # IronLedger account name if a profile mapped it
    default_currency: str | None


def institution_account_key(parsed: ParsedFile) -> str:
    """The stable key that keeps identical amounts at two institutions from colliding."""
    return f"{parsed.institution_id}/{parsed.account_id}"
