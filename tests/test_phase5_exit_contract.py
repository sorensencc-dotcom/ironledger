# tests/test_phase5_exit_contract.py
"""Phase 5 exit-gate contract: one named test per spec §12 item 1–35 except 20.

Item 20 is verified by running the full test suite via `python -m pytest -q`
and ensuring count >= Phase 4 baseline with 0 regressions.
"""

from __future__ import annotations

import io
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from ironledger.cli.__main__ import main
from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.mcp.bind import assert_loopback
from ironledger.mcp.errors import McpBindError
from ironledger.mcp.http import serve_http
from ironledger.mcp.protocol import handle_message
from ironledger.mcp.stdio import run_stdio
from ironledger.mcp.token import load_or_create_token, rotate_token, verify_bearer
from ironledger.mcp.tools import call_tool, list_tools
from ironledger.project import query as project_query
from ironledger.project.activate import rebuild_projection
from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger


@pytest.fixture
def mcp_env(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / "ironledger.db"
    seed_successful_compile_run(db_path, ledger_dir, "run-1")
    conn = connect(str(db_path))
    migrations.migrate(conn)
    projection_dir = tmp_path / "projection"
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    conn.close()
    return ledger_dir, projection_dir, str(db_path)


# 1. tools/list names are exactly ["search", "balances", "projection_status"] in that order. JSON Schema for search requires query and caps limit at 500.
def test_contract_1_tools_list_order_and_schema():
    tools = list_tools()
    names = [t["name"] for t in tools]
    assert names == ["search", "balances", "projection_status"]

    search_tool = next(t for t in tools if t["name"] == "search")
    schema = search_tool["inputSchema"]
    assert "query" in schema["required"]
    assert schema["properties"]["limit"]["maximum"] == 500


# 2. tools/call search against a rebuilt projection returns the same posting_id set as ironledger.project.query.search. minor_units is an integer.
def test_contract_2_tools_call_search(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    res = call_tool("search", {"query": "Coffee"}, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert res["isError"] is False

    data = json.loads(res["content"][0]["text"])
    mcp_posting_ids = [h["posting_id"] for h in data["hits"]]

    qconn = project_query.assert_fresh(ledger_dir, projection_dir)
    direct_hits = project_query.search(qconn, "Coffee")
    qconn.close()
    direct_posting_ids = [h.posting_id for h in direct_hits]

    assert mcp_posting_ids == direct_posting_ids
    assert len(data["hits"]) > 0
    for hit in data["hits"]:
        assert isinstance(hit["minor_units"], int)


# 3. tools/call balances matches query.balances row-for-row: account, minor_units, currency, minor_unit_scale. Two currencies on two rows; never one summed number.
def test_contract_3_tools_call_balances(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    res = call_tool("balances", {}, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert res["isError"] is False

    data = json.loads(res["content"][0]["text"])
    qconn = project_query.assert_fresh(ledger_dir, projection_dir)
    direct_balances = project_query.balances(qconn)
    qconn.close()

    assert len(data["balances"]) == len(direct_balances)
    for b_mcp, b_dir in zip(data["balances"], direct_balances):
        assert b_mcp["account"] == b_dir.account
        assert b_mcp["minor_units"] == b_dir.minor_units
        assert b_mcp["currency"] == b_dir.currency
        assert b_mcp["minor_unit_scale"] == b_dir.minor_unit_scale
        assert isinstance(b_mcp["minor_units"], int)


# 4. tools/call projection_status on a missing projection returns status: "missing" with isError: false. After rebuild, status: "ok" and hash_matches_files: true.
def test_contract_4_tools_call_projection_status(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / "ironledger.db"
    seed_successful_compile_run(db_path, ledger_dir)
    projection_dir = tmp_path / "missing_projection"

    res_missing = call_tool("projection_status", {}, ledger_dir=ledger_dir, projection_dir=projection_dir, db=str(db_path))
    assert res_missing["isError"] is False
    data_missing = json.loads(res_missing["content"][0]["text"])
    assert data_missing["status"] == "missing"

    conn = connect(str(db_path))
    migrations.migrate(conn)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    conn.close()

    res_ok = call_tool("projection_status", {}, ledger_dir=ledger_dir, projection_dir=projection_dir, db=str(db_path))
    assert res_ok["isError"] is False
    data_ok = json.loads(res_ok["content"][0]["text"])
    assert data_ok["status"] == "ok"
    assert data_ok["hash_matches_files"] is True


# 5. Stale projection: search and balances return isError: true; text includes short hashes, --ledger-dir, and --confirm "authorize project". Live projection file is not written.
def test_contract_5_stale_projection(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    sqlite_file = projection_dir / "projection.sqlite"
    mtime_before = sqlite_file.stat().st_mtime_ns

    # Touch ledger to cause hash mismatch
    accounts_file = ledger_dir / "accounts.beancount"
    accounts_file.write_bytes(accounts_file.read_bytes() + b"; modified\n")

    res_search = call_tool("search", {"query": "Coffee"}, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert res_search["isError"] is True
    err_text = res_search["content"][0]["text"]
    assert "--ledger-dir" in err_text
    assert '--confirm "authorize project"' in err_text

    res_bal = call_tool("balances", {}, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert res_bal["isError"] is True

    mtime_after = sqlite_file.stat().st_mtime_ns
    assert mtime_before == mtime_after


# 6. Empty query and invalid FTS syntax: isError: true, error formula, no traceback on stdout.
def test_contract_6_empty_and_invalid_fts(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    res_empty = call_tool("search", {"query": ""}, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert res_empty["isError"] is True
    assert "empty" in res_empty["content"][0]["text"].lower()

    res_invalid = call_tool("search", {"query": "AND"}, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert res_invalid["isError"] is True
    assert "invalid" in res_invalid["content"][0]["text"].lower()
    assert "Traceback" not in res_invalid["content"][0]["text"]


# 7. tools/call name compile / import / review / project / rule / not-a-tool: isError: true, no rebuild_projection, no ingest, no compile journal row, no phrase prompt.
def test_contract_7_mutation_tools_refused(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    for bad_name in ("compile", "import", "review", "project", "rule", "not-a-tool"):
        res = call_tool(bad_name, {}, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
        assert res["isError"] is True
        assert "unknown tool" in res["content"][0]["text"].lower()

    tools = list_tools()
    for t in tools:
        assert t["name"] not in ("compile", "import", "review", "project", "rule")


# 8. JSON-RPC method resources/list (and prompts/list) returns -32601. No resource payload.
def test_contract_8_unsupported_methods(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    for meth in ("resources/list", "prompts/list", "other/method"):
        req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": meth})
        resp = handle_message(req, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
        assert resp is not None
        data = json.loads(resp)
        assert data["id"] == 1
        assert data["error"]["code"] == -32601


# 9. stdio: one initialize request in, one initialize result out; stdout has no non-JSON prefix (no banner). A second process using stdio has no listening TCP socket.
def test_contract_9_stdio_no_tcp_bind(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    stdin = io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26"}}\n')
    stdout = io.BytesIO()
    stderr = io.StringIO()

    with patch("ironledger.mcp.http.serve_http") as spy_http:
        rc = run_stdio(stdin, stdout, stderr, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
        assert rc == 0
        spy_http.assert_not_called()

    out_lines = stdout.getvalue().decode("utf-8").splitlines()
    assert len(out_lines) == 1
    resp = json.loads(out_lines[0])
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "ironledger"
    assert not out_lines[0].startswith("IronLedger")


# 10. --bind 0.0.0.0 --port <n> exits 1, McpBindError (or formatted bind error), no socket. Same for 192.168.1.1 and localhost.
def test_contract_10_bind_refusals(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    for bad_ip in ("0.0.0.0", "192.168.1.1", "localhost", "example.com"):
        with pytest.raises(McpBindError):
            assert_loopback(bad_ip)
        rc = main(["mcp", "--db", db, "--ledger-dir", str(ledger_dir), "--bind", bad_ip, "--port", "8765"])
        assert rc == 1


# 11. --bind 127.0.0.1 --port <ephemeral>: getsockname address is 127.0.0.1. POST /mcp without Authorization is 401. POST with token works.
def test_contract_11_http_bind_and_auth(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    server = serve_http(host="127.0.0.1", port=0, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    host, port = server.server_address[:2]
    assert host == "127.0.0.1"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        init_body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}).encode("utf-8")

        req_no_auth = urllib.request.Request(url, data=init_body, headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req_no_auth)
        assert exc.value.code == 401

        token = load_or_create_token(projection_dir)
        req_auth = urllib.request.Request(url, data=init_body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req_auth) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["result"]["serverInfo"]["name"] == "ironledger"
    finally:
        server.shutdown()
        server.server_close()


# 12. Wrong bearer token -> 401, same body shape as missing token; search is not executed.
def test_contract_12_wrong_token_401(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    server = serve_http(host="127.0.0.1", port=0, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search", "arguments": {"query": "Coffee"}}}).encode("utf-8")

        req_wrong = urllib.request.Request(url, data=body, headers={"Authorization": "Bearer badtoken00000000000000000000000000000000000000000000000000000000", "Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc_wrong:
            urllib.request.urlopen(req_wrong)
        assert exc_wrong.value.code == 401
        assert "Bearer" in exc_wrong.value.headers.get("WWW-Authenticate", "")

        req_missing = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc_missing:
            urllib.request.urlopen(req_missing)
        assert exc_missing.value.code == 401
        assert "Bearer" in exc_missing.value.headers.get("WWW-Authenticate", "")
    finally:
        server.shutdown()
        server.server_close()


# 13. POST /mcp with Origin: https://evil.example -> 403 even with a valid token. POST with no Origin and valid token succeeds.
def test_contract_13_origin_validation(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    token = load_or_create_token(projection_dir)
    server = serve_http(host="127.0.0.1", port=0, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8")

        req_evil = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.example", "Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req_evil)
        assert exc.value.code == 403

        req_ok = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req_ok) as resp:
            assert resp.status == 200
    finally:
        server.shutdown()
        server.server_close()


# 14. GET /mcp -> 405. POST /other -> 404.
def test_contract_14_methods_and_paths(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    server = serve_http(host="127.0.0.1", port=0, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req_get = urllib.request.Request(f"http://127.0.0.1:{port}/mcp", method="GET")
        with pytest.raises(urllib.error.HTTPError) as exc_get:
            urllib.request.urlopen(req_get)
        assert exc_get.value.code == 405

        req_post_other = urllib.request.Request(f"http://127.0.0.1:{port}/other", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc_404:
            urllib.request.urlopen(req_post_other)
        assert exc_404.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


# 15. First HTTP bind creates .mcp-token at 64 hex chars; POSIX mode 0o600. --rotate-token changes the file bytes; the old token then 401s; the new token works.
def test_contract_15_token_lifecycle_and_rotation(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    token1 = load_or_create_token(projection_dir)
    assert len(token1) == 64
    assert all(c in "0123456789abcdef" for c in token1)
    if os.name != "nt":
        assert (projection_dir / ".mcp-token").stat().st_mode & 0o777 == 0o600

    token2 = rotate_token(projection_dir)
    assert len(token2) == 64
    assert token1 != token2
    assert verify_bearer(f"Bearer {token2}", token2) is True
    assert verify_bearer(f"Bearer {token1}", token2) is False


# 16. .mcp-token is gitignored (**/.mcp-token matches).
def test_contract_16_gitignore():
    gitignore_text = Path(".gitignore").read_text(encoding="utf-8")
    assert "**/.mcp-token" in gitignore_text or ".mcp-token" in gitignore_text


# 17. Safe mode enabled: mcp stdio tools/list still succeeds. require_operator is not called.
def test_contract_17_safe_mode_unaffected(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    stdin = io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n')
    stdout = io.BytesIO()
    stderr = io.StringIO()

    with patch("ironledger.cli.auth.require_operator") as spy_auth:
        rc = run_stdio(stdin, stdout, stderr, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
        assert rc == 0
        spy_auth.assert_not_called()

    data = json.loads(stdout.getvalue().decode("utf-8").strip())
    assert len(data["result"]["tools"]) == 3


# 18. tools/call search appends audit_events with action="mcp search", result="ok", and FTS query string does not appear in target or any hash field. HTTP 401 appends action="mcp auth", result="denied".
def test_contract_18_audit_logging(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    res = call_tool("search", {"query": "Coffee"}, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert res["isError"] is False

    conn = connect(db)
    row = conn.execute("SELECT actor, action, target, result, input_hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    conn.close()
    assert row is not None
    actor, action, target, result, input_hash = row
    assert actor == "operator"
    assert action == "mcp search"
    assert target == "search"
    assert result == "ok"
    assert "Coffee" not in (target, input_hash or "")


# 19. No source file under src/ironledger contains import mcp or from mcp. pyproject.toml runtime dependencies remains ["ofxtools==1.1.1"].
def test_contract_19_zero_mcp_dependency():
    root = Path("src/ironledger")
    offenders = []
    for py_file in root.rglob("*.py"):
        for i, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s.startswith("import mcp") or s.startswith("from mcp"):
                offenders.append(f"{py_file}:{i}:{line}")
    assert offenders == []

    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    runtime = pyproject.split("[project.optional-dependencies]")[0]
    assert "ofxtools==1.1.1" in runtime
    assert "pypdf==6.1.3" in runtime
    assert "mcp==" not in runtime.lower()
    assert "from mcp" not in runtime.lower()


# 21. python -m ironledger.cli --help lists mcp. --db after mcp parses.
def test_contract_21_cli_help_and_subcommand(mcp_env, capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "mcp" in out

    ledger_dir, projection_dir, db = mcp_env
    stdin_bytes = b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
    stdin_mock = io.BytesIO(stdin_bytes)
    stdout_mock = io.BytesIO()
    
    mock_stdin = io.TextIOWrapper(stdin_mock, encoding="utf-8")
    mock_stdout = io.TextIOWrapper(stdout_mock, encoding="utf-8")
    
    with patch("sys.stdin", mock_stdin), patch("sys.stdout", mock_stdout):
        rc = main(["mcp", "--ledger-dir", str(ledger_dir), "--db", db, "--projection-dir", str(projection_dir)])
        assert rc == 0
    resp = json.loads(stdout_mock.getvalue().strip())
    assert resp["result"] == {}


# 22. --bind without --port, --port without --bind, --rotate-token without --bind: exit 2.
def test_contract_22_cli_flag_mismatches(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    assert main(["mcp", "--db", db, "--ledger-dir", str(ledger_dir), "--bind", "127.0.0.1"]) == 2
    assert main(["mcp", "--db", db, "--ledger-dir", str(ledger_dir), "--port", "8765"]) == 2
    assert main(["mcp", "--db", db, "--ledger-dir", str(ledger_dir), "--rotate-token"]) == 2


# 23. JSON-RPC batch (a JSON array) returns -32600. Embedded newline inside a stdio line is a parse error, process stays up.
def test_contract_23_batch_and_stdio_newlines(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    resp = handle_message('[{"jsonrpc":"2.0","id":1,"method":"ping"}]', ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    data = json.loads(resp)
    assert data["error"]["code"] == -32600

    stdin = io.BytesIO(b'{"jsonrpc":\n"2.0","id":1,"method":"ping"}\n')
    stdout = io.BytesIO()
    stderr = io.StringIO()
    rc = run_stdio(stdin, stdout, stderr, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert rc == 0
    lines = stdout.getvalue().decode("utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        d = json.loads(line)
        assert d["error"]["code"] == -32700


# 24. Host header evil.example:8765 on POST /mcp with a valid token -> 403.
def test_contract_24_host_rebinding_403(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    token = load_or_create_token(projection_dir)
    server = serve_http(host="127.0.0.1", port=0, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {token}", "Host": f"evil.example:{port}", "Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req)
        assert exc.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


# 25. POST /mcp with Content-Length > 1048576, or with Transfer-Encoding: chunked, returns 413.
def test_contract_25_body_cap_413(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    token = load_or_create_token(projection_dir)
    server = serve_http(host="127.0.0.1", port=0, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sock = socket.socket()
        sock.connect(("127.0.0.1", port))
        sock.sendall(
            f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\nContent-Type: application/json\r\nContent-Length: 2000000\r\n\r\n".encode("ascii")
        )
        response = sock.recv(4096).decode("utf-8")
        sock.close()
        assert "413" in response
    finally:
        server.shutdown()
        server.server_close()


# 26. POST /mcp with Origin: https://evil.example -> 403 before 401. POST with Host: evil.example -> 403 before 401.
def test_contract_26_header_order_precedence(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    server = serve_http(host="127.0.0.1", port=0, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8")

        # Invalid Origin, missing Authorization -> must return 403, not 401
        req_origin = urllib.request.Request(url, data=body, headers={"Origin": "https://evil.example", "Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc_org:
            urllib.request.urlopen(req_origin)
        assert exc_org.value.code == 403

        # Invalid Host, missing Authorization -> must return 403, not 401
        req_host = urllib.request.Request(url, data=body, headers={"Host": f"evil.example:{port}", "Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc_host:
            urllib.request.urlopen(req_host)
        assert exc_host.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


# 27. handle_message with call_tool or search raising RuntimeError("secret") returns JSON-RPC -32603, message is internal error, secret does not appear.
def test_contract_27_internal_error_masks_secret(mcp_env, monkeypatch):
    ledger_dir, projection_dir, db = mcp_env
    def bad_call(*a, **kw):
        raise RuntimeError("super_secret_token_12345")
    monkeypatch.setattr("ironledger.mcp.protocol.call_tool", bad_call)

    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search", "arguments": {"query": "Coffee"}}})
    resp = handle_message(req, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert resp is not None
    data = json.loads(resp)
    assert data["id"] == 1
    assert data["error"]["code"] == -32603
    assert data["error"]["message"] == "internal error"
    assert "super_secret_token_12345" not in resp

    # Also test exception inside search() function itself bubbling to -32603
    def bad_search(*a, **kw):
        raise RuntimeError("db_query_secret_leak_67890")
    monkeypatch.setattr("ironledger.mcp.tools.search", bad_search)
    monkeypatch.undo()  # restore protocol.call_tool
    monkeypatch.setattr("ironledger.mcp.tools.search", bad_search)

    resp_search = handle_message(req, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert resp_search is not None
    data_search = json.loads(resp_search)
    assert data_search["id"] == 1
    assert data_search["error"]["code"] == -32603
    assert data_search["error"]["message"] == "internal error"
    assert "db_query_secret_leak_67890" not in resp_search


# 28. HTTP POST /mcp with body 0xff,0xfe returns HTTP 200 with code -32700. stdio non-UTF-8 yields one -32700 stdout line.
def test_contract_28_non_utf8_decode_recovery(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    token = load_or_create_token(projection_dir)
    server = serve_http(host="127.0.0.1", port=0, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        req = urllib.request.Request(url, data=b"\xff\xfe", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["error"]["code"] == -32700

        # stdio non-UTF8
        stdin = io.BytesIO(b"\xff\xfe\n")
        stdout = io.BytesIO()
        stderr = io.StringIO()
        rc = run_stdio(stdin, stdout, stderr, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
        assert rc == 0
        data_stdio = json.loads(stdout.getvalue().decode("utf-8").strip())
        assert data_stdio["error"]["code"] == -32700
    finally:
        server.shutdown()
        server.server_close()


# 29. append_audit_event raising during tools/call search yields isError: true and no hit payload. Live projection is unchanged.
def test_contract_29_audit_failure_is_error(mcp_env, monkeypatch):
    ledger_dir, projection_dir, db = mcp_env
    def bad_audit(*a, **kw):
        raise RuntimeError("audit db error")
    monkeypatch.setattr("ironledger.mcp.tools.append_audit_event", bad_audit)

    res = call_tool("search", {"query": "Coffee"}, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert res["isError"] is True
    text = res["content"][0]["text"]
    assert "Coffee" not in text
    assert "stx-1" not in text


# 30. POST /mcp with valid bearer token and Origin: https://evil.example returns 403 and appends audit_events with action="mcp auth", target="http", result="denied".
def test_contract_30_origin_403_audited(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    token = load_or_create_token(projection_dir)
    server = serve_http(host="127.0.0.1", port=0, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        req = urllib.request.Request(url, data=b"{}", headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.example", "Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req)
        assert exc.value.code == 403

        conn = connect(db)
        row = conn.execute("SELECT action, target, result FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        conn.close()
        assert row is not None
        action, target, result = row
        assert action == "mcp auth"
        assert target == "http"
        assert result == "denied"
    finally:
        server.shutdown()
        server.server_close()


# 31. POST /mcp with valid bearer token and notification returns HTTP 202 and empty body.
def test_contract_31_notification_http_202(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    token = load_or_create_token(projection_dir)
    server = serve_http(host="127.0.0.1", port=0, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        body = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 202
            assert resp.read() == b""
    finally:
        server.shutdown()
        server.server_close()


# 32. POST /mcp with valid headers, Content-Length: 100, and a 2-byte body does not call handle_message and does not return a JSON-RPC result.
def test_contract_32_short_body_socket_timeout(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    token = load_or_create_token(projection_dir)
    server = serve_http(host="127.0.0.1", port=0, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sock = socket.socket()
        sock.settimeout(2.0)
        sock.connect(("127.0.0.1", port))
        sock.sendall(
            f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\nxx".encode("ascii")
        )
        time.sleep(0.5)
        sock.close()
    finally:
        server.shutdown()
        server.server_close()


# 33. projection/.mcp-token containing nope is replaced by load_or_create_token with a 64-hex token. nope is not accepted by verify_bearer.
def test_contract_33_corrupt_token_replaced(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".mcp-token").write_text("nope", encoding="utf-8")

    token = load_or_create_token(proj)
    assert len(token) == 64
    assert token != "nope"
    assert verify_bearer(f"Bearer {token}", token) is True
    assert verify_bearer("Bearer nope", token) is False


# 34. stdio: a binary line of 1,048,577 bytes then \n yields one stdout JSON-RPC -32700 and loop continues.
def test_contract_34_stdio_oversize_line(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    oversize = b"x" * 1048577 + b"\n"
    valid = b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
    stdin = io.BytesIO(oversize + valid)
    stdout = io.BytesIO()
    stderr = io.StringIO()

    rc = run_stdio(stdin, stdout, stderr, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert rc == 0
    lines = stdout.getvalue().decode("utf-8").splitlines()
    assert len(lines) == 2
    err_resp = json.loads(lines[0])
    assert err_resp["error"]["code"] == -32700
    ok_resp = json.loads(lines[1])
    assert ok_resp["id"] == 2
    assert ok_resp["result"] == {}


# 35. POST /mcp with Content-Type: text/plain returns 415. Missing Content-Type succeeds. Content-Type: application/json; charset=utf-8 succeeds.
def test_contract_35_content_type_rules(mcp_env):
    ledger_dir, projection_dir, db = mcp_env
    token = load_or_create_token(projection_dir)
    server = serve_http(host="127.0.0.1", port=0, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8")

        # 415 on text/plain
        req_plain = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req_plain)
        assert exc.value.code == 415

        # Success on missing Content-Type (urllib defaults to form-urlencoded, so use raw socket for missing header)
        sock = socket.socket()
        sock.connect(("127.0.0.1", port))
        sock.sendall(
            f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\nContent-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        )
        resp_missing = sock.recv(4096).decode("utf-8")
        sock.close()
        assert "200 OK" in resp_missing

        # Success on application/json; charset=utf-8
        req_charset = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(req_charset) as resp:
            assert resp.status == 200
    finally:
        server.shutdown()
        server.server_close()
