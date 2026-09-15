"""Text-layer PDF statement reader mapped through a per-institution profile."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

from ironledger.ingest.errors import ConfigError, ParseError
from ironledger.ingest.formats.csv_engine import parse_amount_to_text
from ironledger.ingest.formats.model import ParsedFile, ParsedRow

__all__ = ["PdfProfile", "load_pdf_profile", "parse_pdf"]


@dataclass(frozen=True)
class PdfProfile:
    name: str
    institution_id: str
    account_id: str
    account: str
    default_currency: str
    date_formats: tuple[str, ...]
    date_window_days: int
    sign: str
    line_pattern: str


def load_pdf_profile(config_dir: str | Path, name: str) -> PdfProfile:
    path = Path(config_dir).joinpath("pdf-profiles", f"{name}.json")
    if not path.is_file():
        raise ConfigError(f"PDF profile {name!r} not found at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    sign = data.get("sign", "as_printed")
    if sign not in ("as_printed", "invert"):
        raise ConfigError(f"PDF profile {name!r} sign must be as_printed or invert")
    window = data.get("date_window_days", 3)
    if not isinstance(window, int) or isinstance(window, bool) or window < 0:
        raise ConfigError(f"PDF profile {name!r} date_window_days must be a non-negative int")
    try:
        return PdfProfile(
            name=data["name"],
            institution_id=data["institution_id"],
            account_id=data["account_id"],
            account=data["account"],
            default_currency=data["default_currency"],
            date_formats=tuple(data["date_formats"]),
            date_window_days=window,
            sign=sign,
            line_pattern=data["line_pattern"],
        )
    except KeyError as exc:
        raise ConfigError(f"PDF profile {name!r} is missing key {exc}") from exc


def parse_pdf(raw: bytes, profile: PdfProfile) -> ParsedFile:
    text = _extract_text(raw)
    if not text.strip():
        raise ParseError("PDF has an empty text layer")
    pattern = re.compile(profile.line_pattern)
    rows: list[ParsedRow] = []
    for line in text.splitlines():
        match = pattern.search(line)
        if match is None:
            continue
        posted = _parse_date(match.group("date"), profile.date_formats)
        amount = parse_amount_to_text(match.group("amount"))
        if profile.sign == "invert":
            amount = amount[1:] if amount.startswith("-") else f"-{amount}"
        rows.append(
            ParsedRow(
                posted_date=posted,
                amount_text=amount,
                payee=match.group("payee").strip(),
                memo="",
                txn_type="",
                fitid="",
                currency=profile.default_currency,
            )
        )
    if not rows:
        raise ParseError("PDF text layer contained no statement rows")
    return ParsedFile(
        rows=tuple(rows),
        institution_id=profile.institution_id,
        account_id=profile.account_id,
        account=profile.account,
        default_currency=profile.default_currency,
    )


def _extract_text(raw: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(raw))
    except PdfReadError as exc:
        raise ParseError(f"PDF is unreadable: {exc}") from exc
    if reader.is_encrypted:
        raise ParseError("PDF is encrypted")
    try:
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
    except FileNotDecryptedError as exc:
        raise ParseError("PDF is encrypted") from exc
    return "\n".join(pages)


def _parse_date(cell: str, formats: tuple[str, ...]) -> str:
    for fmt in formats:
        try:
            return datetime.strptime(cell.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    raise ParseError(f"date {cell!r} matched no profile format")
