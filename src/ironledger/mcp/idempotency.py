"""Process-local idempotency ledger for the loopback daemon.

The key is ``idempotency:v1:{owner}:{client_request_id}``. On this socket
the owner is the fixed principal. Tasks and the in-progress TTL are not
in this module. A crash leaves ``FAILED`` so the same fingerprint can
run again, up to three re-entries.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS

CLIENT_REQUEST_ID = "dev.toolforge/clientRequestId"
RETRY_AFTER_SECONDS = 5
FAILED_RETRY_CAP = 3


@dataclass
class LedgerRow:
    status: str
    fingerprint: str
    owner: str
    body: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    retries: int = 0
    retryable: bool = False


class Ledger:
    def __init__(self) -> None:
        self.rows: dict[str, LedgerRow] = {}
        self._lock: asyncio.Lock | None = None

    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock


def canonical_fingerprint(method: str, name: str, arguments: Any) -> str:
    payload = {"method": method, "name": name, "arguments": arguments}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def mutation(mutations: set[str]):
    def wrap(fn):
        mutations.add(fn.__name__)
        return fn

    return wrap


def _reject(reason: str, message: str, **extra: Any) -> MCPError:
    return MCPError(INVALID_PARAMS, message, {"reason": reason, **extra})


def _as_body(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        dumped = result.model_dump(by_alias=True, mode="json", exclude_none=True)
        if isinstance(dumped, dict):
            return dumped
    if isinstance(result, dict):
        return json.loads(json.dumps(result))
    raise TypeError(type(result).__name__)


class IdempotencyMiddleware:
    def __init__(self, mutations: set[str], ledger: Ledger, fixed_principal: str) -> None:
        self.mutations = mutations
        self.ledger = ledger
        self.fixed_principal = fixed_principal

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        params = ctx.params if isinstance(ctx.params, dict) else {}
        name = params.get("name")
        if ctx.method != "tools/call" or name not in self.mutations:
            return await call_next(ctx)
        return await self._mutate(ctx, params, str(name), call_next)

    async def _mutate(self, ctx: Any, params: dict[str, Any], name: str, call_next: Any) -> Any:
        meta = params.get("_meta")
        meta = meta if isinstance(meta, dict) else {}
        client_request_id = meta.get(CLIENT_REQUEST_ID)
        if not isinstance(client_request_id, str) or not client_request_id:
            raise _reject("missing_client_request_id", "mutation requires dev.toolforge/clientRequestId")
        subject = self.fixed_principal
        fingerprint = canonical_fingerprint(ctx.method, name, params.get("arguments"))
        key = f"idempotency:v1:{subject}:{client_request_id}"
        async with self.ledger.lock():
            cached = self._read_or_insert(key, fingerprint, subject)
            if cached is not None:
                return cached
        try:
            result = await call_next(ctx)
        except MCPError as exc:
            self._fail(key, exc)
            raise
        except BaseException:
            self._fail(key, None)
            raise
        async with self.ledger.lock():
            return self._commit(key, result)

    def _fail(self, key: str, exc: MCPError | None) -> None:
        row = self.ledger.rows[key]
        if exc is not None:
            row.status = "COMPLETED"
            row.retryable = False
            row.body = None
            row.error = {"code": exc.code, "message": exc.message, "data": exc.data}
            return
        row.status = "FAILED"
        row.retryable = True
        row.body = None
        row.error = None

    def _read_or_insert(self, key: str, fingerprint: str, subject: str) -> Any | None:
        row = self.ledger.rows.get(key)
        if row is None:
            self.ledger.rows[key] = LedgerRow(status="IN_PROGRESS", fingerprint=fingerprint, owner=subject)
            return None
        if row.fingerprint != fingerprint:
            raise _reject("idempotency_fingerprint_mismatch", "client request id was reused with a different call")
        if row.status == "COMPLETED":
            if row.error is not None:
                raise MCPError(row.error["code"], row.error["message"], row.error["data"])
            return json.loads(json.dumps(row.body))
        if row.status == "IN_PROGRESS":
            raise _reject(
                "idempotency_in_progress",
                "this client request id is still running",
                retryAfterSeconds=RETRY_AFTER_SECONDS,
            )
        if row.status == "FAILED" and row.retryable and row.retries < FAILED_RETRY_CAP:
            row.status = "IN_PROGRESS"
            row.body = None
            row.retries += 1
            return None
        exhausted = {
            "code": INVALID_PARAMS,
            "message": "retry cap exhausted",
            "data": {"reason": "idempotency_retry_exhausted"},
        }
        row.status = "COMPLETED"
        row.retryable = False
        row.error = exhausted
        row.body = None
        raise MCPError(exhausted["code"], exhausted["message"], exhausted["data"])

    def _commit(self, key: str, result: Any) -> dict[str, Any]:
        row = self.ledger.rows[key]
        body = _as_body(result)
        structured = body.get("structuredContent")
        if isinstance(structured, dict):
            structured = dict(structured)
        else:
            structured = {} if structured is None else {"value": structured}
        structured["owner"] = row.owner
        body["structuredContent"] = structured
        stored = json.loads(json.dumps(body))
        row.status = "COMPLETED"
        row.retryable = False
        row.body = stored
        row.error = None
        return stored
