import json, socket, threading, urllib.request, urllib.error, pytest
from pathlib import Path
from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.project.activate import rebuild_projection
from ironledger.mcp.http import serve_http
from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger

@pytest.fixture
def http_server(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / "ironledger.db"
    seed_successful_compile_run(db_path, ledger_dir)
    conn = connect(str(db_path))
    migrations.migrate(conn)
    projection_dir = tmp_path / "projection"
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    conn.close()

    server = serve_http(
        host="127.0.0.1",
        port=0,
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=str(db_path),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield f"http://127.0.0.1:{port}/mcp", server.token, str(db_path)
    server.shutdown()
    server.server_close()

def test_http_401_without_token(http_server):
    url, token, db = http_server
    req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req)
    assert ei.value.code == 401
    assert "Bearer" in ei.value.headers.get("WWW-Authenticate", "")

def test_http_valid_token_and_403_origin(http_server):
    url, token, db = http_server
    init_data = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=init_data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        d = json.loads(resp.read().decode("utf-8"))
        assert d["result"] == {}

    bad_req = urllib.request.Request(
        url,
        data=init_data,
        headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.example"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(bad_req)
    assert ei.value.code == 403

def test_http_methods(http_server):
    url, token, db = http_server
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(url)
    assert ei.value.code == 405
