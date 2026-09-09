"""JSON-RPC 2.0 and MCP 2025-03-26 message handling."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ironledger import __version__
from ironledger.mcp import PROTOCOL_VERSION
from ironledger.mcp.tools import call_tool, list_tools

_logger = logging.getLogger("ironledger.mcp")


def _jsonrpc_error(code: int, message: str, req_id: Any = None) -> str:
    return json.dumps({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }, sort_keys=True)


def _jsonrpc_result(result: Any, req_id: Any) -> str:
    return json.dumps({
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result,
    }, sort_keys=True)


def handle_message(
    raw: str,
    *,
    ledger_dir: Path,
    projection_dir: Path,
    db: str | None,
) -> str | None:
    """Process a single JSON-RPC / MCP message. Returns None for notifications."""
    try:
        data = json.loads(raw)
    except Exception:
        return _jsonrpc_error(-32700, "Parse error", None)

    if isinstance(data, list):
        return _jsonrpc_error(-32600, "Invalid Request: batch not supported", None)

    if not isinstance(data, dict):
        return _jsonrpc_error(-32600, "Invalid Request: must be object", None)

    req_id = data.get("id")
    method = data.get("method")

    if not isinstance(method, str):
        return _jsonrpc_error(-32600, "Invalid Request: missing method", req_id)

    is_notification = "id" not in data

    if method.startswith("notifications/"):
        return None

    if is_notification:
        return None

    try:
        if method == "initialize":
            return _jsonrpc_result({
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "ironledger", "version": __version__},
            }, req_id)
        elif method == "ping":
            return _jsonrpc_result({}, req_id)
        elif method == "tools/list":
            return _jsonrpc_result({"tools": list_tools()}, req_id)
        elif method == "tools/call":
            params = data.get("params")
            if not isinstance(params, dict):
                return _jsonrpc_error(-32602, "Invalid params: must be object", req_id)
            tool_name = params.get("name")
            tool_args = params.get("arguments")
            if not isinstance(tool_name, str):
                return _jsonrpc_error(-32602, "Invalid params: missing tool name", req_id)
            res = call_tool(
                tool_name,
                tool_args,
                ledger_dir=ledger_dir,
                projection_dir=projection_dir,
                db=db,
            )
            return _jsonrpc_result(res, req_id)
        else:
            return _jsonrpc_error(-32601, f"Method not found: {method}", req_id)
    except Exception as exc:
        _logger.error("internal error during handle_message: %s", type(exc).__name__)
        return _jsonrpc_error(-32603, "internal error", req_id)
