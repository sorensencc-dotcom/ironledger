from __future__ import annotations
import dataclasses, json
from datetime import date
from pathlib import Path
from typing import Any

from ironledger.audit import append_audit_event
from ironledger.db.connection import connect
from ironledger.project.errors import ProjectError
from ironledger.project.query import assert_fresh, balances, projection_status, search
from ironledger.valuation.formatting import format_minor_units, validate_calendar_date
from ironledger.valuation.models import _decimal_fraction
from ironledger.valuation.lots import OpenLot, simulate_lot_disposal, InsufficientInventoryError
from ironledger.valuation.engine import convert_amount_rational, ValuationEngine

CORE_TOOL_NAMES = ('search', 'balances', 'projection_status')
ANALYTICS_TOOL_NAMES = ('get_cash_flow_sankey', 'get_portfolio_holdings', 'trigger_price_sync', 'get_recurring_subscriptions')
TAX_TOOL_NAMES = ('get_capital_gains_summary', 'list_open_tax_lots', 'get_unrealized_gains', 'preview_lot_disposal')
SPLIT_TOOL_NAMES = ('preview_order_split', 'confirm_order_split')
TOOL_NAMES = CORE_TOOL_NAMES
ALL_TOOL_NAMES = CORE_TOOL_NAMES + ANALYTICS_TOOL_NAMES + TAX_TOOL_NAMES + SPLIT_TOOL_NAMES

def _audit_tool(
    db: str | None,
    *,
    action: str,
    target: str,
    result: str,
    input_hash: str | None = None,
) -> None:
    if not db:
        return
    conn = connect(str(db))
    try:
        append_audit_event(
            conn,
            actor='operator',
            action=action,
            target=target,
            result=result,
            input_hash=input_hash,
        )
        conn.commit()
    finally:
        conn.close()

def list_tools(include_analytics: bool = False, include_tax: bool = False, include_all: bool = False):
    core = [
        {
            'name': 'search',
            'description': 'Full-text search across ledger entries and postings.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string', 'description': 'FTS query string'},
                    'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500, 'default': 50},
                    'offset': {'type': 'integer', 'minimum': 0, 'default': 0},
                },
                'required': ['query'],
                'additionalProperties': False,
            },
        },
        {
            'name': 'balances',
            'description': 'Return ledger account balances by currency.',
            'inputSchema': {
                'type': 'object',
                'properties': {},
                'additionalProperties': False,
            },
        },
        {
            'name': 'projection_status',
            'description': 'Return freshness and hash status of the disposable projection.',
            'inputSchema': {
                'type': 'object',
                'properties': {},
                'additionalProperties': False,
            },
        },
    ]

    analytics_tools = [
        {
            'name': 'get_cash_flow_sankey',
            'description': 'Return directed cash-flow streams for Sankey visualization and cash analysis.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'period': {
                        'type': 'string',
                        'description': 'Month formatted as YYYY-MM (e.g. 2026-08)',
                    },
                },
                'required': ['period'],
                'additionalProperties': False,
            },
        },
        {
            'name': 'get_portfolio_holdings',
            'description': 'Return consolidated multi-asset portfolio holdings, rational valuations, and unrealized P&L.',
            'inputSchema': {
                'type': 'object',
                'properties': {},
                'additionalProperties': False,
            },
        },
        {
            'name': 'trigger_price_sync',
            'description': 'Resolve and persist exact-rational prices for requested symbols.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'symbols': {'type': 'array', 'items': {'type': 'string'}},
                    'quote_currency': {'type': 'string', 'default': 'USD'},
                },
                'required': ['symbols'],
                'additionalProperties': False,
            },
        },
        {
            'name': 'get_recurring_subscriptions',
            'description': 'Query recurring subscriptions, cadence analysis, and monthly fixed overhead.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'ledger_id': {
                        'type': 'string',
                        'description': 'Target ledger ID (default: "default")',
                        'default': 'default',
                    },
                    'cadence': {
                        'type': 'string',
                        'description': 'Optional filter by cadence (WEEKLY, BIWEEKLY, MONTHLY, QUARTERLY, ANNUAL)',
                        'enum': ['WEEKLY', 'BIWEEKLY', 'MONTHLY', 'QUARTERLY', 'ANNUAL', 'IRREGULAR'],
                    },
                    'include_irregular': {
                        'type': 'boolean',
                        'description': 'Whether to include irregular recurring expenses (default: false)',
                        'default': False,
                    },
                },
                'additionalProperties': False,
            },
        },
    ]

    tax_tools = [
        {
            'name': 'get_capital_gains_summary',
            'description': 'Return summarized realized capital gains, proceeds, cost basis, and holding period breakdown.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'ledger_id': {'type': 'string', 'default': 'default', 'description': 'Target ledger ID'},
                    'tax_year': {'type': ['integer', 'string', 'null'], 'description': 'Tax year filter (YYYY)'},
                    'term': {'type': 'string', 'enum': ['ALL', 'SHORT_TERM', 'LONG_TERM'], 'default': 'ALL', 'description': 'Holding period term filter'},
                    'account': {'type': ['string', 'null'], 'description': 'Optional account filter'},
                    'commodity': {'type': ['string', 'null'], 'description': 'Optional commodity filter'},
                },
                'additionalProperties': False,
            },
        },
        {
            'name': 'list_open_tax_lots',
            'description': 'List open tax lots with remaining units, unit cost basis, current market value, and unrealized gain/loss.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'ledger_id': {'type': 'string', 'default': 'default', 'description': 'Target ledger ID'},
                    'account': {'type': ['string', 'null'], 'description': 'Optional account filter'},
                    'commodity': {'type': ['string', 'null'], 'description': 'Optional commodity filter'},
                },
                'additionalProperties': False,
            },
        },
        {
            'name': 'get_unrealized_gains',
            'description': 'Return mark-to-market unrealized gains/losses across active positions using latest price directives.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'ledger_id': {'type': 'string', 'default': 'default', 'description': 'Target ledger ID'},
                    'commodity': {'type': ['string', 'null'], 'description': 'Optional commodity filter'},
                },
                'additionalProperties': False,
            },
        },
        {
            'name': 'preview_lot_disposal',
            'description': 'Simulate tax lot disposition (FIFO/LIFO/HIFO) and preview estimated realized gain/loss without mutating state.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'ledger_id': {'type': 'string', 'default': 'default', 'description': 'Target ledger ID'},
                    'commodity': {'type': 'string', 'description': 'Target commodity symbol'},
                    'quantity': {'type': ['string', 'number'], 'description': 'Units to dispose (e.g. "10" or "10.5")'},
                    'proceeds_rate': {'type': ['string', 'number'], 'description': 'Disposal price per unit (e.g. "450.00" or "450")'},
                    'strategy': {'type': 'string', 'enum': ['FIFO', 'LIFO', 'HIFO'], 'default': 'FIFO', 'description': 'Lot matching strategy'},
                    'disposal_date': {'type': ['string', 'null'], 'description': 'Disposal date YYYY-MM-DD (default: current date)'},
                    'account': {'type': ['string', 'null'], 'description': 'Optional account filter'},
                },
                'required': ['commodity', 'quantity', 'proceeds_rate'],
                'additionalProperties': False,
            },
        },
    ]

    split_tools = [
        {
            'name': 'preview_order_split',
            'description': 'Preview multi-leg itemized breakdown and proposed accounts for an order split proposal without mutating staged state.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'proposal_id': {'type': 'string', 'description': 'Split proposal ID to preview'},
                },
                'required': ['proposal_id'],
                'additionalProperties': False,
            },
        },
        {
            'name': 'confirm_order_split',
            'description': 'Confirm a multi-leg order split proposal, replacing staged contra postings with itemized legs transactionally.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'proposal_id': {'type': 'string', 'description': 'Split proposal ID to confirm'},
                },
                'required': ['proposal_id'],
                'additionalProperties': False,
            },
        },
    ]

    if include_all:
        return core + analytics_tools + tax_tools + split_tools
    res = list(core)
    if include_analytics:
        res.extend(analytics_tools)
    if include_tax:
        res.extend(tax_tools)
    return res

def call_tool(name, arguments, *, ledger_dir, projection_dir, db):
    args = arguments if arguments is not None else {}
    if name not in ALL_TOOL_NAMES:
        try:
            _audit_tool(db, action='mcp tools/call', target=str(name), result='error')
        except Exception:
            pass
        return {'isError': True, 'content': [{'type': 'text', 'text': 'Unknown tool ' + repr(name) + '.'}]}

    ledger_dir = Path(ledger_dir)
    projection_dir = Path(projection_dir)

    if name == 'preview_order_split':
        proposal_id = args.get('proposal_id')
        if not proposal_id or not isinstance(proposal_id, str):
            _audit_tool(db, action='mcp preview_order_split', target='preview_order_split', result='error')
            return {'isError': True, 'content': [{'type': 'text', 'text': 'Missing required string parameter proposal_id'}]}
        if not db:
            return {'isError': True, 'content': [{'type': 'text', 'text': 'Database connection required for preview_order_split'}]}
        conn = connect(str(db))
        try:
            prop = conn.execute(
                "SELECT sp.proposal_id, sp.order_id, sp.target_type, sp.target_id, "
                "       sp.parent_amount_minor, sp.match_confidence, sp.status, "
                "       io.merchant, io.order_date, io.total_minor_units, io.currency "
                "FROM split_proposals sp "
                "JOIN itemized_orders io ON sp.order_id = io.order_id "
                "WHERE sp.proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if not prop:
                _audit_tool(db, action='mcp preview_order_split', target=proposal_id, result='error')
                return {'isError': True, 'content': [{'type': 'text', 'text': f'Split proposal {proposal_id} not found'}]}

            lines = conn.execute(
                "SELECT line_index, item_title, item_description, quantity, total_price_minor, proposed_account, confidence_score "
                "FROM itemized_order_lines WHERE order_id = ? ORDER BY line_index",
                (prop[1],),
            ).fetchall()

            preview_data = {
                "proposal_id": prop[0],
                "order_id": prop[1],
                "target_type": prop[2],
                "target_id": prop[3],
                "parent_amount_minor": prop[4],
                "match_confidence": prop[5],
                "status": prop[6],
                "merchant": prop[7],
                "order_date": prop[8],
                "total_minor_units": prop[9],
                "currency": prop[10],
                "lines": [
                    {
                        "line_index": l[0],
                        "item_title": l[1],
                        "item_description": l[2],
                        "quantity": l[3],
                        "total_price_minor": l[4],
                        "proposed_account": l[5],
                        "confidence_score": l[6],
                    }
                    for l in lines
                ],
            }
            _audit_tool(db, action='mcp preview_order_split', target=proposal_id, result='ok')
            return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps(preview_data, indent=2)}]}
        finally:
            conn.close()

    if name == 'confirm_order_split':
        proposal_id = args.get('proposal_id')
        if not proposal_id or not isinstance(proposal_id, str):
            _audit_tool(db, action='mcp confirm_order_split', target='confirm_order_split', result='error')
            return {'isError': True, 'content': [{'type': 'text', 'text': 'Missing required string parameter proposal_id'}]}
        if not db:
            return {'isError': True, 'content': [{'type': 'text', 'text': 'Database connection required for confirm_order_split'}]}
        from ironledger.ingest.split_linker import confirm_split_proposal
        conn = connect(str(db))
        try:
            res = confirm_split_proposal(conn, proposal_id, actor='operator')
            _audit_tool(db, action='mcp confirm_order_split', target=proposal_id, result='ok')
            return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps(res, indent=2)}]}
        except Exception as exc:
            _audit_tool(db, action='mcp confirm_order_split', target=proposal_id, result='error')
            return {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}
        finally:
            conn.close()

    if name == 'trigger_price_sync':
        from ironledger.prices.providers.manual import ManualProvider
        from ironledger.prices.router import PriceCascadeRouter, create_default_price_router
        from ironledger.prices.scraper_daemon import PriceScraperDaemon
        symbols = args.get('symbols')
        quote = args.get('quote_currency', 'USD')
        if not isinstance(symbols, list) or not all(isinstance(symbol, str) for symbol in symbols):
            _audit_tool(db, action='mcp trigger_price_sync', target='trigger_price_sync', result='error')
            return {'isError': True, 'content': [{'type': 'text', 'text': 'symbols must be an array of strings'}]}
        if not isinstance(quote, str):
            _audit_tool(db, action='mcp trigger_price_sync', target='trigger_price_sync', result='error')
            return {'isError': True, 'content': [{'type': 'text', 'text': 'quote_currency must be a string'}]}
        result = PriceScraperDaemon(Path(db), ledger_dir.joinpath('prices.beancount'), create_default_price_router()).sync_watchlist([(symbol, quote) for symbol in symbols])

        try:
            audit_result = 'ok' if result['status'] == 'success' else 'error'
            _audit_tool(db, action='mcp trigger_price_sync', target='trigger_price_sync', result=audit_result)
        except Exception:
            return {'isError': True, 'content': [{'type': 'text', 'text': 'Audit logging failed'}]}
        return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps(result, sort_keys=True)}]}

    if name == 'projection_status':
        status_data = projection_status(ledger_dir, projection_dir, db=db)
        input_hash = status_data.get('ledger_output_hash')
        try:
            _audit_tool(db, action='mcp status', target='projection_status', result='ok', input_hash=input_hash)
        except Exception as exc:
            return {'isError': True, 'content': [{'type': 'text', 'text': 'Audit failure: ' + str(exc)}]}
        return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps(status_data, indent=2, sort_keys=True)}]}

    action_name = f'mcp {name}'
    try:
        conn = assert_fresh(ledger_dir, projection_dir, db=db)
    except ProjectError as exc:
        try:
            _audit_tool(db, action=action_name, target=str(name), result='error')
        except Exception:
            pass
        return {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}

    input_hash = None
    try:
        row = conn.execute('SELECT ledger_output_hash FROM projection_meta WHERE singleton = 1').fetchone()
        if row:
            input_hash = row[0]
    except Exception:
        pass

    try:
        if name == 'search':
            query = args.get('query', '')
            limit = args.get('limit', 50)
            offset = args.get('offset', 0)
            if not isinstance(query, str):
                _audit_tool(db, action='mcp search', target='search', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': 'query must be a string'}]}
            if not isinstance(limit, int) or not isinstance(offset, int) or isinstance(limit, bool) or isinstance(offset, bool):
                _audit_tool(db, action='mcp search', target='search', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': 'limit and offset must be integers'}]}
            hits_raw = search(conn, query, limit=limit, offset=offset)
            try:
                _audit_tool(db, action='mcp search', target='search', result='ok', input_hash=input_hash)
            except Exception:
                return {'isError': True, 'content': [{'type': 'text', 'text': 'Audit logging failed'}]}
            hits = [dataclasses.asdict(h) for h in hits_raw]
            return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps({'hits': hits}, indent=2, sort_keys=True)}]}
        elif name == 'balances':
            bals_raw = balances(conn)
            try:
                _audit_tool(db, action='mcp balances', target='balances', result='ok', input_hash=input_hash)
            except Exception:
                return {'isError': True, 'content': [{'type': 'text', 'text': 'Audit logging failed'}]}
            bals = [dataclasses.asdict(b) for b in bals_raw]
            return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps({'balances': bals}, indent=2, sort_keys=True)}]}
        elif name == 'get_cash_flow_sankey':
            period = args.get('period', '')
            if not isinstance(period, str) or len(period) != 7:
                _audit_tool(db, action='mcp get_cash_flow_sankey', target='get_cash_flow_sankey', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': 'period must be a YYYY-MM string'}]}
            db_conn = connect(str(db)) if db else conn
            try:
                cur = db_conn.cursor()
                cur.execute(
                    "SELECT source_node, target_node, amount_minor_units FROM v_sankey_cash_flows WHERE period_month = ?",
                    (period,),
                )
                flows = [
                    {'source_node': str(r[0]), 'target_node': str(r[1]), 'amount_minor_units': int(r[2])}
                    for r in cur.fetchall()
                ]
                _audit_tool(db, action='mcp get_cash_flow_sankey', target='get_cash_flow_sankey', result='ok', input_hash=input_hash)
                return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps({'flows': flows}, indent=2, sort_keys=True)}]}
            except Exception as e:
                _audit_tool(db, action='mcp get_cash_flow_sankey', target='get_cash_flow_sankey', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': f'Query error: {e}'}]}
            finally:
                if db and db_conn != conn:
                    db_conn.close()
        elif name == 'get_portfolio_holdings':
            db_conn = connect(str(db)) if db else conn
            try:
                cur = db_conn.cursor()
                cur.execute(
                    "SELECT commodity, total_units, total_cost_basis_minor_units, base_currency, market_value_minor_units, unrealized_gain_minor_units FROM v_portfolio_holdings"
                )
                holdings = [
                    {
                        'commodity': str(r[0]),
                        'total_units': int(r[1]) if r[1] is not None else 0,
                        'total_cost_basis_minor_units': int(r[2]) if r[2] is not None else 0,
                        'base_currency': str(r[3]),
                        'market_value_minor_units': int(r[4]) if r[4] is not None else 0,
                        'unrealized_gain_minor_units': int(r[5]) if r[5] is not None else 0,
                    }
                    for r in cur.fetchall()
                ]
                _audit_tool(db, action='mcp get_portfolio_holdings', target='get_portfolio_holdings', result='ok', input_hash=input_hash)
                return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps({'holdings': holdings}, indent=2, sort_keys=True)}]}
            except Exception as e:
                _audit_tool(db, action='mcp get_portfolio_holdings', target='get_portfolio_holdings', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': f'Query error: {e}'}]}
            finally:
                if db and db_conn != conn:
                    db_conn.close()
        elif name == 'get_recurring_subscriptions':
            from ironledger.analytics.subscriptions import get_recurring_subscriptions as query_subscriptions
            ledger_id = str(args.get('ledger_id') or 'default')
            cadence = args.get('cadence')
            include_irregular = bool(args.get('include_irregular', False))
            db_conn = None
            try:
                db_conn = connect(str(db)) if db else conn
                result = query_subscriptions(
                    db_conn,
                    ledger_id=ledger_id,
                    cadence_filter=str(cadence) if cadence is not None else None,
                    include_irregular=include_irregular,
                )
                _audit_tool(db, action='mcp get_recurring_subscriptions', target='get_recurring_subscriptions', result='ok', input_hash=input_hash)
                return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps(result, indent=2, sort_keys=True)}]}
            except Exception as e:
                _audit_tool(db, action='mcp get_recurring_subscriptions', target='get_recurring_subscriptions', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': f'Query error: {e}'}]}
            finally:
                if db and db_conn is not None and db_conn != conn:
                    db_conn.close()
        elif name == 'get_capital_gains_summary':
            ledger_id = str(args.get('ledger_id') or 'default')
            tax_year = args.get('tax_year')
            term = str(args.get('term') or 'ALL').upper()
            account = args.get('account')
            commodity = args.get('commodity')

            if term not in {'ALL', 'SHORT_TERM', 'LONG_TERM'}:
                _audit_tool(db, action='mcp get_capital_gains_summary', target='get_capital_gains_summary', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': 'term must be ALL, SHORT_TERM, or LONG_TERM'}]}

            year_str = str(tax_year) if tax_year is not None else None
            if year_str is not None and not (len(year_str) == 4 and year_str.isdigit()):
                _audit_tool(db, action='mcp get_capital_gains_summary', target='get_capital_gains_summary', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': 'tax_year must be a 4-digit year'}]}

            db_conn = connect(str(db)) if db else conn
            try:
                # Fetch functional currency
                row = db_conn.execute("SELECT base_currency FROM ledgers WHERE ledger_id = ?", (ledger_id,)).fetchone()
                functional_currency = str(row[0]) if row and row[0] else 'USD'

                clauses = ["ledger_id = ?"]
                params: list[Any] = [ledger_id]
                if year_str is not None:
                    clauses.append("disposal_date LIKE ?")
                    params.append(f"{year_str}-%")
                if term != "ALL":
                    clauses.append("term_classification = ?")
                    params.append(term)
                if commodity is not None:
                    clauses.append("commodity = ?")
                    params.append(str(commodity))
                if account is not None:
                    clauses.append("account = ?")
                    params.append(str(account))

                where_sql = " AND ".join(clauses)
                query_sql = f"""
                    SELECT 
                        COALESCE(SUM(functional_realized_gain_minor), 0),
                        COALESCE(SUM(functional_proceeds_minor), 0),
                        COALESCE(SUM(functional_cost_basis_minor), 0),
                        COALESCE(SUM(CASE WHEN term_classification = 'SHORT_TERM' THEN functional_realized_gain_minor ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN term_classification = 'SHORT_TERM' THEN functional_proceeds_minor ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN term_classification = 'SHORT_TERM' THEN functional_cost_basis_minor ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN term_classification = 'LONG_TERM' THEN functional_realized_gain_minor ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN term_classification = 'LONG_TERM' THEN functional_proceeds_minor ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN term_classification = 'LONG_TERM' THEN functional_cost_basis_minor ELSE 0 END), 0),
                        COUNT(*)
                    FROM lot_disposal_allocations
                    WHERE {where_sql}
                """
                agg_row = db_conn.execute(query_sql, params).fetchone()

                total_gain = int(agg_row[0])
                total_proceeds = int(agg_row[1])
                total_cost_basis = int(agg_row[2])
                st_gain = int(agg_row[3])
                st_proceeds = int(agg_row[4])
                st_cost_basis = int(agg_row[5])
                lt_gain = int(agg_row[6])
                lt_proceeds = int(agg_row[7])
                lt_cost_basis = int(agg_row[8])
                disposal_count = int(agg_row[9])

                summary_payload = {
                    'ledger_id': ledger_id,
                    'functional_currency': functional_currency,
                    'tax_year': int(year_str) if year_str else None,
                    'term_filter': term,
                    'total_realized_gain_minor': total_gain,
                    'total_realized_gain_display': format_minor_units(total_gain, 2),
                    'total_proceeds_minor': total_proceeds,
                    'total_proceeds_display': format_minor_units(total_proceeds, 2),
                    'total_cost_basis_minor': total_cost_basis,
                    'total_cost_basis_display': format_minor_units(total_cost_basis, 2),
                    'short_term': {
                        'realized_gain_minor': st_gain,
                        'realized_gain_display': format_minor_units(st_gain, 2),
                        'proceeds_minor': st_proceeds,
                        'proceeds_display': format_minor_units(st_proceeds, 2),
                        'cost_basis_minor': st_cost_basis,
                        'cost_basis_display': format_minor_units(st_cost_basis, 2),
                    },
                    'long_term': {
                        'realized_gain_minor': lt_gain,
                        'realized_gain_display': format_minor_units(lt_gain, 2),
                        'proceeds_minor': lt_proceeds,
                        'proceeds_display': format_minor_units(lt_proceeds, 2),
                        'cost_basis_minor': lt_cost_basis,
                        'cost_basis_display': format_minor_units(lt_cost_basis, 2),
                    },
                    'disposal_count': disposal_count,
                }
                _audit_tool(db, action='mcp get_capital_gains_summary', target='get_capital_gains_summary', result='ok', input_hash=input_hash)
                return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps(summary_payload, indent=2, sort_keys=True)}]}
            except Exception as e:
                _audit_tool(db, action='mcp get_capital_gains_summary', target='get_capital_gains_summary', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': f'Query error: {e}'}]}
            finally:
                if db and db_conn != conn:
                    db_conn.close()

        elif name == 'list_open_tax_lots':
            ledger_id = str(args.get('ledger_id') or 'default')
            account = args.get('account')
            commodity = args.get('commodity')

            db_conn = connect(str(db)) if db else conn
            try:
                engine = ValuationEngine(db_conn)
                clauses = ["ledger_id = ? AND remaining_units_minor > 0"]
                params = [ledger_id]
                if account is not None:
                    clauses.append("account = ?")
                    params.append(str(account))
                if commodity is not None:
                    clauses.append("commodity = ?")
                    params.append(str(commodity))

                where_sql = " AND ".join(clauses)
                lots_sql = f"""
                    SELECT 
                        lot_key, account, commodity, acquisition_date,
                        remaining_units_minor, unit_scale,
                        functional_unit_cost_numerator, functional_unit_cost_denominator,
                        native_cost_numerator, native_cost_denominator, native_cost_currency,
                        functional_currency, functional_cost_basis_minor,
                        remaining_functional_cost_basis_minor, lot_label
                    FROM open_lots
                    WHERE {where_sql}
                    ORDER BY acquisition_date, lot_key
                """
                rows = db_conn.execute(lots_sql, params).fetchall()

                today_iso = date.today().isoformat()
                lots_out = []
                for r in rows:
                    (
                        lot_key, acct, comm, acq_date,
                        rem_units, scale,
                        f_cost_num, f_cost_den,
                        n_cost_num, n_cost_den, n_cost_curr,
                        f_curr, orig_basis, rem_basis, lot_label
                    ) = r

                    market_value_minor = None
                    market_value_display = None
                    unrealized_gain_minor = None
                    unrealized_gain_display = None
                    price_num = None
                    price_den = None

                    try:
                        price = engine.get_price(str(comm), str(f_curr), today_iso, ledger_id=ledger_id, conn=db_conn)
                        price_num, price_den = price.rate_numerator, price.rate_denominator
                        market_value_minor = convert_amount_rational(rem_units, scale, price_num, price_den, 2)
                        unrealized_gain_minor = market_value_minor - rem_basis
                        market_value_display = format_minor_units(market_value_minor, 2)
                        unrealized_gain_display = format_minor_units(unrealized_gain_minor, 2)
                    except Exception:
                        pass

                    lots_out.append({
                        'lot_key': str(lot_key),
                        'account': str(acct),
                        'commodity': str(comm),
                        'acquisition_date': str(acq_date),
                        'remaining_units_minor': int(rem_units),
                        'unit_scale': int(scale),
                        'quantity_display': format_minor_units(rem_units, scale),
                        'functional_currency': str(f_curr),
                        'unit_cost_numerator': int(f_cost_num),
                        'unit_cost_denominator': int(f_cost_den),
                        'current_basis_minor': int(rem_basis),
                        'current_basis_display': format_minor_units(rem_basis, 2),
                        'market_price_numerator': price_num,
                        'market_price_denominator': price_den,
                        'market_value_minor': market_value_minor,
                        'market_value_display': market_value_display,
                        'unrealized_gain_loss_minor': unrealized_gain_minor,
                        'unrealized_gain_loss_display': unrealized_gain_display,
                        'lot_label': str(lot_label) if lot_label else None,
                    })

                _audit_tool(db, action='mcp list_open_tax_lots', target='list_open_tax_lots', result='ok', input_hash=input_hash)
                return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps({'lots': lots_out, 'count': len(lots_out)}, indent=2, sort_keys=True)}]}
            except Exception as e:
                _audit_tool(db, action='mcp list_open_tax_lots', target='list_open_tax_lots', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': f'Query error: {e}'}]}
            finally:
                if db and db_conn != conn:
                    db_conn.close()

        elif name == 'get_unrealized_gains':
            ledger_id = str(args.get('ledger_id') or 'default')
            commodity = args.get('commodity')

            db_conn = connect(str(db)) if db else conn
            try:
                engine = ValuationEngine(db_conn)
                row = db_conn.execute("SELECT base_currency FROM ledgers WHERE ledger_id = ?", (ledger_id,)).fetchone()
                functional_currency = str(row[0]) if row and row[0] else 'USD'

                clauses = ["ledger_id = ? AND remaining_units_minor > 0"]
                params = [ledger_id]
                if commodity is not None:
                    clauses.append("commodity = ?")
                    params.append(str(commodity))

                where_sql = " AND ".join(clauses)
                group_sql = f"""
                    SELECT 
                        commodity, unit_scale,
                        SUM(remaining_units_minor),
                        SUM(remaining_functional_cost_basis_minor)
                    FROM open_lots
                    WHERE {where_sql}
                    GROUP BY commodity, unit_scale
                    ORDER BY commodity
                """
                rows = db_conn.execute(group_sql, params).fetchall()

                today_iso = date.today().isoformat()
                positions = []
                total_basis = 0
                total_market = 0
                total_unrealized = 0

                for comm, scale, units, basis in rows:
                    units = int(units)
                    basis = int(basis)
                    total_basis += basis

                    price_num, price_den = 1, 1
                    price_display = "1.0000"
                    if str(comm) != functional_currency:
                        try:
                            price = engine.get_price(str(comm), functional_currency, today_iso, ledger_id=ledger_id, conn=db_conn)
                            price_num, price_den = price.rate_numerator, price.rate_denominator
                            pq, pr = divmod(price_num * 10000, price_den)
                            price_display = f"{pq // 10000}.{pq % 10000:04d}"
                        except Exception:
                            price_num, price_den = 0, 1
                            price_display = "0.0000"

                    market_val = convert_amount_rational(units, scale, price_num, price_den, 2) if price_num > 0 else 0
                    unrealized_gain = market_val - basis if price_num > 0 else 0

                    total_market += market_val
                    total_unrealized += unrealized_gain

                    positions.append({
                        'commodity': str(comm),
                        'total_units_minor': units,
                        'unit_scale': int(scale),
                        'quantity_display': format_minor_units(units, scale),
                        'functional_currency': functional_currency,
                        'cost_basis_minor': basis,
                        'cost_basis_display': format_minor_units(basis, 2),
                        'latest_price_numerator': price_num,
                        'latest_price_denominator': price_den,
                        'latest_price_display': price_display,
                        'market_value_minor': market_val,
                        'market_value_display': format_minor_units(market_val, 2),
                        'unrealized_gain_minor': unrealized_gain,
                        'unrealized_gain_display': format_minor_units(unrealized_gain, 2),
                    })

                summary = {
                    'ledger_id': ledger_id,
                    'functional_currency': functional_currency,
                    'total_cost_basis_minor': total_basis,
                    'total_cost_basis_display': format_minor_units(total_basis, 2),
                    'total_market_value_minor': total_market,
                    'total_market_value_display': format_minor_units(total_market, 2),
                    'total_unrealized_gain_minor': total_unrealized,
                    'total_unrealized_gain_display': format_minor_units(total_unrealized, 2),
                    'positions': positions,
                }
                _audit_tool(db, action='mcp get_unrealized_gains', target='get_unrealized_gains', result='ok', input_hash=input_hash)
                return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps(summary, indent=2, sort_keys=True)}]}
            except Exception as e:
                _audit_tool(db, action='mcp get_unrealized_gains', target='get_unrealized_gains', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': f'Query error: {e}'}]}
            finally:
                if db and db_conn != conn:
                    db_conn.close()

        elif name == 'preview_lot_disposal':
            ledger_id = str(args.get('ledger_id') or 'default')
            commodity = args.get('commodity')
            quantity_raw = args.get('quantity')
            proceeds_rate_raw = args.get('proceeds_rate')
            strategy = str(args.get('strategy') or 'FIFO').upper()
            disposal_date = str(args.get('disposal_date') or date.today().isoformat())
            account = args.get('account')

            if not commodity or not isinstance(commodity, str):
                _audit_tool(db, action='mcp preview_lot_disposal', target='preview_lot_disposal', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': 'commodity must be a non-empty string'}]}

            if quantity_raw is None:
                _audit_tool(db, action='mcp preview_lot_disposal', target='preview_lot_disposal', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': 'quantity is required'}]}

            if proceeds_rate_raw is None:
                _audit_tool(db, action='mcp preview_lot_disposal', target='preview_lot_disposal', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': 'proceeds_rate is required'}]}

            if strategy not in {'FIFO', 'LIFO', 'HIFO'}:
                _audit_tool(db, action='mcp preview_lot_disposal', target='preview_lot_disposal', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': 'strategy must be FIFO, LIFO, or HIFO'}]}

            try:
                valid_date = validate_calendar_date(disposal_date)
            except Exception as e:
                _audit_tool(db, action='mcp preview_lot_disposal', target='preview_lot_disposal', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': f'Invalid disposal_date: {e}'}]}

            db_conn = connect(str(db)) if db else conn
            try:
                row = db_conn.execute("SELECT base_currency FROM ledgers WHERE ledger_id = ?", (ledger_id,)).fetchone()
                functional_currency = str(row[0]) if row and row[0] else 'USD'

                clauses = ["ledger_id = ? AND commodity = ? AND remaining_units_minor > 0"]
                params = [ledger_id, commodity]
                if account is not None:
                    clauses.append("account = ?")
                    params.append(str(account))

                where_sql = " AND ".join(clauses)
                lot_rows = db_conn.execute(
                    f"""
                    SELECT lot_key, ledger_id, account, commodity, acquisition_date,
                           remaining_units_minor, unit_scale, functional_unit_cost_numerator,
                           functional_unit_cost_denominator, native_cost_currency,
                           functional_cost_basis_minor, remaining_functional_cost_basis_minor
                    FROM open_lots
                    WHERE {where_sql}
                    ORDER BY acquisition_date, lot_key
                    """,
                    params
                ).fetchall()

                if not lot_rows:
                    _audit_tool(db, action='mcp preview_lot_disposal', target='preview_lot_disposal', result='error', input_hash=input_hash)
                    return {'isError': True, 'content': [{'type': 'text', 'text': f'No open lots found for {commodity} in ledger {ledger_id}'}]}

                unit_scale = lot_rows[0][6]
                open_lots_in_memory = [
                    OpenLot(
                        lot_key=str(r[0]),
                        ledger_id=str(r[1]),
                        account=str(r[2]),
                        commodity=str(r[3]),
                        acquisition_date=str(r[4]),
                        remaining_units_minor=int(r[5]),
                        unit_scale=int(r[6]),
                        cost_num=int(r[7]),
                        cost_den=int(r[8]),
                        cost_currency=str(r[9]),
                        original_basis_minor=int(r[10]),
                        remaining_basis_minor=int(r[11]),
                    )
                    for r in lot_rows
                ]

                # Parse quantity
                q_num, q_den = _decimal_fraction(str(quantity_raw))
                if q_num <= 0:
                    _audit_tool(db, action='mcp preview_lot_disposal', target='preview_lot_disposal', result='error', input_hash=input_hash)
                    return {'isError': True, 'content': [{'type': 'text', 'text': 'quantity must be positive'}]}
                units_minor = (q_num * (10 ** unit_scale)) // q_den

                # Parse proceeds rate
                p_num, p_den = _decimal_fraction(str(proceeds_rate_raw))
                if p_num <= 0:
                    _audit_tool(db, action='mcp preview_lot_disposal', target='preview_lot_disposal', result='error', input_hash=input_hash)
                    return {'isError': True, 'content': [{'type': 'text', 'text': 'proceeds_rate must be positive'}]}

                allocations, remaining_lots = simulate_lot_disposal(
                    open_lots_in_memory,
                    units_disposed_minor=units_minor,
                    unit_scale=unit_scale,
                    disposal_price_num=p_num,
                    disposal_price_denom=p_den,
                    strategy=strategy,
                    disposal_date=valid_date,
                    functional_currency=functional_currency,
                )

                tot_proceeds = sum(a.functional_proceeds_minor for a in allocations)
                tot_basis = sum(a.functional_cost_basis_minor for a in allocations)
                tot_gain = sum(a.functional_realized_gain_minor for a in allocations)
                st_gain = sum(a.functional_realized_gain_minor for a in allocations if a.term_classification == 'SHORT_TERM')
                lt_gain = sum(a.functional_realized_gain_minor for a in allocations if a.term_classification == 'LONG_TERM')

                alloc_out = [
                    {
                        'open_lot_key': a.open_lot_key,
                        'acquisition_date': a.acquisition_date,
                        'disposal_date': a.disposal_date,
                        'units_disposed_minor': a.units_disposed_minor,
                        'units_disposed_display': format_minor_units(a.units_disposed_minor, unit_scale),
                        'holding_period_days': a.holding_period_days,
                        'term_classification': a.term_classification,
                        'functional_proceeds_minor': a.functional_proceeds_minor,
                        'functional_proceeds_display': format_minor_units(a.functional_proceeds_minor, 2),
                        'functional_cost_basis_minor': a.functional_cost_basis_minor,
                        'functional_cost_basis_display': format_minor_units(a.functional_cost_basis_minor, 2),
                        'functional_realized_gain_minor': a.functional_realized_gain_minor,
                        'functional_realized_gain_display': format_minor_units(a.functional_realized_gain_minor, 2),
                    }
                    for a in allocations
                ]

                remaining_out = [
                    {
                        'lot_key': lot.lot_key,
                        'account': lot.account,
                        'commodity': lot.commodity,
                        'acquisition_date': lot.acquisition_date,
                        'remaining_units_minor': lot.remaining_units_minor,
                        'remaining_units_display': format_minor_units(lot.remaining_units_minor, lot.unit_scale),
                        'remaining_basis_minor': lot.remaining_basis_minor,
                        'remaining_basis_display': format_minor_units(lot.remaining_basis_minor, 2),
                    }
                    for lot in remaining_lots
                    if lot.remaining_units_minor > 0
                ]

                preview_result = {
                    'simulation_status': 'SUCCESS',
                    'ledger_id': ledger_id,
                    'commodity': commodity,
                    'strategy': strategy,
                    'disposal_date': valid_date,
                    'units_disposed_minor': units_minor,
                    'units_disposed_display': format_minor_units(units_minor, unit_scale),
                    'total_proceeds_minor': tot_proceeds,
                    'total_proceeds_display': format_minor_units(tot_proceeds, 2),
                    'total_cost_basis_minor': tot_basis,
                    'total_cost_basis_display': format_minor_units(tot_basis, 2),
                    'total_realized_gain_minor': tot_gain,
                    'total_realized_gain_display': format_minor_units(tot_gain, 2),
                    'short_term_gain_minor': st_gain,
                    'short_term_gain_display': format_minor_units(st_gain, 2),
                    'long_term_gain_minor': lt_gain,
                    'long_term_gain_display': format_minor_units(lt_gain, 2),
                    'allocations': alloc_out,
                    'remaining_lots': remaining_out,
                }

                _audit_tool(db, action='mcp preview_lot_disposal', target='preview_lot_disposal', result='ok', input_hash=input_hash)
                return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps(preview_result, indent=2, sort_keys=True)}]}
            except InsufficientInventoryError as e:
                _audit_tool(db, action='mcp preview_lot_disposal', target='preview_lot_disposal', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': f'Insufficient inventory: {e}'}]}
            except Exception as e:
                _audit_tool(db, action='mcp preview_lot_disposal', target='preview_lot_disposal', result='error', input_hash=input_hash)
                return {'isError': True, 'content': [{'type': 'text', 'text': f'Preview error: {e}'}]}
            finally:
                if db and db_conn != conn:
                    db_conn.close()

    except ProjectError as exc:
        try:
            _audit_tool(db, action=action_name, target=str(name), result='error', input_hash=input_hash)
        except Exception:
            pass
        return {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}
    finally:
        conn.close()

