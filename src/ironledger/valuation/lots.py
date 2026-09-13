"""Deterministic in-memory lot matching primitives."""
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
        self.functional_currency = functional_currency
        self.lots: list[OpenLot] = []

    def process_acquisition(self, ledger_id, account, commodity, date, units_minor, unit_scale,
                            cost_num, cost_denom, cost_currency, posting_id, tx_id):
        if units_minor <= 0 or cost_denom <= 0:
            raise ValueError("acquisition units and denominator must be positive")
        basis = _round_even(units_minor * cost_num * 100, cost_denom * (10 ** unit_scale))
        key = hashlib.sha256(f"{ledger_id}:{account}:{commodity}:{date}:{cost_num}:{cost_denom}:{cost_currency}:{posting_id}".encode()).hexdigest()
        self.lots.append(OpenLot(key, ledger_id, account, commodity, date, units_minor, unit_scale,
                                 cost_num, cost_denom, cost_currency, basis, basis))

    def process_disposal(self, ledger_id, account, commodity, date, units_disposed_minor, unit_scale,
                         disposal_price_num, disposal_price_denom, disposal_currency, strategy,
                         closing_posting_id, closing_tx_id):
        candidates = [x for x in self.lots if x.ledger_id == ledger_id and x.account == account and x.commodity == commodity and x.remaining_units_minor]
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
        for lot in candidates:
            take = min(remaining, lot.remaining_units_minor)
            basis = lot.remaining_basis_minor if take == lot.remaining_units_minor else _round_even(take * lot.cost_num * 100, lot.cost_den * (10 ** lot.unit_scale))
            proceeds = _round_even(take * disposal_price_num * 100, disposal_price_denom * (10 ** unit_scale))
            if take == lot.remaining_units_minor:
                basis = lot.remaining_basis_minor
            lot.remaining_units_minor -= take
            lot.remaining_basis_minor -= basis
            days = (date_from_string(date) - date_from_string(lot.acquisition_date)).days
            gain = proceeds - basis
            result.append(LotDisposalAllocation(lot.lot_key, lot.acquisition_date, date, take, days, "LONG_TERM" if days > 365 else "SHORT_TERM", proceeds, basis, gain))
            remaining -= take
            if not remaining:
                break
        return result


def date_from_string(value: str) -> date:
    return date.fromisoformat(value)
