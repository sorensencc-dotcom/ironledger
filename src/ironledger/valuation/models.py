"""Data models and exceptions for multi-asset valuation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

CURRENCY_PATTERN = re.compile(r"^[A-Z0-9_.-]{1,12}\Z")
LEDGER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")


class ValuationError(Exception):
    """Base exception for valuation subsystem errors."""


class MissingPriceDirectiveError(ValuationError):
    """Raised when no suitable price directive is found for a currency pair."""


class StalePriceDirectiveError(ValuationError):
    """Raised when the latest available price directive exceeds the staleness limit."""


@dataclass(frozen=True)
class PriceDirective:
    directive_date: str
    base_currency: str
    quote_currency: str
    rate_numerator: int
    rate_denominator: int
    precision_scale: int = 4
    source: Literal["MANUAL", "POLLED_FEED", "EXCHANGE_API"] = "MANUAL"
    ledger_id: str = "default"
    id: int | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.directive_date, str) or len(self.directive_date) != 10:
            raise ValueError(f"Invalid directive_date format: {self.directive_date!r}")
        try:
            datetime.strptime(self.directive_date, "%Y-%m-%d").date()
        except ValueError as e:
            raise ValueError(f"Invalid calendar date {self.directive_date!r}: {e}") from e

        if not isinstance(self.base_currency, str) or not CURRENCY_PATTERN.match(self.base_currency):
            raise ValueError(f"Invalid base_currency: {self.base_currency!r}")
        if not isinstance(self.quote_currency, str) or not CURRENCY_PATTERN.match(self.quote_currency):
            raise ValueError(f"Invalid quote_currency: {self.quote_currency!r}")

        if type(self.rate_numerator) is not int or isinstance(self.rate_numerator, bool) or self.rate_numerator <= 0:
            raise TypeError("rate_numerator must be a positive integer (not bool or float)")
        if type(self.rate_denominator) is not int or isinstance(self.rate_denominator, bool) or self.rate_denominator <= 0:
            raise TypeError("rate_denominator must be a positive integer (not bool or float)")
        if type(self.precision_scale) is not int or isinstance(self.precision_scale, bool) or not (0 <= self.precision_scale <= 18):
            raise TypeError("precision_scale must be an integer between 0 and 18")

        if self.source not in ("MANUAL", "POLLED_FEED", "EXCHANGE_API"):
            raise ValueError(f"Invalid source: {self.source!r}")
        if not isinstance(self.ledger_id, str) or not LEDGER_ID_PATTERN.match(self.ledger_id):
            raise ValueError(f"Invalid ledger_id: {self.ledger_id!r}")
        if self.id is not None and (type(self.id) is not int or isinstance(self.id, bool) or self.id < 0):
            raise TypeError("id must be a non-negative integer or None")
