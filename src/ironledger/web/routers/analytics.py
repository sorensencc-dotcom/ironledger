"""Analytics and portfolio reporting endpoints for IronLedger."""

from __future__ import annotations

import sqlite3
import csv
import io
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.get_db()


def _require_ledger(conn: sqlite3.Connection, ledger_id: str) -> str:
    row = conn.execute("SELECT base_currency FROM ledgers WHERE ledger_id = ?", (ledger_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Ledger not found")
    return str(row[0])


def _safe_csv_text(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


@router.get("/gains")
def get_capital_gains(
    ledger_id: str = "default", year: str | None = None, term: str = "ALL",
    commodity: str | None = None, account: str | None = None,
    limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    currency = _require_ledger(conn, ledger_id)
    if term not in {"ALL", "SHORT_TERM", "LONG_TERM"}:
        raise HTTPException(status_code=400, detail="Invalid term")
    clauses, params = ["ledger_id = ?"], [ledger_id]
    if year is not None:
        if not (len(year) == 4 and year.isdigit()):
            raise HTTPException(status_code=400, detail="Invalid year")
        clauses.append("disposal_date LIKE ?"); params.append(f"{year}-%")
    if term != "ALL": clauses.append("term_classification = ?"); params.append(term)
    if commodity is not None: clauses.append("commodity = ?"); params.append(commodity)
    if account is not None: clauses.append("account = ?"); params.append(account)
    where = " AND ".join(clauses)
    summary = conn.execute(f"SELECT COALESCE(SUM(functional_realized_gain_minor),0), COALESCE(SUM(functional_proceeds_minor),0), COALESCE(SUM(functional_cost_basis_minor),0) FROM lot_disposal_allocations WHERE {where}", params).fetchone()
    rows = conn.execute(f"SELECT id, account, commodity, disposal_date, acquisition_date, units_disposed_minor, unit_scale, holding_period_days, term_classification, functional_proceeds_minor, functional_cost_basis_minor, functional_realized_gain_minor, strategy_applied FROM lot_disposal_allocations WHERE {where} ORDER BY disposal_date, id LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
    keys = ["id","account","commodity","disposal_date","acquisition_date","units_disposed_minor","unit_scale","holding_period_days","term_classification","functional_proceeds_minor","functional_cost_basis_minor","functional_realized_gain_minor","strategy_applied"]
    return {"ledger_id": ledger_id, "functional_currency": currency, "summary": {"total_realized_gain_minor": summary[0], "total_proceeds_minor": summary[1], "total_cost_basis_minor": summary[2]}, "allocations": [dict(zip(keys, row)) for row in rows]}


@router.get("/lots")
def get_open_lots(ledger_id: str = "default", account: str | None = None, commodity: str | None = None, conn: sqlite3.Connection = Depends(get_db)) -> list[dict[str, Any]]:
    _require_ledger(conn, ledger_id)
    clauses, params = ["ledger_id = ? AND remaining_units_minor > 0"], [ledger_id]
    if account is not None: clauses.append("account = ?"); params.append(account)
    if commodity is not None: clauses.append("commodity = ?"); params.append(commodity)
    rows = conn.execute(f"SELECT lot_key, account, commodity, acquisition_date, remaining_units_minor, unit_scale, functional_cost_basis_minor, remaining_functional_cost_basis_minor, functional_currency, lot_label FROM open_lots WHERE {' AND '.join(clauses)} ORDER BY acquisition_date, lot_key", params).fetchall()
    keys = ["lot_key","account","commodity","acquisition_date","remaining_units_minor","unit_scale","functional_cost_basis_minor","remaining_functional_cost_basis_minor","functional_currency","lot_label"]
    return [dict(zip(keys, row)) for row in rows]


@router.get("/gains/export")
def export_capital_gains(ledger_id: str = "default", conn: sqlite3.Connection = Depends(get_db)) -> Any:
    _require_ledger(conn, ledger_id)
    rows = conn.execute("SELECT commodity, acquisition_date, disposal_date, functional_proceeds_minor, functional_cost_basis_minor, functional_realized_gain_minor, functional_currency, holding_period_days, term_classification FROM lot_disposal_allocations WHERE ledger_id = ? ORDER BY disposal_date, id LIMIT 100000", (ledger_id,)).fetchall()
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(["Description","Date_Acquired","Date_Sold","Proceeds","Cost_Basis","Gain_Loss","Functional_Currency","Holding_Period_Days","Term_Classification"])
    writer.writerows(tuple(_safe_csv_text(v) for v in row) for row in rows)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=capital-gains.csv"})


@router.get("/sankey")
def get_sankey_data(
    period: str = Query(..., pattern=r"^\d{4}-\d{2}$", description="Billing period formatted as YYYY-MM"),
    conn: sqlite3.Connection = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Retrieve categorized directed cash flow links for Sankey visualization."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT source_node, target_node, amount_minor_units 
            FROM v_sankey_cash_flows 
            WHERE period_month = ?
            ORDER BY amount_minor_units DESC
            """,
            (period,),
        )
        return [
            {
                "source_node": str(r[0]),
                "target_node": str(r[1]),
                "amount_minor_units": int(r[2]),
            }
            for r in cursor.fetchall()
        ]
    except sqlite3.OperationalError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query v_sankey_cash_flows view: {exc}",
        )
    finally:
        conn.close()


@router.get("/portfolio")
def get_portfolio_data(
    conn: sqlite3.Connection = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Retrieve consolidated multi-asset holdings, rational valuations, and unrealized P&L."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT commodity, total_units, total_cost_basis_minor_units, 
                   base_currency, market_value_minor_units, unrealized_gain_minor_units 
            FROM v_portfolio_holdings
            ORDER BY market_value_minor_units DESC
            """
        )
        return [
            {
                "commodity": str(r[0]),
                "total_units": int(r[1]) if r[1] is not None else 0,
                "total_cost_basis_minor_units": int(r[2]) if r[2] is not None else 0,
                "base_currency": str(r[3]),
                "market_value_minor_units": int(r[4]) if r[4] is not None else 0,
                "unrealized_gain_minor_units": int(r[5]) if r[5] is not None else 0,
            }
            for r in cursor.fetchall()
        ]
    except sqlite3.OperationalError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query v_portfolio_holdings view: {exc}",
        )
    finally:
        conn.close()


@router.get("/watchlist")
def get_watchlist(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve configured watchlist symbols, latest exchange rates, and resolution audit log."""
    import json
    from pathlib import Path
    config_dir = Path(getattr(request.app.state, "config_dir", "config"))
    config_path = config_dir.joinpath("prices.json")
    
    watchlist_items: list[dict[str, str]] = []
    default_quote = "USD"
    manual_quotes: dict[str, str] = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                default_quote = str(data.get("quote_currency", "USD"))
                manual_quotes = data.get("manual_quotes", {})
                for item in data.get("watchlist", []):
                    if isinstance(item, str):
                        watchlist_items.append({"symbol": item, "quote_currency": default_quote})
                    elif isinstance(item, dict) and "symbol" in item:
                        watchlist_items.append({"symbol": item["symbol"], "quote_currency": item.get("quote_currency", default_quote)})
        except Exception:
            pass

    try:
        cursor = conn.cursor()
        # Query latest price_history per commodity
        cursor.execute(
            """
            SELECT base_currency, quote_currency, rate_numerator, rate_denominator, directive_date, source, created_at
            FROM price_history
            WHERE id IN (
                SELECT MAX(id) FROM price_history GROUP BY base_currency, quote_currency
            )
            """
        )
        history_map = {
            (r[0], r[1]): {
                "rate_numerator": r[2],
                "rate_denominator": r[3],
                "directive_date": r[4],
                "source": r[5],
                "created_at": r[6],
            }
            for r in cursor.fetchall()
        }

        # Query latest audit log entries
        cursor.execute(
            """
            SELECT symbol, quote_currency, provider_id, status, rate_numerator, rate_denominator, latency_ms, error_message, created_at
            FROM price_feed_audit
            ORDER BY audit_id DESC
            LIMIT 25
            """
        )
        recent_audit = [
            {
                "symbol": r[0],
                "quote_currency": r[1],
                "provider_id": r[2],
                "status": r[3],
                "rate_numerator": r[4],
                "rate_denominator": r[5],
                "latency_ms": r[6],
                "error_message": r[7],
                "created_at": r[8],
            }
            for r in cursor.fetchall()
        ]

        items_out = []
        for wl in watchlist_items:
            sym = wl["symbol"]
            quote = wl["quote_currency"]
            hist = history_map.get((sym, quote))
            audit_matches = [a for a in recent_audit if a["symbol"] == sym and a["quote_currency"] == quote]
            latest_audit = audit_matches[0] if audit_matches else None
            
            num = hist["rate_numerator"] if hist else (latest_audit["rate_numerator"] if latest_audit else None)
            den = hist["rate_denominator"] if hist else (latest_audit["rate_denominator"] if latest_audit else None)
            price_str = None
            if num is not None and den is not None and den > 0:
                q, _ = divmod(num * 10000, den)
                price_str = f"{q // 10000}.{q % 10000:04d}"

            items_out.append({
                "symbol": sym,
                "quote_currency": quote,
                "rate_numerator": num,
                "rate_denominator": den,
                "price_display": price_str or manual_quotes.get(f"{sym}/{quote}"),
                "directive_date": hist["directive_date"] if hist else None,
                "last_provider": latest_audit["provider_id"] if latest_audit else (hist["source"] if hist else "none"),
                "last_status": latest_audit["status"] if latest_audit else "UNRESOLVED",
                "last_latency_ms": latest_audit["latency_ms"] if latest_audit else 0,
                "updated_at": hist["created_at"] if hist else (latest_audit["created_at"] if latest_audit else None),
            })

        return {
            "quote_currency": default_quote,
            "items": items_out,
            "recent_audit": recent_audit,
        }
    finally:
        conn.close()


@router.post("/prices/sync")
def trigger_price_sync(
    request: Request,
    payload: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Execute on-demand price feed synchronization across configured watchlist."""
    import json
    from pathlib import Path
    from ironledger.prices.scraper_daemon import PriceScraperDaemon
    from ironledger.prices.router import PriceCascadeRouter
    from ironledger.prices.providers.manual import ManualProvider

    db_path = Path(getattr(request.app.state, "db_path", "ironledger.db"))
    config_dir = Path(getattr(request.app.state, "config_dir", "config"))
    config_path = config_dir.joinpath("prices.json")
    ledger_dir = db_path.parent.joinpath("ledger")
    prices_beancount = ledger_dir.joinpath("prices.beancount")

    manual_quotes: dict[str, str] = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg_data = json.load(f)
                manual_quotes = cfg_data.get("manual_quotes", {})
        except Exception:
            pass

    router = PriceCascadeRouter({"DEFAULT": [ManualProvider(static_quotes=manual_quotes)]})
    daemon = PriceScraperDaemon(
        db_path=db_path,
        prices_ledger_path=prices_beancount,
        router=router,
        ledger_id="default",
    )

    symbols = None
    if payload and "symbols" in payload:
        quote = payload.get("quote_currency", "USD")
        symbols = [(str(s), quote) for s in payload["symbols"]]

    res = daemon.sync_watchlist(symbols=symbols, config_path=config_path if not symbols else None)
    return res


@router.post("/watchlist/add")
def add_watchlist_symbol(
    request: Request,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Add a new target symbol to config/prices.json and sync quote."""
    import json
    from pathlib import Path
    symbol = str(payload.get("symbol", "")).strip().upper()
    quote = str(payload.get("quote_currency", "USD")).strip().upper()
    manual_quote = payload.get("manual_quote")

    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol cannot be empty")

    config_dir = Path(getattr(request.app.state, "config_dir", "config"))
    config_path = config_dir.joinpath("prices.json")

    data: dict[str, Any] = {"quote_currency": "USD", "watchlist": []}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    watchlist = data.get("watchlist", [])
    exists = any(
        (isinstance(w, str) and w == symbol) or (isinstance(w, dict) and w.get("symbol") == symbol)
        for w in watchlist
    )
    if not exists:
        watchlist.append({"symbol": symbol, "quote_currency": quote})
        data["watchlist"] = watchlist

    if manual_quote:
        if "manual_quotes" not in data:
            data["manual_quotes"] = {}
        data["manual_quotes"][f"{symbol}/{quote}"] = str(manual_quote)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return {"status": "success", "symbol": symbol, "quote_currency": quote}


@router.delete("/watchlist/{symbol}")
def remove_watchlist_symbol(
    symbol: str,
    request: Request,
    quote_currency: str = "USD",
) -> Dict[str, Any]:
    """Remove a symbol from the configured watchlist in config/prices.json."""
    import json
    from pathlib import Path
    sym = symbol.strip().upper()
    quote = quote_currency.strip().upper()

    config_dir = Path(getattr(request.app.state, "config_dir", "config"))
    config_path = config_dir.joinpath("prices.json")

    if not config_path.exists():
        raise HTTPException(status_code=404, detail="prices.json configuration not found")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read prices.json: {exc}")

    watchlist = data.get("watchlist", [])
    new_watchlist = [
        w for w in watchlist
        if not (
            (isinstance(w, str) and w.upper() == sym) or
            (isinstance(w, dict) and w.get("symbol", "").upper() == sym and w.get("quote_currency", "USD").upper() == quote)
        )
    ]
    data["watchlist"] = new_watchlist

    # Clean up manual quotes if present
    if "manual_quotes" in data and f"{sym}/{quote}" in data["manual_quotes"]:
        del data["manual_quotes"][f"{sym}/{quote}"]

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return {"status": "success", "removed_symbol": sym, "quote_currency": quote}
