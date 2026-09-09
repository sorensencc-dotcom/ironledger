"""Newline-delimited JSON-RPC stdio transport."""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

from ironledger.mcp.protocol import handle_message

_logger = logging.getLogger('ironledger.mcp')
MAX_HTTP_BODY: int = 1_048_576


def run_stdio(
    stdin: io.BufferedIOBase | io.RawIOBase | Any,
    stdout: io.BufferedIOBase | io.RawIOBase | Any,
    stderr: Any,
    *,
    ledger_dir: Path,
    projection_dir: Path,
    db: str | None,
) -> int:
    """Process JSON-RPC messages line-by-line on binary stdin/stdout streams."""
    ledger_dir = Path(ledger_dir)
    projection_dir = Path(projection_dir)

    while True:
        line = stdin.readline(MAX_HTTP_BODY + 1)
        if not line:
            break

        if len(line) > MAX_HTTP_BODY:
            if not line.endswith(b'\n'):
                stdin.readline()
            err_msg = json.dumps({
                'jsonrpc': '2.0',
                'id': None,
                'error': {'code': -32700, 'message': 'Line exceeds maximum allowed size'},
            }, sort_keys=True)
            stdout.write(err_msg.encode('utf-8') + b'\n')
            stdout.flush()
            continue

        raw_bytes = line.rstrip(b'\r\n')
        if not raw_bytes:
            continue

        try:
            raw_str = raw_bytes.decode('utf-8')
        except UnicodeDecodeError:
            err_msg = json.dumps({
                'jsonrpc': '2.0',
                'id': None,
                'error': {'code': -32700, 'message': 'Parse error'},
            }, sort_keys=True)
            stdout.write(err_msg.encode('utf-8') + b'\n')
            stdout.flush()
            continue

        resp = handle_message(raw_str, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
        if resp is not None:
            stdout.write(resp.encode('utf-8') + b'\n')
            stdout.flush()

    return 0
