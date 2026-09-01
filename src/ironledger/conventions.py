"""Canonical ledger conventions for IronLedger Phase 1.

This module locks the *policy and validation rules* for accounts, currencies,
monetary amounts, timestamps, and source links. It does not generate import
identities, parse institution files, or write the ledger; those are later
phases. The concrete chart of accounts stays deferred to the first authorized
import (Phase 0 decision D-6).

Conventions locked here (see docs/meta/phases/ironledger-phase-0-threat-model-baseline.md):

- Accounts: five Beancount roots; colon-separated PascalCase ASCII segments;
  minimum depth two; every account constrained to a single currency at `open`.
- Currency: ISO-4217 alphabetic codes validated against a versioned static
  table. Currency is part of monetary identity. Unlike currencies are never
  netted.
- Amounts: signed integer minor units plus an explicit currency and an explicit
  scale. The scale must equal the currency table's scale for that currency.
  No floating-point value is ever accepted on an accounting path.
- Timestamps: UTC, ISO-8601 with an explicit ``Z``, second precision or finer.
- Source links: every entry and posting carries a source-document id, a
  source-record id, an immutable identity-algorithm version, and an
  identity-method discriminator (``fitid`` or ``sha256_fallback``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from typing import Any, Final

__all__ = [
    "ConventionError",
    "ACCOUNT_ROOTS",
    "CURRENCY_TABLE_VERSION",
    "IDENTITY_METHODS",
    "LEDGER_LAYOUT",
    "load_currency_table",
    "currency_scale",
    "validate_account_name",
    "validate_currency",
    "validate_amount_minor_units",
    "validate_utc_timestamp",
    "validate_source_link",
    "validate_same_currency_balance",
    "validate_convention_sample",
]


class ConventionError(ValueError):
    """A value violates a locked Phase 1 convention."""


# --- Accounts ---------------------------------------------------------------

ACCOUNT_ROOTS: Final[tuple[str, ...]] = (
    "Assets",
    "Liabilities",
    "Equity",
    "Income",
    "Expenses",
)

# One segment: an uppercase letter, then letters, digits, or internal hyphens.
_ACCOUNT_SEGMENT: Final[re.Pattern[str]] = re.compile(r"[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*\Z")
_MIN_ACCOUNT_DEPTH: Final[int] = 2


def validate_account_name(name: str) -> str:
    """Return ``name`` unchanged if it is a well-formed account name."""
    if not isinstance(name, str) or not name:
        raise ConventionError("account name must be a non-empty string")
    segments = name.split(":")
    if len(segments) < _MIN_ACCOUNT_DEPTH:
        raise ConventionError(
            f"account {name!r} must have at least {_MIN_ACCOUNT_DEPTH} colon-separated segments"
        )
    if segments[0] not in ACCOUNT_ROOTS:
        raise ConventionError(
            f"account {name!r} root {segments[0]!r} is not one of {ACCOUNT_ROOTS}"
        )
    for segment in segments:
        if not _ACCOUNT_SEGMENT.match(segment):
            raise ConventionError(
                f"account {name!r} segment {segment!r} is not PascalCase ASCII"
            )
    return name


# --- Currency and amounts -------------------------------------------------

CURRENCY_TABLE_VERSION: Final[str] = "2026-01"
_CURRENCY_CODE: Final[re.Pattern[str]] = re.compile(r"[A-Z]{3}\Z")
_MAX_MINOR_UNITS: Final[int] = 2**63 - 1
_MIN_MINOR_UNITS: Final[int] = -(2**63)

_currency_table_cache: dict[str, dict[str, Any]] | None = None


def load_currency_table() -> dict[str, dict[str, Any]]:
    """Load and cache the pinned ISO-4217 table for ``CURRENCY_TABLE_VERSION``."""
    global _currency_table_cache
    if _currency_table_cache is None:
        raw = (
            resources.files("ironledger.reference")
            .joinpath(f"iso4217.v{CURRENCY_TABLE_VERSION}.json")
            .read_text(encoding="utf-8")
        )
        parsed = json.loads(raw)
        if parsed.get("table_version") != CURRENCY_TABLE_VERSION:
            raise ConventionError(
                f"currency table version mismatch: file says {parsed.get('table_version')!r}, "
                f"expected {CURRENCY_TABLE_VERSION!r}"
            )
        _currency_table_cache = parsed["currencies"]
    return _currency_table_cache


def validate_currency(code: str) -> str:
    """Return ``code`` unchanged if it is a known ISO-4217 alphabetic code."""
    if not isinstance(code, str) or not _CURRENCY_CODE.match(code):
        raise ConventionError(f"currency {code!r} is not a three-letter uppercase ISO-4217 code")
    if code not in load_currency_table():
        raise ConventionError(
            f"currency {code!r} is not in pinned table v{CURRENCY_TABLE_VERSION}"
        )
    return code


def currency_scale(code: str) -> int:
    """Return the minor-unit scale for a known currency."""
    validate_currency(code)
    return int(load_currency_table()[code]["minor_unit_scale"])


def validate_amount_minor_units(minor_units: int, currency: str, scale: int) -> int:
    """Validate a monetary amount expressed in signed integer minor units.

    ``bool`` is rejected explicitly because it is an ``int`` subclass. Floats and
    numeric strings are rejected: an accounting amount is always an ``int``.
    """
    if isinstance(minor_units, bool) or not isinstance(minor_units, int):
        raise ConventionError("amount minor_units must be a plain int, not float, str, or bool")
    if not _MIN_MINOR_UNITS <= minor_units <= _MAX_MINOR_UNITS:
        raise ConventionError("amount minor_units is outside the signed 64-bit range")
    expected = currency_scale(currency)
    if not isinstance(scale, int) or isinstance(scale, bool):
        raise ConventionError("amount scale must be a plain int")
    if scale != expected:
        raise ConventionError(
            f"amount scale {scale} does not match currency {currency} table scale {expected}"
        )
    return minor_units


# --- Timestamps ----------------------------------------------------------

# ISO-8601, date, and time, explicit trailing Z, optional fractional seconds.
_UTC_TIMESTAMP: Final[re.Pattern[str]] = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z"
)


def validate_utc_timestamp(value: str) -> str:
    """Return ``value`` unchanged if it is an ISO-8601 UTC instant ending in ``Z``."""
    if not isinstance(value, str) or not _UTC_TIMESTAMP.match(value):
        raise ConventionError(
            f"timestamp {value!r} must be ISO-8601 UTC with an explicit trailing Z"
        )
    # Reject values that match the shape but are not real instants (e.g. month 13).
    try:
        datetime.strptime(value.split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise ConventionError(f"timestamp {value!r} is not a valid instant: {exc}") from exc
    return value


# --- Source links ------------------------------------------------------

IDENTITY_METHODS: Final[tuple[str, ...]] = ("fitid", "sha256_fallback")


@dataclass(frozen=True)
class SourceLink:
    """The source-identity linkage carried by every entry and posting."""

    source_document_id: str
    source_record_id: str
    identity_algo_version: int
    identity_method: str


def validate_source_link(link: dict[str, Any]) -> SourceLink:
    """Validate the source-link metadata dictionary and return a ``SourceLink``."""
    if not isinstance(link, dict):
        raise ConventionError("source link must be a dict")
    missing = {"source_document_id", "source_record_id", "identity_algo_version", "identity_method"} - set(link)
    if missing:
        raise ConventionError(f"source link is missing keys: {sorted(missing)}")
    for key in ("source_document_id", "source_record_id"):
        if not isinstance(link[key], str) or not link[key]:
            raise ConventionError(f"source link {key} must be a non-empty string")
    version = link["identity_algo_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ConventionError("source link identity_algo_version must be an int >= 1")
    if link["identity_method"] not in IDENTITY_METHODS:
        raise ConventionError(
            f"source link identity_method {link['identity_method']!r} is not one of {IDENTITY_METHODS}"
        )
    return SourceLink(
        source_document_id=link["source_document_id"],
        source_record_id=link["source_record_id"],
        identity_algo_version=version,
        identity_method=link["identity_method"],
    )


# --- Ledger layout -----------------------------------------------------

LEDGER_LAYOUT: Final[dict[str, str]] = {
    "ledger/main.beancount": "Root file. Contains only include directives and global options.",
    "ledger/accounts.beancount": "Every account's open directive, each with a single-currency constraint.",
    "ledger/txns/": "Compiled transaction entries, one file per calendar year (YYYY.beancount).",
}


# --- Transaction balancing ---------------------------------------------

def validate_same_currency_balance(postings: list[dict[str, Any]]) -> dict[str, int]:
    """Validate that a list of postings balances to zero for each currency.

    Unlike currencies are never netted against each other. Every currency
    present in the postings must independently sum to zero minor units.
    All postings are validated for account grammar, currency code, and
    minor-unit scale.
    """
    if not isinstance(postings, (list, tuple)) or len(postings) < 2:
        raise ConventionError("postings must be a sequence of at least 2 entries")

    currency_totals: dict[str, int] = {}
    for posting in postings:
        if not isinstance(posting, dict):
            raise ConventionError("each posting must be a dict")
        required = {"account", "currency", "minor_units", "scale"}
        missing = required - set(posting)
        if missing:
            raise ConventionError(f"posting is missing keys: {sorted(missing)}")
        validate_account_name(posting["account"])
        validate_currency(posting["currency"])
        validate_amount_minor_units(posting["minor_units"], posting["currency"], posting["scale"])
        if posting["minor_units"] == 0:
            raise ConventionError("posting minor_units must be non-zero")

        curr = posting["currency"]
        currency_totals[curr] = currency_totals.get(curr, 0) + posting["minor_units"]

    for curr, total in currency_totals.items():
        if total != 0:
            raise ConventionError(
                f"postings do not balance for currency {curr!r}: net balance is {total} minor units"
            )
    return currency_totals


# --- Convention fixture ------------------------------------------------

def validate_convention_sample(sample: dict[str, Any]) -> None:
    """Validate one canonical sample record against every locked convention.

    Expected keys: ``account``, ``currency``, ``minor_units``, ``scale``,
    ``timestamp``, ``source_link``. Raises :class:`ConventionError` on the first
    violation.
    """
    required = {"account", "currency", "minor_units", "scale", "timestamp", "source_link"}
    missing = required - set(sample)
    if missing:
        raise ConventionError(f"convention sample is missing keys: {sorted(missing)}")
    validate_account_name(sample["account"])
    validate_currency(sample["currency"])
    validate_amount_minor_units(sample["minor_units"], sample["currency"], sample["scale"])
    validate_utc_timestamp(sample["timestamp"])
    validate_source_link(sample["source_link"])
