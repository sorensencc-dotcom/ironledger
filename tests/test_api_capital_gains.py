import sqlite3

from ironledger.db.migrations import migrate_governed
from ironledger.web.routers.analytics import get_capital_gains, get_open_lots


def test_capital_gains_unknown_ledger_is_not_found():
    conn = sqlite3.connect(":memory:")
    migrate_governed(conn)
    try:
        get_capital_gains(ledger_id="missing", conn=conn)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 404
    else:
        raise AssertionError("unknown ledger must return 404")


def test_lots_endpoint_returns_empty_known_ledger():
    conn = sqlite3.connect(":memory:")
    migrate_governed(conn)
    assert get_open_lots(ledger_id="default", conn=conn) == []
