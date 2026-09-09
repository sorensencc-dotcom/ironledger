"""Loopback bind policy for IronLedger MCP."""
from ironledger.mcp.errors import McpBindError, format_bind_refused

ALLOWED = frozenset({"127.0.0.1", "::1"})

def assert_loopback(host: str) -> None:
    """Assert that the given host is an allowed loopback literal."""
    if host not in ALLOWED:
        raise McpBindError(format_bind_refused(host))
