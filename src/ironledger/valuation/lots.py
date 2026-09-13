"""Deterministic in-memory and database-backed lot matching primitives."""
from __future__ import annotations

import hashlib
from functools import cmp_to_key
from dataclasses import dataclass
from datetime import date


class InsufficientInventoryError(ValueError):
    pass


def _round_even(num: int, den: int) -> int:
    q, r = divmod(abs(num), den)
    if r * 2 > den or (r * 2 == den and q % 2):
        q += 1
    return -q if num < 0 else q


@dataclass
class OpenLot:
    lot_key: str
    ledger_id: str
    account: str
    commodity: str
    acquisition_date: str
    remaining_units_minor: int
    unit_scale: int
    cost_num: int
    cost_den: int
    cost_currency: str
    original_basis_minor: int
    remaining_basis_minor: int


@dataclass(frozen=True)
class LotDisposalAllocation:
    open_lot_key: str
    acquisition_date: str
    disposal_date: str
    units_disposed_minor: int
    holding_period_days: int
    term_classification: str
    functional_proceeds_minor: int
    functional_cost_basis_minor: int
    functional_realized_gain_minor: int


class LotProcessor:
    def __init__(self, conn=None, engine=None, *, functional_currency: str = "USD"):
        self.conn = conn
        self.engine = engine
        self.functional_currency = functional_currency
        self.lots: list[OpenLot] = []

    def process_acquisition(
        self, ledger_id, account, commodity, date, units_minor, unit_scale,
        cost_num, cost_denom, cost_currency, posting_id, tx_id
    ):
        if units_minor <= 0 or cost_denom <= 0:
            raise ValueError("acquisition units and denominator must be positive")
        basis = _round_even(units_minor * cost_num * 100, cost_denom * (10 ** unit_scale))
        key = hashlib.sha256(
            f"{ledger_id}:{account}:{commodity}:{date}:{cost_num}:{cost_denom}:{cost_currency}:{posting_id}".encode()
        ).hexdigest()
        lot = OpenLot(
            key, ledger_id, account, commodity, date, units_minor, unit_scale,
            cost_num, cost_denom, cost_currency, basis, basis
        )
        self.lots.append(lot)

        if self.conn is not None:
            self.conn.execute(
                """
                INSERT INTO open_lots (
                    lot_key, ledger_id, account, commodity, acquisition_date,
                    original_units_minor, remaining_units_minor, unit_scale,
                    native_cost_numerator, native_cost_denominator, native_cost_currency,
                    functional_currency, functional_unit_cost_numerator, functional_unit_cost_denominator,
                    functional_cost_basis_minor, remaining_functional_cost_basis_minor,
                    created_posting_id, created_entry_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key, ledger_id, account, commodity, date,
                    units_minor, units_minor, unit_scale,
                    cost_num, cost_denom, cost_currency,
                    self.functional_currency, cost_num, cost_denom,
                    basis, basis, str(posting_id), str(tx_id)
                )
            )
            self.conn.commit()

    def process_disposal(
        self, ledger_id, account, commodity, date, units_disposed_minor, unit_scale,
        disposal_price_num, disposal_price_denom, disposal_currency, strategy,
        closing_posting_id, closing_tx_id
    ):
        candidates = [
            x for x in self.lots
            if x.ledger_id == ledger_id and x.account == account and x.commodity == commodity and x.remaining_units_minor
        ]
        if strategy == "LIFO":
            candidates.sort(key=lambda x: (x.acquisition_date, x.lot_key), reverse=True)
        elif strategy == "HIFO":
            def compare(a, b):
                left = a.cost_num * b.cost_den
                right = b.cost_num * a.cost_den
                if left != right:
                    return -1 if left > right else 1
                if (a.acquisition_date, a.lot_key) < (b.acquisition_date, b.lot_key):
                    return -1
                if (a.acquisition_date, a.lot_key) > (b.acquisition_date, b.lot_key):
                    return 1
                return 0
            candidates.sort(key=cmp_to_key(compare))
        else:
            candidates.sort(key=lambda x: (x.acquisition_date, x.lot_key))

        if sum(x.remaining_units_minor for x in candidates) < units_disposed_minor:
            raise InsufficientInventoryError("disposition exceeds available inventory")

        remaining = units_disposed_minor
        result = []
        ordinal = 0
        for lot in candidates:
            take = min(remaining, lot.remaining_units_minor)
            basis = lot.remaining_basis_minor if take == lot.remaining_units_minor else _round_even(
                take * lot.cost_num * 100, lot.cost_den * (10 ** lot.unit_scale)
            )
            proceeds = _round_even(take * disposal_price_num * 100, disposal_price_denom * (10 ** unit_scale))
            if take == lot.remaining_units_minor:
                basis = lot.remaining_basis_minor

            lot.remaining_units_minor -= take
            lot.remaining_basis_minor -= basis
            days = (date_from_string(date) - date_from_string(lot.acquisition_date)).days
            gain = proceeds - basis
            alloc = LotDisposalAllocation(
                lot.lot_key, lot.acquisition_date, date, take, days,
                "LONG_TERM" if days > 365 else "SHORT_TERM", proceeds, basis, gain
            )
            result.append(alloc)

            if self.conn is not None:
                self.conn.execute(
                    """
                    UPDATE open_lots
                    SET remaining_units_minor = ?,
                        remaining_functional_cost_basis_minor = ?
                    WHERE lot_key = ?
                    """,
                    (lot.remaining_units_minor, lot.remaining_basis_minor, lot.lot_key)
                )
                alloc_key = hashlib.sha256(
                    f"{ledger_id}:{lot.lot_key}:{closing_posting_id}:{take}".encode()
                ).hexdigest()
                self.conn.execute(
                    """
                    INSERT INTO lot_disposal_allocations (
                        allocation_key, ledger_id, account, commodity,
                        disposal_date, acquisition_date, units_disposed_minor, unit_scale,
                        holding_period_days, term_classification, native_proceeds_minor,
                        native_proceeds_currency, native_cost_basis_minor, native_cost_currency,
                        native_realized_gain_minor, functional_proceeds_minor, functional_cost_basis_minor,
                        functional_realized_gain_minor, functional_currency, strategy_applied,
                        open_lot_key, closing_posting_id, closing_entry_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        alloc_key, ledger_id, account, commodity,
                        date, lot.acquisition_date, take, unit_scale,
                        days, alloc.term_classification, proceeds,
                        disposal_currency, basis, lot.cost_currency,
                        gain if disposal_currency == lot.cost_currency else None,
                        proceeds, basis, gain,
                        self.functional_currency, strategy, lot.lot_key,
                        str(closing_posting_id), str(closing_tx_id)
                    )
                )
            remaining -= take
            ordinal += 1
            if not remaining:
                break

        if self.conn is not None:
            self.conn.commit()

        return result


def date_from_string(value: str) -> date:
    return date.fromisoformat(value)