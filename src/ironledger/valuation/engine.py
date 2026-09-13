"""Multi-Asset Valuation Engine and rational integer arithmetic."""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime

from ironledger.valuation.formatting import (
    CURRENCY_PATTERN,
    validate_calendar_date,
)
from ironledger.valuation.models import (
    LEDGER_ID_PATTERN,
    MissingPriceDirectiveError,
    PriceDirective,
    StalePriceDirectiveError,
)


def convert_amount_rational(
    source_minor: int,
    source_scale: int,
    rate_numerator: int,
    rate_denominator: int,
    target_scale: int,
) -> int:
    """Convert currency amount using exact Banker's half-even integer rational arithmetic.

    Computes: source_minor * (rate_numerator / rate_denominator) * (10^target_scale / 10^source_scale)
    with zero float operations and exact round-half-to-even tie-breaking.
    """
    if type(source_minor) is not int or isinstance(source_minor, bool):
        raise TypeError("source_minor must be an integer (not bool or float)")
    if type(source_scale) is not int or isinstance(source_scale, bool) or not (0 <= source_scale <= 18):
        raise TypeError("source_scale must be an integer between 0 and 18")
    if type(rate_numerator) is not int or isinstance(rate_numerator, bool) or rate_numerator <= 0:
        raise TypeError("rate_numerator must be a positive integer")
    if type(rate_denominator) is not int or isinstance(rate_denominator, bool) or rate_denominator <= 0:
        raise TypeError("rate_denominator must be a positive integer")
    if type(target_scale) is not int or isinstance(target_scale, bool) or not (0 <= target_scale <= 18):
        raise TypeError("target_scale must be an integer between 0 and 18")

    scale_diff = target_scale - source_scale
    if scale_diff >= 0:
        num = abs(source_minor) * rate_numerator * (10 ** scale_diff)
        denom = rate_denominator
    else:
        num = abs(source_minor) * rate_numerator
        denom = rate_denominator * (10 ** (-scale_diff))

    quot, rem = divmod(num, denom)
    doubled_rem = rem * 2

    if doubled_rem > denom:
        quot += 1
    elif doubled_rem == denom:
        # Exact tie: round to nearest even integer
        if quot % 2 == 1:
            quot += 1

    return -quot if source_minor < 0 else quot


class ValuationEngine:
    """Manages historical price directives cache and rational multi-asset conversions."""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self._conn = conn

    def refresh_portfolio_cache(
        self, ledger_id: str = "default", conn: sqlite3.Connection | None = None,
        *, target_scale: int = 2,
    ) -> None:
        """Materialize active holdings using exact rational conversion."""
        c = self._get_connection(conn)
        currency_row = c.execute(
            "SELECT base_currency FROM ledgers WHERE ledger_id = ?", (ledger_id,)
        ).fetchone()
        if currency_row is None:
            raise ValueError(f"Unknown ledger: {ledger_id}")
        functional_currency = currency_row[0]
        rows = c.execute(
            """SELECT account, commodity, unit_scale, SUM(remaining_units_minor),
                      SUM(remaining_functional_cost_basis_minor)
               FROM open_lots
               WHERE ledger_id = ? AND remaining_units_minor > 0
               GROUP BY account, commodity, unit_scale""", (ledger_id,)
        ).fetchall()
        c.execute("DELETE FROM portfolio_holdings_cache WHERE ledger_id = ?", (ledger_id,))
        for account, commodity, unit_scale, units, basis in rows:
            if commodity == functional_currency:
                price_num, price_den = 1, 1
            else:
                price = self.get_price(commodity, functional_currency, "9999-12-31", ledger_id, conn=c)
                price_num, price_den = price.rate_numerator, price.rate_denominator
            market = convert_amount_rational(units, unit_scale, price_num, price_den, target_scale)
            c.execute(
                """INSERT INTO portfolio_holdings_cache
                   (ledger_id, account, commodity, total_units_minor, unit_scale,
                    functional_currency, total_cost_basis_minor, latest_price_numerator,
                    latest_price_denominator, market_value_minor, unrealized_gain_minor)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ledger_id, account, commodity, units, unit_scale, functional_currency,
                 basis, price_num, price_den, market, market - basis),
            )
        c.commit()

    def _get_connection(self, conn: sqlite3.Connection | None) -> sqlite3.Connection:
        active_conn = conn if conn is not None else self._conn
        if active_conn is None:
            raise ValueError("No database connection provided")
        return active_conn

    def add_price_directive(
        self,
        directive: PriceDirective,
        conn: sqlite3.Connection | None = None,
    ) -> PriceDirective:
        """Persist and cache a price directive in the database with normalized fraction."""
        c = self._get_connection(conn)

        # Normalize fraction with GCD
        common = math.gcd(directive.rate_numerator, directive.rate_denominator)
        norm_num = directive.rate_numerator // common
        norm_denom = directive.rate_denominator // common

        in_tx = c.in_transaction
        if not in_tx:
            c.execute("BEGIN IMMEDIATE")
        try:
            # Determine next ID for (ledger_id, id)
            cur = c.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM price_history WHERE ledger_id = ?",
                (directive.ledger_id,),
            )
            row = cur.fetchone()
            next_id = int(row[0]) if row and row[0] is not None else 1

            c.execute(
                """
                INSERT INTO price_history (
                    id, ledger_id, directive_date, base_currency, quote_currency,
                    rate_numerator, rate_denominator, precision_scale, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (ledger_id, directive_date, base_currency, quote_currency) DO UPDATE SET
                    rate_numerator = excluded.rate_numerator,
                    rate_denominator = excluded.rate_denominator,
                    precision_scale = excluded.precision_scale,
                    source = excluded.source
                """,
                (
                    next_id,
                    directive.ledger_id,
                    directive.directive_date,
                    directive.base_currency,
                    directive.quote_currency,
                    norm_num,
                    norm_denom,
                    directive.precision_scale,
                    directive.source,
                ),
            )
            if not in_tx:
                c.execute("COMMIT")
        except Exception:
            if not in_tx and c.in_transaction:
                c.execute("ROLLBACK")
            raise

        # Fetch the saved row
        cur = c.execute(
            """
            SELECT id, ledger_id, directive_date, base_currency, quote_currency,
                   rate_numerator, rate_denominator, precision_scale, source, created_at
            FROM price_history
            WHERE ledger_id = ? AND directive_date = ? AND base_currency = ? AND quote_currency = ?
            """,
            (
                directive.ledger_id,
                directive.directive_date,
                directive.base_currency,
                directive.quote_currency,
            ),
        )
        saved_row = cur.fetchone()
        return PriceDirective(
            id=saved_row[0],
            ledger_id=saved_row[1],
            directive_date=saved_row[2],
            base_currency=saved_row[3],
            quote_currency=saved_row[4],
            rate_numerator=saved_row[5],
            rate_denominator=saved_row[6],
            precision_scale=saved_row[7],
            source=saved_row[8],
            created_at=saved_row[9],
        )

    def get_price(
        self,
        base_currency: str,
        quote_currency: str,
        as_of_date: str,
        ledger_id: str = "default",
        max_staleness_days: int | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> PriceDirective:
        """Resolve the effective price directive for currency pair as of a given date."""
        valid_date = validate_calendar_date(as_of_date)
        if not isinstance(base_currency, str) or not CURRENCY_PATTERN.match(base_currency):
            raise ValueError(f"Invalid base_currency: {base_currency!r}")
        if not isinstance(quote_currency, str) or not CURRENCY_PATTERN.match(quote_currency):
            raise ValueError(f"Invalid quote_currency: {quote_currency!r}")
        if not isinstance(ledger_id, str) or not LEDGER_ID_PATTERN.match(ledger_id):
            raise ValueError(f"Invalid ledger_id: {ledger_id!r}")
        if max_staleness_days is not None and (
            type(max_staleness_days) is not int
            or isinstance(max_staleness_days, bool)
            or max_staleness_days < 0
        ):
            raise TypeError("max_staleness_days must be a non-negative integer or None")

        # Identity fast path
        if base_currency == quote_currency:
            return PriceDirective(
                directive_date=valid_date,
                base_currency=base_currency,
                quote_currency=quote_currency,
                rate_numerator=1,
                rate_denominator=1,
                precision_scale=4,
                source="MANUAL",
                ledger_id=ledger_id,
            )

        c = self._get_connection(conn)

        # 1. Direct lookup
        cur = c.execute(
            """
            SELECT id, ledger_id, directive_date, base_currency, quote_currency,
                   rate_numerator, rate_denominator, precision_scale, source, created_at
            FROM price_history
            WHERE ledger_id = ? AND base_currency = ? AND quote_currency = ? AND directive_date <= ?
            ORDER BY directive_date DESC, id DESC
            LIMIT 1
            """,
            (ledger_id, base_currency, quote_currency, valid_date),
        )
        row = cur.fetchone()

        if row is not None:
            directive = PriceDirective(
                id=row[0],
                ledger_id=row[1],
                directive_date=row[2],
                base_currency=row[3],
                quote_currency=row[4],
                rate_numerator=row[5],
                rate_denominator=row[6],
                precision_scale=row[7],
                source=row[8],
                created_at=row[9],
            )
        else:
            # 2. Inverse lookup fallback
            cur = c.execute(
                """
                SELECT id, ledger_id, directive_date, base_currency, quote_currency,
                       rate_numerator, rate_denominator, precision_scale, source, created_at
                FROM price_history
                WHERE ledger_id = ? AND base_currency = ? AND quote_currency = ? AND directive_date <= ?
                ORDER BY directive_date DESC, id DESC
                LIMIT 1
                """,
                (ledger_id, quote_currency, base_currency, valid_date),
            )
            inv_row = cur.fetchone()
            if inv_row is None:
                raise MissingPriceDirectiveError(
                    f"No price directive found for {base_currency}->{quote_currency} "
                    f"as of {valid_date} in ledger '{ledger_id}'"
                )
            directive = PriceDirective(
                id=inv_row[0],
                ledger_id=inv_row[1],
                directive_date=inv_row[2],
                base_currency=base_currency,
                quote_currency=quote_currency,
                rate_numerator=inv_row[6],  # Invert numerator & denominator
                rate_denominator=inv_row[5],
                precision_scale=inv_row[7],
                source=inv_row[8],
                created_at=inv_row[9],
            )

        # 3. Staleness check
        if max_staleness_days is not None:
            req_dt = datetime.strptime(valid_date, "%Y-%m-%d").date()
            dir_dt = datetime.strptime(directive.directive_date, "%Y-%m-%d").date()
            days_diff = (req_dt - dir_dt).days
            if days_diff > max_staleness_days:
                raise StalePriceDirectiveError(
                    f"Price directive for {base_currency}->{quote_currency} is {days_diff} days stale "
                    f"(max allowed: {max_staleness_days} days)"
                )

        return directive

    def convert(
        self,
        source_minor: int,
        source_scale: int,
        base_currency: str,
        quote_currency: str,
        as_of_date: str,
        target_scale: int,
        ledger_id: str = "default",
        max_staleness_days: int | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """Convert minor units from base_currency to quote_currency as of given date."""
        valid_date = validate_calendar_date(as_of_date)
        if not isinstance(base_currency, str) or not CURRENCY_PATTERN.match(base_currency):
            raise ValueError(f"Invalid base_currency: {base_currency!r}")
        if not isinstance(quote_currency, str) or not CURRENCY_PATTERN.match(quote_currency):
            raise ValueError(f"Invalid quote_currency: {quote_currency!r}")
        if not isinstance(ledger_id, str) or not LEDGER_ID_PATTERN.match(ledger_id):
            raise ValueError(f"Invalid ledger_id: {ledger_id!r}")
        if type(source_minor) is not int or isinstance(source_minor, bool):
            raise TypeError("source_minor must be an integer (not bool or float)")
        if type(source_scale) is not int or isinstance(source_scale, bool) or not (0 <= source_scale <= 18):
            raise TypeError("source_scale must be an integer between 0 and 18")
        if type(target_scale) is not int or isinstance(target_scale, bool) or not (0 <= target_scale <= 18):
            raise TypeError("target_scale must be an integer between 0 and 18")
        if max_staleness_days is not None and (
            type(max_staleness_days) is not int
            or isinstance(max_staleness_days, bool)
            or max_staleness_days < 0
        ):
            raise TypeError("max_staleness_days must be a non-negative integer or None")

        if base_currency == quote_currency:
            if source_scale == target_scale:
                return source_minor
            return convert_amount_rational(
                source_minor=source_minor,
                source_scale=source_scale,
                rate_numerator=1,
                rate_denominator=1,
                target_scale=target_scale,
            )

        directive = self.get_price(
            base_currency=base_currency,
            quote_currency=quote_currency,
            as_of_date=valid_date,
            ledger_id=ledger_id,
            max_staleness_days=max_staleness_days,
            conn=conn,
        )

        return convert_amount_rational(
            source_minor=source_minor,
            source_scale=source_scale,
            rate_numerator=directive.rate_numerator,
            rate_denominator=directive.rate_denominator,
            target_scale=target_scale,
        )
