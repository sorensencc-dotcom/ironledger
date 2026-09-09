from __future__ import annotations
import dataclasses, json
from pathlib import Path
from typing import Any

from ironledger.audit import append_audit_event
from ironledger.db.connection import connect
from ironledger.project.errors import ProjectError
from ironledger.project.query import assert_fresh, balances, projection_status, search

TOOL_NAMES = ('search', 'balances', 'projection_status')

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

def list_tools():
    return [
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

def call_tool(name, arguments, *, ledger_dir, projection_dir, db):
    args = arguments if arguments is not None else {}
    if name not in TOOL_NAMES:
        try:
            _audit_tool(db, action='mcp tools/call', target=str(name), result='error')
        except Exception:
            pass
        return {'isError': True, 'content': [{'type': 'text', 'text': 'Unknown tool ' + repr(name) + '.'}]}

    ledger_dir = Path(ledger_dir)
    projection_dir = Path(projection_dir)

    if name == 'projection_status':
        status_data = projection_status(ledger_dir, projection_dir, db=db)
        input_hash = status_data.get('ledger_output_hash')
        try:
            _audit_tool(db, action='mcp status', target='projection_status', result='ok', input_hash=input_hash)
        except Exception as exc:
            return {'isError': True, 'content': [{'type': 'text', 'text': 'Audit failure: ' + str(exc)}]}
        return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps(status_data, indent=2, sort_keys=True)}]}

    action_name = 'mcp search' if name == 'search' else 'mcp balances'
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
            _audit_tool(db, action='mcp search', target='search', result='ok', input_hash=input_hash)
            hits = [dataclasses.asdict(h) for h in hits_raw]
            return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps({'hits': hits}, indent=2, sort_keys=True)}]}
        elif name == 'balances':
            bals_raw = balances(conn)
            _audit_tool(db, action='mcp balances', target='balances', result='ok', input_hash=input_hash)
            bals = [dataclasses.asdict(b) for b in bals_raw]
            return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps({'balances': bals}, indent=2, sort_keys=True)}]}
    except ProjectError as exc:
        try:
            _audit_tool(db, action=action_name, target=str(name), result='error', input_hash=input_hash)
        except Exception:
            pass
        return {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}
    except Exception as exc:
        return {'isError': True, 'content': [{'type': 'text', 'text': 'Audit failure: ' + str(exc)}]}
    finally:
        conn.close()
