from __future__ import annotations
import dataclasses, json
from pathlib import Path
from typing import Any
from ironledger.project.errors import ProjectError
from ironledger.project.query import assert_fresh, balances, projection_status, search

TOOL_NAMES = ('search', 'balances', 'projection_status')

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
        return {'isError': True, 'content': [{'type': 'text', 'text': 'Unknown tool ' + repr(name) + '.'}]}

    ledger_dir = Path(ledger_dir)
    projection_dir = Path(projection_dir)

    if name == 'projection_status':
        status_data = projection_status(ledger_dir, projection_dir, db=db)
        return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps(status_data, indent=2, sort_keys=True)}]}

    try:
        conn = assert_fresh(ledger_dir, projection_dir, db=db)
    except ProjectError as exc:
        return {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}

    try:
        if name == 'search':
            query = args.get('query', '')
            limit = args.get('limit', 50)
            offset = args.get('offset', 0)
            if not isinstance(query, str):
                return {'isError': True, 'content': [{'type': 'text', 'text': 'query must be a string'}]}
            if not isinstance(limit, int) or not isinstance(offset, int) or isinstance(limit, bool) or isinstance(offset, bool):
                return {'isError': True, 'content': [{'type': 'text', 'text': 'limit and offset must be integers'}]}
            hits_raw = search(conn, query, limit=limit, offset=offset)
            hits = [dataclasses.asdict(h) for h in hits_raw]
            return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps({'hits': hits}, indent=2, sort_keys=True)}]}
        elif name == 'balances':
            bals_raw = balances(conn)
            bals = [dataclasses.asdict(b) for b in bals_raw]
            return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps({'balances': bals}, indent=2, sort_keys=True)}]}
    except ProjectError as exc:
        return {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}
    finally:
        conn.close()
