"""Closed-dialect parser: exact inverse of compile.render.render_ledger."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from ironledger.conventions import ConventionError, currency_scale, validate_account_name, validate_currency
from ironledger.project.errors import ProjectParseError, format_parse_error

_TITLE_RE = re.compile(r'option "title" "(.*)"')
_OPERATING_CURRENCY_RE = re.compile(r'option "operating_currency" "(.*)"')
_INCLUDE_ACCOUNTS = 'include "accounts.beancount"'
_INCLUDE_YEAR_RE = re.compile(r'include "txns/(\d{4})\.beancount"')
_OPEN_RE = re.compile(r"(\d{4}-\d{2}-\d{2}) open (\S+) ([A-Z]{3})")
_ENTRY_HEADER_RE = re.compile(r'(\d{4}-\d{2}-\d{2}) \* "(.*)" "(.*)"')
_STAGED_TX_RE = re.compile(r'  staged-transaction-id: "(.*)"')
_POSTING_RE = re.compile(r"  (\S+)  (\S+) ([A-Z]{3})")
_META_RE = re.compile(r'    ([A-Za-z0-9-]+): "(.*)"')

_POSTING_META_KEYS = (
    "source-document-id",
    "source-record-id",
    "identity-algo-version",
    "identity-method",
)

_ROLES = ("imported", "contra")


@dataclass(frozen=True)
class ParsedAccount:
    account: str
    currency: str
    open_date: str


@dataclass(frozen=True)
class ParsedPosting:
    posting_id: str
    entry_id: str
    account: str
    minor_units: int
    currency: str
    minor_unit_scale: int
    source_document_id: str
    source_record_id: str
    identity_algo_version: int
    identity_method: str
    role: str


@dataclass(frozen=True)
class ParsedEntry:
    entry_id: str
    entry_date: str
    payee: str
    narration: str
    staged_transaction_id: str
    postings: tuple[ParsedPosting, ...]


@dataclass(frozen=True)
class ParsedLedger:
    title: str
    operating_currencies: tuple[str, ...]
    accounts: tuple[ParsedAccount, ...]
    entries: tuple[ParsedEntry, ...]
    year_files: tuple[str, ...]


def parse_amount(amount_str: str, scale: int) -> int:
    """Exact inverse of format_amount. Caller supplies the ISO-4217 scale."""
    if not isinstance(amount_str, str) or amount_str == "":
        _raise_amount_error(amount_str, scale)
    sign = -1 if amount_str[0] == "-" else 1
    rest = amount_str[1:] if amount_str[0] == "-" else amount_str
    if rest == "":
        _raise_amount_error(amount_str, scale)
    if scale == 0:
        if "." in rest or not rest.isdigit():
            _raise_amount_error(amount_str, scale)
        return sign * int(rest)
    if rest.count(".") != 1:
        _raise_amount_error(amount_str, scale)
    whole, frac = rest.split(".", 1)
    if not whole.isdigit() or not frac.isdigit() or len(frac) != scale:
        _raise_amount_error(amount_str, scale)
    return sign * (int(whole) * 10**scale + int(frac))


def unescape_beancount_string(val: str) -> str:
    """Inverse of escape_beancount_string (\\\\ and \\\" only)."""
    out: list[str] = []
    i = 0
    n = len(val)
    while i < n:
        if val[i] == "\\" and i + 1 < n and val[i + 1] in '\\"':
            out.append(val[i + 1])
            i += 2
            continue
        out.append(val[i])
        i += 1
    return "".join(out)


def discover_year_files(ledger_dir: Path) -> list[str]:
    """Return txns/*.beancount as txns/{name}, same glob as compile status."""
    txns_dir = ledger_dir / "txns"
    if not txns_dir.exists():
        return []
    return [f"txns/{p.name}" for p in sorted(txns_dir.glob("*.beancount"))]


def parse_ledger(ledger_dir: Path) -> ParsedLedger:
    title, operating_currencies, year_includes = _parse_main(ledger_dir)
    discovered = discover_year_files(ledger_dir)
    if set(year_includes) != set(discovered):
        raise _parse_error(
            "main.beancount",
            0,
            "include set disagrees with txns/*.beancount glob",
            'include "txns/"',
        )
    accounts = _parse_accounts(ledger_dir)
    seen_stx: set[str] = set()
    entries: list[ParsedEntry] = []
    for rel in year_includes:
        entries.extend(_parse_year_file(ledger_dir / rel, rel, seen_stx))
    return ParsedLedger(
        title=title,
        operating_currencies=operating_currencies,
        accounts=accounts,
        entries=tuple(entries),
        year_files=tuple(discovered),
    )


def _raise_amount_error(amount_str: str, scale: int) -> NoReturn:
    raise ProjectParseError(
        f"amount {amount_str!r} is not exactly representable at scale {scale}",
        path="",
        line_no=0,
        snippet=str(amount_str),
    )


def _parse_error(path: str, line_no: int, reason: str, snippet: str) -> ProjectParseError:
    return ProjectParseError(
        format_parse_error(path, line_no, reason, snippet),
        path=path,
        line_no=line_no,
        snippet=snippet,
    )


def _read_nonblank_lines(path: Path, rel: str) -> list[tuple[int, str]]:
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError as exc:
        raise _parse_error(rel, 0, f"missing file {rel}", "") from exc
    except UnicodeDecodeError as exc:
        raise _parse_error(rel, 0, "file is not valid UTF-8", "") from exc
    rows: list[tuple[int, str]] = []
    for i, line in enumerate(text.split("\n"), start=1):
        if line == "":
            continue
        rows.append((i, line))
    return rows


class _Cursor:
    def __init__(self, rows: list[tuple[int, str]]) -> None:
        self._rows = rows
        self._i = 0

    def peek(self) -> tuple[int, str] | None:
        if self._i >= len(self._rows):
            return None
        return self._rows[self._i]

    def pop(self) -> tuple[int, str] | None:
        item = self.peek()
        if item is not None:
            self._i += 1
        return item


def _parse_main(ledger_dir: Path) -> tuple[str, tuple[str, ...], list[str]]:
    rel = "main.beancount"
    cur = _Cursor(_read_nonblank_lines(ledger_dir / rel, rel))
    item = cur.pop()
    if item is None:
        raise _parse_error(rel, 0, "missing option title", "")
    line_no, line = item
    title_m = _TITLE_RE.fullmatch(line)
    if title_m is None:
        raise _parse_error(rel, line_no, "unknown directive", line)
    title = unescape_beancount_string(title_m.group(1))

    currencies: list[str] = []
    while True:
        peeked = cur.peek()
        if peeked is None:
            break
        line_no, line = peeked
        curr_m = _OPERATING_CURRENCY_RE.fullmatch(line)
        if curr_m is None:
            break
        cur.pop()
        curr = curr_m.group(1)
        try:
            validate_currency(curr)
        except ConventionError as exc:
            raise _parse_error(rel, line_no, f"unknown currency: {exc}", line) from exc
        currencies.append(curr)

    item = cur.pop()
    if item is None or item[1] != _INCLUDE_ACCOUNTS:
        line_no, line = item if item is not None else (0, "")
        raise _parse_error(rel, line_no, "missing include accounts.beancount", line)

    year_includes: list[str] = []
    while True:
        peeked = cur.peek()
        if peeked is None:
            break
        line_no, line = peeked
        year_m = _INCLUDE_YEAR_RE.fullmatch(line)
        if year_m is None:
            raise _parse_error(rel, line_no, "unknown directive", line)
        cur.pop()
        year_includes.append(f"txns/{year_m.group(1)}.beancount")
    return title, tuple(currencies), year_includes


def _parse_accounts(ledger_dir: Path) -> tuple[ParsedAccount, ...]:
    rel = "accounts.beancount"
    accounts: list[ParsedAccount] = []
    for line_no, line in _read_nonblank_lines(ledger_dir / rel, rel):
        open_m = _OPEN_RE.fullmatch(line)
        if open_m is None:
            raise _parse_error(rel, line_no, "unknown directive", line)
        open_date, account, currency = open_m.groups()
        try:
            validate_account_name(account)
        except ConventionError as exc:
            raise _parse_error(rel, line_no, f"invalid account: {exc}", line) from exc
        try:
            validate_currency(currency)
        except ConventionError as exc:
            raise _parse_error(rel, line_no, f"unknown currency: {exc}", line) from exc
        accounts.append(ParsedAccount(account=account, currency=currency, open_date=open_date))
    return tuple(accounts)


def _parse_year_file(path: Path, rel: str, seen_stx: set[str]) -> list[ParsedEntry]:
    cur = _Cursor(_read_nonblank_lines(path, rel))
    entries: list[ParsedEntry] = []
    while True:
        item = cur.pop()
        if item is None:
            break
        line_no, line = item
        header_m = _ENTRY_HEADER_RE.fullmatch(line)
        if header_m is None:
            raise _parse_error(rel, line_no, "unknown directive", line)
        entry_date = header_m.group(1)
        payee = unescape_beancount_string(header_m.group(2))
        narration = unescape_beancount_string(header_m.group(3))

        meta_item = cur.pop()
        if meta_item is None:
            raise _parse_error(rel, line_no, "missing required metadata staged-transaction-id", line)
        meta_no, meta_line = meta_item
        stx_m = _STAGED_TX_RE.fullmatch(meta_line)
        if stx_m is None:
            raise _parse_error(rel, meta_no, "missing required metadata staged-transaction-id", meta_line)
        staged_transaction_id = unescape_beancount_string(stx_m.group(1))
        if staged_transaction_id in seen_stx:
            raise _parse_error(
                rel, meta_no, f"duplicate staged-transaction-id {staged_transaction_id}", meta_line
            )
        seen_stx.add(staged_transaction_id)

        postings = [
            _parse_posting(cur, rel, staged_transaction_id, role)
            for role in _ROLES
        ]
        peeked = cur.peek()
        if peeked is not None and _POSTING_RE.fullmatch(peeked[1]):
            raise _parse_error(rel, peeked[0], "third posting is not allowed", peeked[1])
        entries.append(
            ParsedEntry(
                entry_id=staged_transaction_id,
                entry_date=entry_date,
                payee=payee,
                narration=narration,
                staged_transaction_id=staged_transaction_id,
                postings=tuple(postings),
            )
        )
    return entries


def _parse_posting(cur: _Cursor, rel: str, staged_transaction_id: str, role: str) -> ParsedPosting:
    item = cur.pop()
    if item is None:
        raise _parse_error(rel, 0, f"missing {role} posting", "")
    line_no, line = item
    posting_m = _POSTING_RE.fullmatch(line)
    if posting_m is None:
        raise _parse_error(rel, line_no, f"missing {role} posting", line)
    account, amount_str, currency = posting_m.groups()
    try:
        validate_account_name(account)
    except ConventionError as exc:
        raise _parse_error(rel, line_no, f"invalid account: {exc}", line) from exc
    try:
        scale = currency_scale(currency)
    except ConventionError as exc:
        raise _parse_error(rel, line_no, f"unknown currency: {exc}", line) from exc
    try:
        minor_units = parse_amount(amount_str, scale)
    except ProjectParseError as exc:
        raise _parse_error(rel, line_no, str(exc), line) from exc

    meta = _parse_posting_metadata(cur, rel)
    try:
        identity_algo_version = int(meta["identity-algo-version"])
    except ValueError as exc:
        raise _parse_error(rel, line_no, "identity-algo-version is not an int", line) from exc
    return ParsedPosting(
        posting_id=f"{staged_transaction_id}:{role}",
        entry_id=staged_transaction_id,
        account=account,
        minor_units=minor_units,
        currency=currency,
        minor_unit_scale=scale,
        source_document_id=meta["source-document-id"],
        source_record_id=meta["source-record-id"],
        identity_algo_version=identity_algo_version,
        identity_method=meta["identity-method"],
        role=role,
    )


def _parse_posting_metadata(cur: _Cursor, rel: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for expected in _POSTING_META_KEYS:
        item = cur.pop()
        if item is None:
            raise _parse_error(rel, 0, f"missing required metadata {expected}", "")
        line_no, line = item
        meta_m = _META_RE.fullmatch(line)
        if meta_m is None:
            raise _parse_error(rel, line_no, f"missing required metadata {expected}", line)
        key, raw = meta_m.groups()
        if key != expected:
            if key not in _POSTING_META_KEYS:
                raise _parse_error(rel, line_no, f"extra metadata key {key}", line)
            raise _parse_error(rel, line_no, f"missing required metadata {expected}", line)
        values[key] = unescape_beancount_string(raw)
    peeked = cur.peek()
    if peeked is not None:
        extra_m = _META_RE.fullmatch(peeked[1])
        if extra_m is not None:
            raise _parse_error(rel, peeked[0], f"extra metadata key {extra_m.group(1)}", peeked[1])
    return values
