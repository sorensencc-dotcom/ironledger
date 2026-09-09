import pytest
from ironledger.mcp.bind import assert_loopback
from ironledger.mcp.errors import McpBindError


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_loopback_ok(host):
    assert assert_loopback(host) is None


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "localhost", "192.168.1.1", "127.0.0.2", ""])
def test_non_loopback_refused(host):
    with pytest.raises(McpBindError) as ei:
        assert_loopback(host)
    assert host in str(ei.value) or "127.0.0.1" in str(ei.value)
