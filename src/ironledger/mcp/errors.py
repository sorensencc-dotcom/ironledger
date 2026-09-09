"""MCP error types and formatters."""


class McpError(Exception):
    """Base exception for all IronLedger MCP errors."""


class McpBindError(McpError):
    """Raised when bind host is refused."""


class McpAuthError(McpError):
    """Raised when MCP Authentication fails."""


class McpProtocolError(McpError):
    """Raised on JSON-RPC or MCP protocol violations."""


def format_bind_refused(host: str) -> str:
    """Format bind refusal with problem, cause, and allowed values."""
    return (
        f"Bind host '{host}' was refused. "
        "IronLedger MCP allows loopback addresses only (127.0.0.1 or ::1). "
        "To fix, specify --bind 127.0.0.1 or --bind ::1 with --port."
    )


def format_auth_denied() -> str:
    """Format authentication error without leaking secrets or tokens."""
    return (
        "Authentication denied. "
        "A valid HTTP Bearer token is required. "
        "To fix, supply 'Authorization: Bearer <token>' in request headers."
    )


def format_protocol_error(reason: str) -> str:
    """Format protocol violation error."""
    return f"Protocol error: {reason}"
