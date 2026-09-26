"""Read-only Phase 14 tax and gains endpoints."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Annotated, Iterator, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ironledger.valuation.engine import ValuationEngine, convert_amount_rational
from ironledger.valuation.formatting import format_minor_units, validate_calendar_date
from ironledger.valuation.lots import InsufficientInventoryError, OpenLot, simulate_lot_disposal
from ironledger.valuation.models import MissingPriceDirectiveError, StalePriceDirectiveError, _decimal_fraction
from ironledger.web.schemas import (
    CapitalGainsSummaryResponse,
    DisposalPreviewRequest,
    DisposalPreviewResponse,
    OpenTaxLotsResponse,
    UnrealizedGainsResponse,
)

router = APIRouter(prefix="/api/tax", tags=["tax"])
Term = Literal["ALL", "SHORT_TERM", "LONG_TERM"]
OptionalFilter = Annotated[str | None, Query(min_length=1)]


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = request.app.state.get_db()
    try:
        yield conn
    finally:
        conn.close()


def _currency(conn: sqlite3.Connection, ledger_id: str) -> str:
    row = conn.execute("SELECT base_currency FROM ledgers WHERE ledger_id = ?", (ledger_id,)).fetchone()
    return str(row[0]) if row and row[0] else "USD"


@router.get("/capital-gains-summary", response_model=CapitalGainsSummaryResponse)
def capital_gains_summary(
    ledger_id: str = "default",
    tax_year: Annotated[int | None, Query(ge=1000, le=9999)] = None,
    term: Term = "ALL",
    account: OptionalFilter = None,
    commodity: OptionalFilter = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    clauses = ["ledger_id = ?"]
    params: list[object] = [ledger_id]
    if tax_year is not None:
        clauses.append("disposal_date LIKE ?")
        params.append(f"{tax_year}-%")
    if term != "ALL":
        clauses.append("term_classification = ?")
        params.append(term)
    if account is not None:
        clauses.append("account = ?")
        params.append(account)
    if commodity is not None:
        clauses.append("commodity = ?")
        params.append(commodity)
    row = conn.execute(
        f"""SELECT
            COALESCE(SUM(functional_realized_gain_minor), 0),
            COALESCE(SUM(functional_proceeds_minor), 0),
            COALESCE(SUM(functional_cost_basis_minor), 0),
            COALESCE(SUM(CASE WHEN term_classification = 'SHORT_TERM' THEN functional_realized_gain_minor ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN term_classification = 'SHORT_TERM' THEN functional_proceeds_minor ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN term_classification = 'SHORT_TERM' THEN functional_cost_basis_minor ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN term_classification = 'LONG_TERM' THEN functional_realized_gain_minor ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN term_classification = 'LONG_TERM' THEN functional_proceeds_minor ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN term_classification = 'LONG_TERM' THEN functional_cost_basis_minor ELSE 0 END), 0),
            COUNT(*) FROM lot_disposal_allocations WHERE {' AND '.join(clauses)}""",
        params,
    ).fetchone()
    values = [int(value) for value in row]
    def term_summary(offset: int) -> dict:
        gain, proceeds, basis = values[offset:offset + 3]
        return {
            "realized_gain_minor": gain, "realized_gain_display": format_minor_units(gain, 2),
            "proceeds_minor": proceeds, "proceeds_display": format_minor_units(proceeds, 2),
            "cost_basis_minor": basis, "cost_basis_display": format_minor_units(basis, 2),
        }
    return {
        "ledger_id": ledger_id, "functional_currency": _currency(conn, ledger_id),
        "tax_year": tax_year, "term_filter": term,
        "total_realized_gain_minor": values[0], "total_realized_gain_display": format_minor_units(values[0], 2),
        "total_proceeds_minor": values[1], "total_proceeds_display": format_minor_units(values[1], 2),
        "total_cost_basis_minor": values[2], "total_cost_basis_display": format_minor_units(values[2], 2),
        "short_term": term_summary(3), "long_term": term_summary(6), "disposal_count": values[9],
    }


@router.get("/open-lots", response_model=OpenTaxLotsResponse)
def open_tax_lots(
    ledger_id: str = "default",
    account: OptionalFilter = None,
    commodity: OptionalFilter = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    clauses = ["ledger_id = ?", "remaining_units_minor > 0"]
    params: list[object] = [ledger_id]
    for column, value in (("account", account), ("commodity", commodity)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    rows = conn.execute(
        f"""SELECT lot_key, account, commodity, acquisition_date, remaining_units_minor,
        unit_scale, functional_unit_cost_numerator, functional_unit_cost_denominator,
        functional_currency, remaining_functional_cost_basis_minor, lot_label
        FROM open_lots WHERE {' AND '.join(clauses)} ORDER BY acquisition_date, lot_key""",
        params,
    ).fetchall()
    engine = ValuationEngine(conn)
    today = date.today().isoformat()
    lots = []
    for row in rows:
        lot_key, acct, comm, acquired, units, scale, cost_num, cost_den, currency, basis, label = row
        price_num = price_den = market = gain = None
        try:
            price = engine.get_price(str(comm), str(currency), today, ledger_id=ledger_id, conn=conn)
            price_num, price_den = price.rate_numerator, price.rate_denominator
            market = convert_amount_rational(int(units), int(scale), price_num, price_den, 2)
            gain = market - int(basis)
        except (MissingPriceDirectiveError, StalePriceDirectiveError):
            pass
        lots.append({
            "lot_key": str(lot_key), "account": str(acct), "commodity": str(comm), "acquisition_date": str(acquired),
            "remaining_units_minor": int(units), "unit_scale": int(scale), "quantity_display": format_minor_units(int(units), int(scale)),
            "functional_currency": str(currency), "unit_cost_numerator": int(cost_num), "unit_cost_denominator": int(cost_den),
            "current_basis_minor": int(basis), "current_basis_display": format_minor_units(int(basis), 2),
            "market_price_numerator": price_num, "market_price_denominator": price_den,
            "market_value_minor": market, "market_value_display": format_minor_units(market, 2) if market is not None else None,
            "unrealized_gain_loss_minor": gain, "unrealized_gain_loss_display": format_minor_units(gain, 2) if gain is not None else None,
            "lot_label": str(label) if label else None,
        })
    return {"lots": lots, "count": len(lots)}


@router.get("/unrealized-gains", response_model=UnrealizedGainsResponse)
def unrealized_gains(
    ledger_id: str = "default",
    commodity: OptionalFilter = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    clauses = ["ledger_id = ?", "remaining_units_minor > 0"]
    params: list[object] = [ledger_id]
    if commodity is not None:
        clauses.append("commodity = ?")
        params.append(commodity)
    rows = conn.execute(
        f"""SELECT commodity, unit_scale, SUM(remaining_units_minor),
        SUM(remaining_functional_cost_basis_minor) FROM open_lots
        WHERE {' AND '.join(clauses)} GROUP BY commodity, unit_scale ORDER BY commodity""",
        params,
    ).fetchall()
    currency = _currency(conn, ledger_id)
    engine = ValuationEngine(conn)
    today = date.today().isoformat()
    positions = []
    total_basis = total_market = total_gain = 0
    for comm, scale, units, basis in rows:
        units, scale, basis = int(units), int(scale), int(basis)
        price_num, price_den, price_display = 1, 1, "1.0000"
        if str(comm) != currency:
            try:
                price = engine.get_price(str(comm), currency, today, ledger_id=ledger_id, conn=conn)
                price_num, price_den = price.rate_numerator, price.rate_denominator
                scaled = (price_num * 10000) // price_den
                price_display = f"{scaled // 10000}.{scaled % 10000:04d}"
            except (MissingPriceDirectiveError, StalePriceDirectiveError):
                price_num, price_den, price_display = 0, 1, "0.0000"
        market = convert_amount_rational(units, scale, price_num, price_den, 2) if price_num else 0
        gain = market - basis if price_num else 0
        total_basis += basis
        total_market += market
        total_gain += gain
        positions.append({
            "commodity": str(comm), "total_units_minor": units, "unit_scale": scale,
            "quantity_display": format_minor_units(units, scale), "functional_currency": currency,
            "cost_basis_minor": basis, "cost_basis_display": format_minor_units(basis, 2),
            "latest_price_numerator": price_num, "latest_price_denominator": price_den, "latest_price_display": price_display,
            "market_value_minor": market, "market_value_display": format_minor_units(market, 2),
            "unrealized_gain_minor": gain, "unrealized_gain_display": format_minor_units(gain, 2),
        })
    return {
        "ledger_id": ledger_id, "functional_currency": currency,
        "total_cost_basis_minor": total_basis, "total_cost_basis_display": format_minor_units(total_basis, 2),
        "total_market_value_minor": total_market, "total_market_value_display": format_minor_units(total_market, 2),
        "total_unrealized_gain_minor": total_gain, "total_unrealized_gain_display": format_minor_units(total_gain, 2),
        "positions": positions,
    }


@router.post("/preview-disposal", response_model=DisposalPreviewResponse)
def preview_disposal(payload: DisposalPreviewRequest, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    try:
        disposal_date = validate_calendar_date(payload.disposal_date or date.today().isoformat())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid disposal_date: {exc}") from exc
    rows = conn.execute(
        """SELECT lot_key, ledger_id, account, commodity, acquisition_date, remaining_units_minor,
        unit_scale, functional_unit_cost_numerator, functional_unit_cost_denominator,
        native_cost_currency, functional_cost_basis_minor, remaining_functional_cost_basis_minor
        FROM open_lots WHERE ledger_id = ? AND commodity = ? AND remaining_units_minor > 0
        AND (? IS NULL OR account = ?) ORDER BY acquisition_date, lot_key""",
        (payload.ledger_id, payload.commodity, payload.account, payload.account),
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No open lots found for {payload.commodity}")
    scale = int(rows[0][6])
    lots = [OpenLot(str(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), int(r[5]), int(r[6]), int(r[7]), int(r[8]), str(r[9]), int(r[10]), int(r[11])) for r in rows]
    try:
        quantity_num, quantity_den = _decimal_fraction(str(payload.quantity))
        proceeds_num, proceeds_den = _decimal_fraction(str(payload.proceeds_rate))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="quantity and proceeds_rate must be decimal numbers") from exc
    if quantity_num <= 0 or proceeds_num <= 0:
        raise HTTPException(status_code=422, detail="quantity and proceeds_rate must be positive")
    scaled_quantity = quantity_num * (10 ** scale)
    if scaled_quantity % quantity_den:
        raise HTTPException(status_code=422, detail=f"quantity exceeds supported scale of {scale} decimal places")
    units = scaled_quantity // quantity_den
    if units <= 0:
        raise HTTPException(status_code=422, detail="quantity must resolve to at least one minor unit")
    try:
        allocations, remaining = simulate_lot_disposal(
            lots, units_disposed_minor=units, unit_scale=scale,
            disposal_price_num=proceeds_num, disposal_price_denom=proceeds_den,
            strategy=payload.strategy, disposal_date=disposal_date,
            functional_currency=_currency(conn, payload.ledger_id),
        )
    except InsufficientInventoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    proceeds = sum(a.functional_proceeds_minor for a in allocations)
    basis = sum(a.functional_cost_basis_minor for a in allocations)
    gain = sum(a.functional_realized_gain_minor for a in allocations)
    short = sum(a.functional_realized_gain_minor for a in allocations if a.term_classification == "SHORT_TERM")
    long = sum(a.functional_realized_gain_minor for a in allocations if a.term_classification == "LONG_TERM")
    return {
        "simulation_status": "SUCCESS", "ledger_id": payload.ledger_id, "commodity": payload.commodity,
        "strategy": payload.strategy, "disposal_date": disposal_date,
        "units_disposed_minor": units, "units_disposed_display": format_minor_units(units, scale),
        "total_proceeds_minor": proceeds, "total_proceeds_display": format_minor_units(proceeds, 2),
        "total_cost_basis_minor": basis, "total_cost_basis_display": format_minor_units(basis, 2),
        "total_realized_gain_minor": gain, "total_realized_gain_display": format_minor_units(gain, 2),
        "short_term_gain_minor": short, "short_term_gain_display": format_minor_units(short, 2),
        "long_term_gain_minor": long, "long_term_gain_display": format_minor_units(long, 2),
        "allocations": [{
            "open_lot_key": a.open_lot_key, "acquisition_date": a.acquisition_date, "disposal_date": a.disposal_date,
            "units_disposed_minor": a.units_disposed_minor, "units_disposed_display": format_minor_units(a.units_disposed_minor, scale),
            "holding_period_days": a.holding_period_days, "term_classification": a.term_classification,
            "functional_proceeds_minor": a.functional_proceeds_minor, "functional_proceeds_display": format_minor_units(a.functional_proceeds_minor, 2),
            "functional_cost_basis_minor": a.functional_cost_basis_minor, "functional_cost_basis_display": format_minor_units(a.functional_cost_basis_minor, 2),
            "functional_realized_gain_minor": a.functional_realized_gain_minor, "functional_realized_gain_display": format_minor_units(a.functional_realized_gain_minor, 2),
        } for a in allocations],
        "remaining_lots": [{
            "lot_key": lot.lot_key, "account": lot.account, "commodity": lot.commodity, "acquisition_date": lot.acquisition_date,
            "remaining_units_minor": lot.remaining_units_minor, "remaining_units_display": format_minor_units(lot.remaining_units_minor, lot.unit_scale),
            "remaining_basis_minor": lot.remaining_basis_minor, "remaining_basis_display": format_minor_units(lot.remaining_basis_minor, 2),
        } for lot in remaining if lot.remaining_units_minor > 0],
    }
