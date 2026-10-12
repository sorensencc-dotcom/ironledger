"""Stateless loopback daemon for gate 2.

This module binds 127.0.0.1:8766 with mcp 2.x ``stateless_http=True``.
``serve_http`` stays the hand-rolled parser and is not this process.
The process opens ``ironledger.daemon-copy.db`` only. It refuses the
repo-root ``ironledger.db`` and the container path
``/var/lib/ironledger/ironledger.db``.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp_types import CallToolResult, TextContent

from ironledger.db.connection import connect
from ironledger.db.migrations import migrate
from ironledger.mcp.bind import assert_loopback
from ironledger.mcp.tools import call_tool

log = logging.getLogger("ironledger.mcp.loopback")

FIXED_PRINCIPAL = "local:ironledger"
BIND_HOST = "127.0.0.1"
BIND_PORT = 8766
COPY_NAME = "ironledger.daemon-copy.db"
CONTAINER_DATABASE = "/var/lib/ironledger/ironledger.db"


class LiveDatabaseRefused(RuntimeError):
    """The daemon was pointed at a live financial database."""


@dataclass(frozen=True)
class LoopbackCopy:
    """The only database, ledger dir, and projection dir this process may open."""

    database: Path
    ledger_dir: Path
    projection_dir: Path
    principal: str = FIXED_PRINCIPAL


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def live_databases(repo: Path) -> frozenset[Path]:
    repo = Path(repo).resolve()
    return frozenset(
        {
            (repo / "ironledger.db").resolve(),
            Path(CONTAINER_DATABASE),
        }
    )


def assert_not_live(path: Path, repo: Path) -> Path:
    resolved = Path(path).resolve()
    if resolved in live_databases(repo) or resolved.as_posix().endswith(CONTAINER_DATABASE):
        raise LiveDatabaseRefused(str(resolved))
    return resolved


def prepare_copy(root: Path, repo: Path | None = None) -> LoopbackCopy:
    """Create or reuse a schema copy under ``root``. Never opens a live database."""
    repo = Path(repo) if repo is not None else repo_root()
    root = Path(root)
    database = assert_not_live(root / COPY_NAME, repo)
    ledger_dir = root / "ledger"
    projection_dir = root / "projection"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    projection_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(database)
    try:
        migrate(conn)
    finally:
        conn.close()
    return LoopbackCopy(database=database, ledger_dir=ledger_dir, projection_dir=projection_dir)


def checkpoint_copy(database: Path) -> None:
    conn = connect(database)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _tool_text(name: str, arguments: dict, copy: LoopbackCopy) -> str:
    result = call_tool(
        name,
        arguments,
        ledger_dir=copy.ledger_dir,
        projection_dir=copy.projection_dir,
        db=str(copy.database),
    )
    content = result.get("content") or []
    text = content[0].get("text", "") if content else ""
    if result.get("isError"):
        raise RuntimeError(text)
    return text


def build_server(copy: LoopbackCopy):
    from mcp.server import MCPServer

    from ironledger.mcp.idempotency import IdempotencyMiddleware, Ledger, mutation

    mutations: set[str] = set()
    ledger = Ledger()
    mark = mutation(mutations)
    executions = {"mark_request": 0}

    @asynccontextmanager
    async def lifespan(_server):
        log.info("subject %s opened %s", copy.principal, copy.database)
        try:
            yield {"database": str(copy.database), "principal": copy.principal}
        finally:
            checkpoint_copy(copy.database)
            log.info("checkpointed %s", copy.database)

    server = MCPServer(
        "ironledger",
        instructions="Loopback finance tools on a SQLite copy. Subject local:ironledger.",
        lifespan=lifespan,
        middleware=[IdempotencyMiddleware(mutations, ledger, copy.principal)],
    )

    @server.tool(description="Record one loopback marker. A retry returns the stored row.")
    @mark
    def mark_request(label: str) -> CallToolResult:
        executions["mark_request"] += 1
        count = executions["mark_request"]
        return CallToolResult(
            content=[TextContent(type="text", text=label)],
            structured_content={"label": label, "executions": count},
            is_error=False,
        )

    @server.tool(description="Return freshness of the disposable projection.")
    def projection_status() -> str:
        return _tool_text("projection_status", {}, copy)

    @server.tool(description="Full-text search across ledger entries and postings.")
    def search(query: str, limit: int = 50, offset: int = 0) -> str:
        return _tool_text("search", {"query": query, "limit": limit, "offset": offset}, copy)

    @server.tool(description="Return ledger account balances by currency.")
    def balances() -> str:
        return _tool_text("balances", {}, copy)

    return server


def _stop_on_stdin(server) -> None:
    try:
        sys.stdin.buffer.read()
    finally:
        server.should_exit = True


def serve(copy: LoopbackCopy, *, host: str = BIND_HOST, port: int = BIND_PORT) -> None:
    import uvicorn
    from importlib.metadata import version

    assert_loopback(host)
    assert_not_live(copy.database, repo_root())
    mcp_version = version("mcp")
    if not mcp_version.startswith("2."):
        raise SystemExit(f"mcp {mcp_version} cannot run this daemon. Use mcp 2.x.")

    app = build_server(copy).streamable_http_app(stateless_http=True, host=host)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    if os.environ.get("IRONLEDGER_MCP_STOP_ON_STDIN") == "1":
        threading.Thread(target=_stop_on_stdin, args=(server,), daemon=True).start()

    banner = (
        f"ironledger daemon http://{host}:{port}/mcp "
        f"subject {copy.principal} opened {copy.database} mcp {mcp_version}\n"
    )
    sys.stdout.write(banner)
    sys.stdout.flush()
    ready = copy.database.with_suffix(".ready")
    ready.write_text(f"{copy.principal}\n{copy.database}\n", encoding="utf-8")
    try:
        server.run()
    finally:
        ready.unlink(missing_ok=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    root = Path(os.environ.get("IRONLEDGER_MCP_COPY_ROOT", repo_root() / ".mcp-loopback"))
    copy = prepare_copy(root)
    serve(copy)


if __name__ == "__main__":
    main()
