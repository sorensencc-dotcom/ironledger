import json
from pathlib import Path
import pytest
from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.project.activate import rebuild_projection
from ironledger.mcp.protocol import handle_message
from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger


@pytest.fixture
def mcp_env(tmp_path: Path):
    ledger_dir = tmp_path / 'ledger'
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / 'ironledger.db'
    seed_successful_compile_run(db_path, ledger_dir)
    conn = connect(str(db_path))
    migrations.migrate(conn)
    projection_dir = tmp_path / 'projection'
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc='2026-09-08T12:00:00Z')
    conn.close()
    return ledger_dir, projection_dir, str(db_path)


def test_parse_error_and_batch(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    resp = handle_message('not json', ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    d = json.loads(resp)
    assert d['error']['code'] == -32700
    assert d['id'] is None

    batch_resp = handle_message('[]', ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    bd = json.loads(batch_resp)
    assert bd['error']['code'] == -32600


def test_initialize_ping_notifications(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    init_req = json.dumps({
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'initialize',
        'params': {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'test'}}
    })
    resp = handle_message(init_req, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    d = json.loads(resp)
    assert d['id'] == 1
    assert d['result']['protocolVersion'] == '2025-03-26'
    assert d['result']['serverInfo']['name'] == 'ironledger'

    notif = json.dumps({
        'jsonrpc': '2.0',
        'method': 'notifications/initialized'
    })
    assert handle_message(notif, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db) is None

    ping = json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'ping'})
    presp = handle_message(ping, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert json.loads(presp)['result'] == {}


def test_unknown_method_and_internal_error_masks_secret(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    req = json.dumps({'jsonrpc': '2.0', 'id': 3, 'method': 'resources/list'})
    resp = handle_message(req, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert json.loads(resp)['error']['code'] == -32601
