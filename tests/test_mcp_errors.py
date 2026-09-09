from ironledger.mcp.errors import (
    McpAuthError,
    McpBindError,
    McpError,
    McpProtocolError,
    format_auth_denied,
    format_bind_refused,
    format_protocol_error,
)


def test_hierarchy():
    assert issubclass(McpBindError, McpError)
    assert issubclass(McpAuthError, McpError)
    assert issubclass(McpProtocolError, McpError)


def test_format_bind_refused_names_host_and_loopback():
    msg = format_bind_refused('0.0.0.0')
    assert '0.0.0.0' in msg
    assert '127.0.0.1' in msg
    assert '::1' in msg


def test_format_auth_denied_has_no_secret():
    msg = format_auth_denied()
    assert 'bearer' in msg.lower() or 'Authorization' in msg
    for banned in ('token=', 'Bearer abc', '.mcp-token'):
        assert banned not in msg
