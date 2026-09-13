from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

TICKER_PATTERN = re.compile(r"^[A-Z0-9._-]{1,24}$")
CURRENCY_PATTERN = re.compile(r"^[A-Z]{3,8}$")
MAX_SQLITE_INT = 9_223_372_036_854_775_807


@dataclass(frozen=True)
class PriceDirectiveRecord:
    directive_date: str
    base_currency: str
    quote_currency: str
    price_numerator: int
    price_denominator: int
    source_provider: str
    raw_quote_str: str

    def __post_init__(self) -> None:
        if not TICKER_PATTERN.fullmatch(self.base_currency):
            raise ValueError(f"Invalid base commodity: {self.base_currency!r}")
        if not CURRENCY_PATTERN.fullmatch(self.quote_currency):
            raise ValueError(f"Invalid quote currency: {self.quote_currency!r}")
        if type(self.price_numerator) is not int or self.price_numerator <= 0:
            raise ValueError("Price numerator must be a positive integer")
        if type(self.price_denominator) is not int or self.price_denominator <= 0:
            raise ValueError("Price denominator must be a positive integer")
        if self.price_numerator > MAX_SQLITE_INT or self.price_denominator > MAX_SQLITE_INT:
            raise OverflowError("Price rational exceeds 64-bit integer range")

    @classmethod
    def from_decimal_str(cls, directive_date, base_currency, quote_currency, raw_price, source_provider):
        if not isinstance(raw_price, str):
            raise TypeError("raw_price must be a string")
        cleaned = raw_price.strip().replace(",", "")
        if "e" in cleaned.lower():
            raise ValueError("Scientific notation is forbidden in price quotes")
        try:
            dec = Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"Malformed price string: {raw_price!r}") from exc
        if not dec.is_finite() or dec <= 0:
            raise ValueError(f"Price quote must be positive and finite: {raw_price!r}")
        _sign, digits, exponent = dec.as_tuple()
        if exponent > 0 or exponent < -18:
            raise ValueError("Decimal exponent out of allowed range [-18, 0]")
        numerator = int("".join(str(digit) for digit in digits))
        denominator = 10 ** (-exponent)
        common = math.gcd(numerator, denominator)
        return cls(directive_date, base_currency.upper(), quote_currency.upper(), numerator // common, denominator // common, source_provider, cleaned)

    def reciprocal(self, source_provider="reciprocal"):
        return PriceDirectiveRecord(self.directive_date, self.quote_currency, self.base_currency, self.price_denominator, self.price_numerator, source_provider, f"{self.price_denominator}/{self.price_numerator}")

    def to_beancount_directive(self):
        scaled_num = self.price_numerator * 10000
        quot, rem = divmod(scaled_num, self.price_denominator)
        double_rem = rem * 2
        if double_rem > self.price_denominator or (double_rem == self.price_denominator and (quot % 2 != 0)):
            quot += 1
        int_part, frac_part = divmod(quot, 10000)
        formatted_price = f"{int_part}.{frac_part:04d}"
        return f"{self.directive_date} price {self.base_currency:<10} {formatted_price} {self.quote_currency}"


