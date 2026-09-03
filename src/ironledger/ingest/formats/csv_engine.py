"""A generic CSV statement reader that maps columns through a per-institution profile."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ironledger.conventions import ConventionError, validate_currency
from ironledger.ingest.errors import ConfigError, ParseError
from ironledger.ingest.formats.model import ParsedFile, ParsedRow

__all__ = ["CsvProfile", "load_profile", "parse_amount_to_text", "parse_csv"]

_DECIMAL = re.compile(r"\A-?\d+(?:\.\d+)?\Z")
_SEP_CHARS = str.maketrans({",": "", "$": "", "€": "", "£": "", " ": ""})


@dataclass(frozen=True)
class CsvProfile:
    name: str
    institution_id: str
    account_id: str
    account: str
    date_column: str
    date_formats: tuple[str, ...]
    amount_column: str | None
    debit_column: str | None
    credit_column: str | None
    payee_column: str
    memo_column: str | None
    currency_column: str | None
    default_currency: str | None
    delimiter: str | None


def load_profile(config_dir: str | Path, name: str) -> CsvProfile:
    path = Path(config_dir) / "csv-profiles" / f"{name}.json"
    if not path.is_file():
        raise ConfigError(f"CSV profile {name!r} not found at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc

    has_amount = bool(data.get("amount_column"))
    has_split = bool(data.get("debit_column")) and bool(data.get("credit_column"))
    if not has_amount and not has_split:
        raise ConfigError(
            f"CSV profile {name!r} must set amount_column, or both debit_column and credit_column"
        )
    if not data.get("currency_column") and not data.get("default_currency"):
        raise ConfigError(
            f"CSV profile {name!r} must set currency_column or default_currency"
        )
    try:
        return CsvProfile(
            name=data["name"],
            institution_id=data["institution_id"],
            account_id=data["account_id"],
            account=data["account"],
            date_column=data["date_column"],
            date_formats=tuple(data["date_formats"]),
            amount_column=data.get("amount_column"),
            debit_column=data.get("debit_column"),
            credit_column=data.get("credit_column"),
            payee_column=data["payee_column"],
            memo_column=data.get("memo_column"),
            currency_column=data.get("currency_column"),
            default_currency=data.get("default_currency"),
            delimiter=data.get("delimiter"),
        )
    except KeyError as exc:
        raise ConfigError(f"CSV profile {name!r} is missing key {exc}") from exc


def parse_amount_to_text(value: str) -> str:
    """Normalize one amount cell to a plain signed decimal string."""
    text = value.strip()
    if not text:
        raise ParseError("empty amount cell")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    if text.endswith("-"):
        negative = True
        text = text[:-1]
    if text.startswith("-"):
        negative = not negative
        text = text[1:]
    text = text.translate(_SEP_CHARS)
    if _DECIMAL.match(text) is None:
        raise ParseError(f"amount {value!r} is not a plain decimal")
    normalized = text if not negative else f"-{text}"
    return normalized


def _parse_date(cell: str, formats: tuple[str, ...], row_index: int) -> str:
    for fmt in formats:
        try:
            return datetime.strptime(cell.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    raise ParseError(f"date {cell!r} matches none of {list(formats)}", row_index=row_index)


def _resolve_currency(cell: str | None, profile: CsvProfile, row_index: int) -> str | None:
    code = (cell or "").strip() or profile.default_currency
    if not code:
        raise ParseError("row has no currency and the profile has no default", row_index=row_index)
    try:
        validate_currency(code)
    except ConventionError as exc:
        raise ParseError(f"currency {code!r}: {exc}", row_index=row_index) from exc
    return code


def parse_csv(raw: bytes, profile: CsvProfile) -> ParsedFile:
    text = _decode(raw)
    delimiter = profile.delimiter
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None:
        raise ParseError("CSV has no header row")

    rows: list[ParsedRow] = []
    for row_index, record in enumerate(reader):
        posted_date = _parse_date(record.get(profile.date_column, ""), profile.date_formats, row_index)
        amount_text = _row_amount(record, profile, row_index)
        currency = _resolve_currency(
            record.get(profile.currency_column) if profile.currency_column else None,
            profile,
            row_index,
        )
        rows.append(
            ParsedRow(
                posted_date=posted_date,
                amount_text=amount_text,
                payee=(record.get(profile.payee_column, "") or "").strip(),
                memo=(record.get(profile.memo_column, "") if profile.memo_column else "").strip(),
                txn_type="",
                fitid="",
                currency=currency,
            )
        )
    if not rows:
        raise ParseError("CSV has a header but no data rows")

    return ParsedFile(
        rows=tuple(rows),
        institution_id=profile.institution_id,
        account_id=profile.account_id,
        account=profile.account,
        default_currency=profile.default_currency,
    )


def _row_amount(record: dict[str, str], profile: CsvProfile, row_index: int) -> str:
    if profile.amount_column:
        return parse_amount_to_text(record.get(profile.amount_column, ""))
    debit = (record.get(profile.debit_column or "", "") or "").strip()
    credit = (record.get(profile.credit_column or "", "") or "").strip()
    if debit and credit:
        raise ParseError("row has both a debit and a credit value", row_index=row_index)
    if debit:
        return parse_amount_to_text(f"-{debit}")
    if credit:
        return parse_amount_to_text(credit)
    raise ParseError("row has neither a debit nor a credit value", row_index=row_index)


def _decode(raw: bytes) -> str:
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if raw.startswith(bom):
            return raw.decode(enc)
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ParseError("could not decode CSV bytes as UTF-8, UTF-16, or Latin-1")
