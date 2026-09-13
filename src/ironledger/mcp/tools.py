from __future__ import annotations
import dataclasses, json
from pathlib import Path
from typing import Any

from ironledger.audit import append_audit_event
from ironledger.db.connection import connect
from ironledger.project.errors import ProjectError
from ironledger.project.query import assert_fresh, balances, projection_status, search

CORE_TOOL_NAMES = ('search', 'balances', 'projection_status')
ANALYTICS_TOOL_NAMES = ('get_cash_flow_sankey', 'get_portfolio_holdings', 'trigger_price_sync')
TOOL_NAMES = CORE_TOOL_NAMES
ALL_TOOL_NAMES = CORE_TOOL_NAMES + ANALYTICS_TOOL_NAMES

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

def list_tools(include_analytics: bool = False):
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
    if not include_analytics:
        return core

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
    ]
    return core + analytics_tools

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

    if name == 'trigger_price_sync':
        from ironledger.prices.providers.manual import ManualProvider
        from ironledger.prices.router import PriceCascadeRouter, create_default_price_router
        from ironledger.prices.scraper_daemon import PriceScraperDaemon
        symbols = args.get('symbols')
        quote = args.get('quote_currency', 'USD')
        if not isinstance(symbols, list) or not all(isinstance(symbol, str) for symbol in symbols):
            return {'isError': True, 'content': [{'type': 'text', 'text': 'symbols must be an array of strings'}]}
        if not isinstance(quote, str):
            return {'isError': True, 'content': [{'type': 'text', 'text': 'quote_currency must be a string'}]}
        result = PriceScraperDaemon(Path(db), ledger_dir / 'prices.beancount', create_default_price_router()).sync_watchlist([(symbol, quote) for symbol in symbols])

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
            # Query db for v_sankey_cash_flows
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
    except ProjectError as exc:
        try:
            _audit_tool(db, action=action_name, target=str(name), result='error', input_hash=input_hash)
        except Exception:
            pass
        return {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}
    finally:
        conn.close()
