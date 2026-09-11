"""Pure integer string formatting and calendar validation for multi-asset valuation."""

from __future__ import annotations

import re
from datetime import datetime

CURRENCY_PATTERN = re.compile(r"^[A-Z0-9_.-]{1,12}$")


def validate_calendar_date(date_str: str) -> str:
    """Validate calendar date string format YYYY-MM-DD and verify valid calendar date."""
    if not isinstance(date_str, str) or len(date_str) != 10:
        raise ValueError(f"Invalid date string format: {date_str!r}")
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"Invalid calendar date {date_str!r}: {e}") from e
    return parsed.strftime("%Y-%m-%d")


def format_minor_units(minor_units: int, scale: int) -> str:
    """Format minor units to decimal string using pure integer arithmetic (zero float)."""
    if type(minor_units) is not int or isinstance(minor_units, bool):
        raise TypeError("minor_units must be an integer (not bool or float)")
    if type(scale) is not int or isinstance(scale, bool) or not (0 <= scale <= 18):
        raise TypeError("scale must be an integer between 0 and 18")
    sign = "-" if minor_units < 0 else ""
    abs_units = abs(minor_units)
    if scale == 0:
        return f"{sign}{abs_units}"
    multiplier = 10 ** scale
    integer_part, fraction_part = divmod(abs_units, multiplier)
    return f"{sign}{integer_part}.{fraction_part:0{scale}d}"


def format_beancount_price_directive(
    directive_date: str,
    base_currency: str,
    quote_currency: str,
    rate_numerator: int,
    rate_denominator: int,
    precision_scale: int = 4,
) -> str:
    """Format Beancount price directive using pure integer arithmetic and Banker's rounding."""
    valid_date = validate_calendar_date(directive_date)
    if not isinstance(base_currency, str) or not CURRENCY_PATTERN.match(base_currency):
        raise ValueError(f"Invalid base_currency: {base_currency}")
    if not isinstance(quote_currency, str) or not CURRENCY_PATTERN.match(quote_currency):
        raise ValueError(f"Invalid quote_currency: {quote_currency}")
    if type(rate_numerator) is not int or isinstance(rate_numerator, bool) or rate_numerator <= 0:
        raise TypeError("rate_numerator must be a positive integer")
    if type(rate_denominator) is not int or isinstance(rate_denominator, bool) or rate_denominator <= 0:
        raise TypeError("rate_denominator must be a positive integer")
    if type(precision_scale) is not int or isinstance(precision_scale, bool) or not (0 <= precision_scale <= 18):
        raise TypeError("precision_scale must be an integer between 0 and 18")

    # Handle precision_scale == 0 with Banker's rounding
    if precision_scale == 0:
        quot, rem = divmod(rate_numerator, rate_denominator)
        doubled_rem = rem * 2
        if doubled_rem > rate_denominator:
            quot += 1
        elif doubled_rem == rate_denominator:
            if quot % 2 == 1:
                quot += 1
        return f"{valid_date} price {base_currency} {quot} {quote_currency}"

    # Pure integer division and Banker's (half-even) tie-breaking for precision_scale > 0
    integer_part, rem = divmod(rate_numerator, rate_denominator)
    multiplier = 10 ** precision_scale
    quot, subrem = divmod(rem * multiplier, rate_denominator)
    doubled_subrem = subrem * 2

    if doubled_subrem > rate_denominator:
        quot += 1
    elif doubled_subrem == rate_denominator:
        # Exact tie: round to nearest even integer
        if quot % 2 == 1:
            quot += 1

    if quot >= multiplier:
        integer_part += 1
        quot -= multiplier

    formatted_rate = f"{integer_part}.{quot:0{precision_scale}d}"
    return f"{valid_date} price {base_currency} {formatted_rate} {quote_currency}"
