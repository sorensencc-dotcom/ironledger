"""Minimal text-layer parser for Fidelity brokerage statements."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

__all__ = ["FidelityRecord", "parse_fidelity_pdf"]


@dataclass(frozen=True)
class FidelityRecord:
    source_file: str
    account_id: str
    posted_date: str
    description: str
    cusip: str
    quantity: Decimal | None
    price: Decimal | None
    amount_minor: int
    transaction_type: str
    raw_line: str


_ACCOUNT = re.compile(r"(?:Account\s*(?:Number|#)|Account)\s*[:#]?\s*([0-9X* -]{4,})", re.I)
_ROW = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+"
    r"(?P<description>.+?)\s+(?P<cusip>[A-Z0-9]{9}|-)\s+"
    r"(?P<quantity>[+-]?[\d,]+(?:\.\d+)?|-)\s+"
    r"(?P<price>[+-]?\$?[\d,]+(?:\.\d+)?|-)?\s*"
    r"(?P<amount>\(?[+-]?\$?[\d,]+(?:\.\d{2})?\)?)\s*$"
)


def parse_fidelity_pdf(path: str | Path) -> list[FidelityRecord]:
    source = Path(path)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(source)).pages)
    statement_year = _statement_year(source)
    account_id = ""
    records: list[FidelityRecord] = []
    lines = text.splitlines()
    for index, raw_line in enumerate(lines):
        account = _ACCOUNT.search(raw_line)
        if account:
            account_id = account.group(1).strip()
            continue
        normalized = " ".join(raw_line.split())
        normalized = re.sub(r"\s+@\s+1(?:\.0000)?", " - 1", normalized)
        normalized = re.sub(r"\s+@\s+\$?1\.000", " -", normalized)
        match = _ROW.match(normalized)
        if match is None and re.match(r"^\d{1,2}/\d{1,2}\s+", normalized):
            for extra in lines[index + 1:index + 3]:
                normalized = f"{normalized} {' '.join(extra.split())}"
                normalized = re.sub(r"\s+@\s+1(?:\.0000)?", " - 1", normalized)
                normalized = re.sub(r"\s+@\s+\$?1\.000", " -", normalized)
                match = _ROW.match(normalized)
                if match is not None:
                    break
        if not match:
            continue
        values = match.groupdict()
        description = values["description"].strip()
        records.append(FidelityRecord(
            source_file=str(source), account_id=account_id,
            posted_date=_date(values["date"], statement_year), description=description,
            cusip="" if values["cusip"] == "-" else values["cusip"], quantity=_optional_decimal(values["quantity"]),
            price=_optional_decimal(values["price"]), amount_minor=_minor(values["amount"]),
            transaction_type=_transaction_type(description), raw_line=raw_line,
        ))
    return records


def _statement_year(source: Path) -> int:
    match = re.search(r"(?:Statement|statement)\d{4}(\d{4})", source.stem)
    return int(match.group(1)) if match else 2000


def _date(value: str, statement_year: int) -> str:
    parts = value.split("/")
    month, day = parts[:2]
    year = parts[2] if len(parts) == 3 else str(statement_year)
    year = year if len(year) == 4 else str(2000 + int(year))
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace("$", "").replace(",", ""))


def _optional_decimal(value: str | None) -> Decimal | None:
    return None if not value or value == "-" else _decimal(value)


def _minor(value: str) -> int:
    negative = value.startswith("-") or value.startswith("(")
    number = Decimal(value.strip("()$").replace(",", ""))
    cents = int(number * 100)
    return -abs(cents) if negative else cents


def _transaction_type(description: str) -> str:
    text = description.lower()
    for marker, kind in (("buy", "buy"), ("sell", "sell"), ("dividend", "dividend"),
                         ("interest", "interest"), ("fee", "fee"), ("commission", "fee")):
        if marker in text:
            return kind
    return "other"
