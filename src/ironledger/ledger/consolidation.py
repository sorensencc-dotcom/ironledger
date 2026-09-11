"""Consolidated balance sheet reporting and cross-tenant valuation."""

from __future__ import annotations

import sqlite3

from ironledger.ledger.models import (
    CURRENCY_PATTERN,
    LEDGER_ID_PATTERN,
    ConsolidatedBalanceSheet,
    EntityBalance,
)
from ironledger.ledger.topology import LedgerRegistry
from ironledger.valuation.engine import ValuationEngine, convert_amount_rational
from ironledger.valuation.formatting import validate_calendar_date
from ironledger.valuation.models import MissingPriceDirectiveError


class ConsolidationEngine:
    """Aggregates multi-tenant entity balances into a consolidated balance sheet."""

    def __init__(self, registry: LedgerRegistry) -> None:
        self.registry = registry

    def seed_balance(
        self,
        ledger_id: str,
        account: str,
        amount_minor: int,
        currency: str,
        scale: int = 2,
    ) -> None:
        """Record or update an entity balance in ledger_balances."""
        if not isinstance(ledger_id, str) or not LEDGER_ID_PATTERN.match(ledger_id):
            raise ValueError(f"Invalid ledger_id: {ledger_id!r}")
        if not isinstance(account, str) or not account:
            raise ValueError("account must be a non-empty string")
        if type(amount_minor) is not int or isinstance(amount_minor, bool):
            raise TypeError("amount_minor must be an integer")
        if not isinstance(currency, str) or not CURRENCY_PATTERN.match(currency):
            raise ValueError(f"Invalid currency: {currency!r}")
        if type(scale) is not int or isinstance(scale, bool) or not (0 <= scale <= 18):
            raise TypeError("scale must be an integer between 0 and 18")

        in_tx = self.registry.conn.in_transaction
        if not in_tx:
            self.registry.conn.execute("BEGIN IMMEDIATE")
        try:
            self.registry.conn.execute(
                """
                INSERT INTO ledger_balances (ledger_id, account, amount_minor, currency, scale, updated_at)
                VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%f', 'now'))
                ON CONFLICT(ledger_id, account, currency) DO UPDATE SET
                    amount_minor = excluded.amount_minor,
                    scale = excluded.scale,
                    updated_at = excluded.updated_at
                """,
                (ledger_id, account, amount_minor, currency, scale),
            )
            if not in_tx:
                self.registry.conn.execute("COMMIT")
        except Exception:
            if not in_tx and self.registry.conn.in_transaction:
                self.registry.conn.execute("ROLLBACK")
            raise

    def consolidated_balance_sheet(
        self,
        base_currency: str = "USD",
        as_of_date: str = "2026-09-10",
    ) -> ConsolidatedBalanceSheet:
        """Generate consolidated balance sheet across all active ledgers converted to base_currency."""
        valid_date = validate_calendar_date(as_of_date)
        if not isinstance(base_currency, str) or not CURRENCY_PATTERN.match(base_currency):
            raise ValueError(f"Invalid base_currency: {base_currency!r}")

        ledgers = self.registry.list_ledgers(include_inactive=False)
        val_engine = ValuationEngine(self.registry.conn)

        entity_balances: list[EntityBalance] = []
        total_minor = 0

        for ledger in ledgers:
            cur = self.registry.conn.execute(
                """
                SELECT account, amount_minor, currency, scale
                FROM ledger_balances
                WHERE ledger_id = ?
                ORDER BY account ASC, currency ASC
                """,
                (ledger.ledger_id,),
            )
            rows = cur.fetchall()
            for r in rows:
                account = str(r[0])
                amount_minor = int(r[1])
                currency = str(r[2])
                scale = int(r[3])

                if currency == base_currency:
                    converted_minor = convert_amount_rational(
                        source_minor=amount_minor,
                        source_scale=scale,
                        rate_numerator=1,
                        rate_denominator=1,
                        target_scale=2,
                    )
                else:
                    try:
                        converted_minor = val_engine.convert(
                            source_minor=amount_minor,
                            source_scale=scale,
                            base_currency=currency,
                            quote_currency=base_currency,
                            as_of_date=valid_date,
                            target_scale=2,
                            ledger_id=ledger.ledger_id,
                        )
                    except MissingPriceDirectiveError:
                        # Fall back to global/default price directive cache
                        converted_minor = val_engine.convert(
                            source_minor=amount_minor,
                            source_scale=scale,
                            base_currency=currency,
                            quote_currency=base_currency,
                            as_of_date=valid_date,
                            target_scale=2,
                            ledger_id="default",
                        )

                eb = EntityBalance(
                    ledger_id=ledger.ledger_id,
                    name=ledger.name,
                    account=account,
                    amount_minor=amount_minor,
                    currency=currency,
                    scale=scale,
                    converted_minor=converted_minor,
                    target_currency=base_currency,
                )
                entity_balances.append(eb)
                total_minor += converted_minor

        return ConsolidatedBalanceSheet(
            base_currency=base_currency,
            as_of_date=valid_date,
            total_minor=total_minor,
            scale=2,
            entities=ledgers,
            balances=entity_balances,
        )
