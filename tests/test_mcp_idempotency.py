import asyncio
from types import SimpleNamespace

import pytest
from mcp.shared.exceptions import MCPError

from ironledger.mcp.idempotency import (
    FAILED_RETRY_CAP,
    IdempotencyMiddleware,
    Ledger,
    LedgerRow,
    canonical_fingerprint,
)

PRINCIPAL = "local:ironledger"
REQUEST_ID = "6f1e2c0a-7b34-4d5e-9a10-2c8b7d6e5f40"


def _ctx(name: str, arguments: dict | None, request_id: str | None) -> SimpleNamespace:
    meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientInfo": {"name": "probe", "version": "0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    if request_id is not None:
        meta["dev.toolforge/clientRequestId"] = request_id
    return SimpleNamespace(
        method="tools/call",
        params={"name": name, "arguments": arguments or {}, "_meta": meta},
    )


def _middleware() -> tuple[IdempotencyMiddleware, Ledger, dict]:
    ledger = Ledger()
    mutations: set[str] = {"mark_request"}
    seen = {"calls": 0}

    async def call_next(_ctx):
        seen["calls"] += 1
        return {
            "content": [{"type": "text", "text": "alpha"}],
            "structuredContent": {"label": "alpha", "executions": seen["calls"]},
            "isError": False,
        }

    return IdempotencyMiddleware(mutations, ledger, PRINCIPAL), ledger, {"call_next": call_next, "seen": seen}


def test_missing_client_request_id_inserts_nothing():
    middleware, ledger, bag = _middleware()
    called = {"n": 0}

    async def call_next(_ctx):
        called["n"] += 1
        return {}

    with pytest.raises(MCPError) as caught:
        asyncio.run(middleware(_ctx("mark_request", {"label": "alpha"}, None), call_next))
    assert caught.value.data["reason"] == "missing_client_request_id"
    assert ledger.rows == {}
    assert called["n"] == 0


def test_completed_row_owner_is_the_fixed_principal():
    middleware, ledger, bag = _middleware()
    body = asyncio.run(middleware(_ctx("mark_request", {"label": "alpha"}, REQUEST_ID), bag["call_next"]))
    key = f"idempotency:v1:{PRINCIPAL}:{REQUEST_ID}"
    row = ledger.rows[key]
    assert row.owner == PRINCIPAL
    assert row.status == "COMPLETED"
    assert body["structuredContent"]["owner"] == PRINCIPAL
    assert body["structuredContent"]["executions"] == 1
    assert bag["seen"]["calls"] == 1


def test_same_id_returns_the_stored_body():
    middleware, ledger, bag = _middleware()
    ctx = _ctx("mark_request", {"label": "alpha"}, REQUEST_ID)
    first = asyncio.run(middleware(ctx, bag["call_next"]))
    second = asyncio.run(middleware(ctx, bag["call_next"]))
    assert second == first
    assert bag["seen"]["calls"] == 1
    assert second["structuredContent"]["executions"] == 1


def test_same_id_different_label_does_not_run():
    middleware, _ledger, bag = _middleware()
    asyncio.run(middleware(_ctx("mark_request", {"label": "alpha"}, REQUEST_ID), bag["call_next"]))
    with pytest.raises(MCPError) as caught:
        asyncio.run(middleware(_ctx("mark_request", {"label": "beta"}, REQUEST_ID), bag["call_next"]))
    assert caught.value.data["reason"] == "idempotency_fingerprint_mismatch"
    assert bag["seen"]["calls"] == 1


def test_read_without_client_request_id_runs():
    middleware, ledger, _bag = _middleware()
    called = {"n": 0}

    async def call_next(_ctx):
        called["n"] += 1
        return {"ok": True}

    ctx = _ctx("projection_status", {}, None)
    assert asyncio.run(middleware(ctx, call_next)) == {"ok": True}
    assert called["n"] == 1
    assert ledger.rows == {}


def test_in_progress_row_does_not_run():
    middleware, ledger, bag = _middleware()
    key = f"idempotency:v1:{PRINCIPAL}:{REQUEST_ID}"
    fingerprint = canonical_fingerprint("tools/call", "mark_request", {"label": "alpha"})
    ledger.rows[key] = LedgerRow(status="IN_PROGRESS", fingerprint=fingerprint, owner=PRINCIPAL)
    with pytest.raises(MCPError) as caught:
        asyncio.run(middleware(_ctx("mark_request", {"label": "alpha"}, REQUEST_ID), bag["call_next"]))
    assert caught.value.data["reason"] == "idempotency_in_progress"
    assert caught.value.data["retryAfterSeconds"] == 5
    assert bag["seen"]["calls"] == 0
    assert ledger.rows[key].status == "IN_PROGRESS"


def test_runtime_error_is_retryable_once():
    middleware, ledger, _bag = _middleware()
    state = {"calls": 0}

    async def call_next(_ctx):
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("boom")
        return {
            "structuredContent": {"label": "alpha", "executions": state["calls"]},
            "isError": False,
        }

    ctx = _ctx("mark_request", {"label": "alpha"}, REQUEST_ID)
    with pytest.raises(RuntimeError):
        asyncio.run(middleware(ctx, call_next))
    key = f"idempotency:v1:{PRINCIPAL}:{REQUEST_ID}"
    assert ledger.rows[key].status == "FAILED"
    body = asyncio.run(middleware(ctx, call_next))
    assert state["calls"] == 2
    assert ledger.rows[key].status == "COMPLETED"
    assert body["structuredContent"]["executions"] == 2
    assert ledger.rows[key].retries == 1
    assert FAILED_RETRY_CAP == 3
