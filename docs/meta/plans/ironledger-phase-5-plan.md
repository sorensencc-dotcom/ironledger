# IronLedger Phase 5 read-only MCP implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose Phase 4 `search`, `balances`, and `projection_status` as a read-only MCP server: stdio by default, optional loopback Streamable HTTP with a bearer token.

**Architecture:** A new `src/ironledger/mcp/` package (eight modules, locked) implements a stdlib JSON-RPC / MCP 2025-03-26 subset. `tools.py` dispatches into `project.query` (and a lifted status helper). `stdio.py` and `http.py` are transports only. No mutation path, no `mcp` package, no SSE, no non-loopback bind.

```
  agent / client
       |
       |  argv: --db (audit only) --ledger-dir --projection-dir
       |  --bind absent => stdio     --bind 127.0.0.1|::1 --port N => HTTP
       v
  +------------------+     +----------------------------------------------+
  | stdio.py         |     | http.py   POST /mcp only                     |
  | newline JSON-RPC |     | 1 path/method  2 Host 403  3 Origin 403      |
  | one object/line  |     | 4 Content-Length/chunked 413 (max 1 MiB)     |
  +--------+---------+     | 5 Bearer 401   6 read body                   |
           |               +----------------------+-----------------------+
           |                                      |
           +------------------+-------------------+
                              v
                    protocol.py  JSON-RPC
                    initialize / ping / tools/list / tools/call
                              |
                              v
                    tools.py   allowlist:
                    search | balances | projection_status
                    (no compile/import/review/project/rule)
                              |
              +---------------+---------------+
              v                               v
     project.query                     audit_events on --db
     projection.sqlite                 action=mcp search|balances|status
     assert_fresh / search /           |mcp tools/call|mcp auth
     balances / projection_status      never store query string or token
              |
              X  never opens --db for query data
              X  never require_operator, never rebuild_projection
```

**Tech Stack:** Python 3.12+ standard library (`json`, `http.server`, `secrets`, `hmac`, `socket`, `argparse`). No new runtime dependency. Tests use `pytest`.

**Repo:** `C:\dev\IronLedger` (local `main`, no remote, decision D-0). Run tests with `python -m pytest -q` from the repo root. Baseline before Task 1: **418 passed / 2 skipped** without `bean-check` on PATH; **419 / 1** with. Phase 5 tests only add.

**Spec:** `docs/meta/specs/ironledger-phase-5-mcp-design.md`. Executors read both.

**Author:** commits use `Iron-Hammer <iron-hammer@ironledger.local>`.

**Eng-review lock (2026-09-09, 1A):** Phase 5 is this MCP plan, not the FastAPI/React workbench. Workbench history lives on `ironledger/phase-5-workbench`. Do not merge the workbench as Phase 5.

**Operator approval:** 2026-09-09, transcript C (commit spec+plan, then implement). Implementation paused on request (“do not implement yet”).

---

## Global Constraints

- Python `requires-python = ">=3.12"`. Standard library for runtime core. No new package. `ofxtools==1.1.1` remains the only runtime third-party import. Never `import mcp` / `from mcp` under `src/ironledger`.
- `beancount` is never imported under `src/ironledger`.
- Beancount files are the sole accounting authority. MCP reads `projection/projection.sqlite` only for query data. `--db` is required on `mcp` solely for `audit_events`.
- Monetary values are signed 64-bit integer minor units with explicit currency. No floating-point accounting arithmetic. Unlike currencies are never netted.
- Timestamps are UTC ISO-8601 `%Y-%m-%dT%H:%M:%SZ`.
- MCP is not a mutator. No `require_operator`. Safe mode does not deny `mcp`. Do not take compile or project locks. Do not call `rebuild_projection`.
- Tools: exactly `search`, `balances`, `projection_status`. Tool arguments MUST NOT accept filesystem paths.
- Transports are mutually exclusive: no `--bind` → stdio, no socket; `--bind 127.0.0.1|::1 --port 1..65535` → HTTP, stdin is not MCP.
- `--bind` literals allowed: `127.0.0.1`, `::1`. Refuse `0.0.0.0`, `::`, `localhost`, RFC1918, public, hostnames.
- HTTP token: 32 bytes hex at `<projection-dir>/.mcp-token`, `chmod 0o600`, `hmac.compare_digest`. Never print the secret. `--rotate-token` requires `--bind`.
- Protocol: JSON-RPC 2.0, MCP `2025-03-26`. Stdout (stdio) is only newline-delimited JSON-RPC. Batches rejected (`-32600`). GET `/mcp` → 405. No SSE, no session id.
- Search limits unchanged: default 50, max 500, offset ≥ 0. Business errors are `isError: true` with the Phase 4 error formula, not tracebacks on stdout.
- Exit codes: `0` clean EOF / server stop, `1` bind/token write failure, `2` argv.
- Eight-module layout is locked. Do not collapse it.
- D-0: no remote, do not push.
- Parked: date/account filters, rollups, runway, health, mutation MCP, SDK, SSE, non-loopback, WebAuthn.

---

## File structure

Created:

| Path | Responsibility |
|---|---|
| `src/ironledger/mcp/__init__.py` | Re-exports public types and `PROTOCOL_VERSION` |
| `src/ironledger/mcp/errors.py` | Exception types + formatters |
| `src/ironledger/mcp/bind.py` | `assert_loopback(host: str) -> None` |
| `src/ironledger/mcp/token.py` | create / load / rotate / verify bearer |
| `src/ironledger/mcp/tools.py` | allowlist, schemas, `call_tool` |
| `src/ironledger/mcp/protocol.py` | JSON-RPC + MCP methods |
| `src/ironledger/mcp/stdio.py` | newline JSON-RPC loop |
| `src/ironledger/mcp/http.py` | Streamable HTTP on loopback |
| `tests/test_mcp_errors.py` | Error formula |
| `tests/test_mcp_bind.py` | Loopback policy |
| `tests/test_mcp_token.py` | Token file |
| `tests/test_mcp_tools.py` | Allowlist + dispatch |
| `tests/test_mcp_protocol.py` | JSON-RPC / initialize / list / call |
| `tests/test_mcp_stdio.py` | stdio framing |
| `tests/test_mcp_http.py` | HTTP bind, 401, Origin, Host |
| `tests/test_cli_mcp.py` | CLI argv |
| `tests/test_mcp_audit.py` | Audit events |
| `tests/test_phase5_exit_contract.py` | Gate items 1–35 except 20 |

Modified:

| Path | Why |
|---|---|
| `src/ironledger/project/query.py` | Lift `projection_status` out of the CLI |
| `src/ironledger/cli/__main__.py` | `mcp` command; `--db` after subcommand; `_needs_operational_db` |
| `src/ironledger/__init__.py` | Phase banner → 5 |
| `src/ironledger/cli/__init__.py` | Phase banner → 5 |
| `pyproject.toml` | `[tool.ironledger] phase = 5` |
| `.gitignore` | `**/.mcp-token` |
| `README.md` | Optional mcp golden path |
| `docs/meta/ironledger-dependency-posture.md` | Phase 5: still no `mcp` package |

Do not add `mcp` to `project.dependencies` or `optional-dependencies`.

---

### Task 1: MCP error types and the error formula

**Files:**
- Create: `src/ironledger/mcp/__init__.py`
- Create: `src/ironledger/mcp/errors.py`
- Test: `tests/test_mcp_errors.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `PROTOCOL_VERSION = "2025-03-26"`
  - `class McpError(Exception)`
  - `class McpBindError(McpError)`
  - `class McpAuthError(McpError)`
  - `class McpProtocolError(McpError)`
  - `format_bind_refused(host: str) -> str`
  - `format_auth_denied() -> str` — must not include a token
  - `format_protocol_error(reason: str) -> str`

Every formatter returns **problem + cause + fix**. Bind errors name the refused host and state allowed values `127.0.0.1` and `::1`. Auth formatter has no secret and no `Authorization` header value.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_errors.py
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
    msg = format_bind_refused("0.0.0.0")
    assert "0.0.0.0" in msg
    assert "127.0.0.1" in msg
    assert "::1" in msg


def test_format_auth_denied_has_no_secret():
    msg = format_auth_denied()
    assert "bearer" in msg.lower() or "Authorization" in msg
    for banned in ("token=", "Bearer abc", ".mcp-token"):
        assert banned not in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mcp_errors.py -q`
Expected: FAIL (module not found)

- [ ] **Step 3: Write minimal implementation**

`src/ironledger/mcp/__init__.py` exports `PROTOCOL_VERSION` from errors or a constant in `__init__`. Prefer `PROTOCOL_VERSION` in `__init__.py` as `"2025-03-26"`. `errors.py` implements the classes and formatters.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_mcp_errors.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/mcp/__init__.py src/ironledger/mcp/errors.py tests/test_mcp_errors.py
git commit -m "feat(mcp): add error types and bind/auth formula"
```

---

### Task 2: Loopback bind policy

**Files:**
- Create: `src/ironledger/mcp/bind.py`
- Test: `tests/test_mcp_bind.py`

**Interfaces:**
- Consumes: `McpBindError`, `format_bind_refused`
- Produces: `assert_loopback(host: str) -> None` — returns None for `127.0.0.1` and `::1`; raises `McpBindError` otherwise. Strip wrapping brackets on `::1` so `[::1]` is also accepted as a host string? Spec says `--bind` literals are `127.0.0.1` and `::1` only. Reject `[::1]`, `localhost`, `0.0.0.0`, `::`, `192.168.1.1`, empty string, `127.0.0.2`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_bind.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mcp_bind.py -q`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
ALLOWED = frozenset({"127.0.0.1", "::1"})

def assert_loopback(host: str) -> None:
    if host not in ALLOWED:
        raise McpBindError(format_bind_refused(host))
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_mcp_bind.py tests/test_mcp_errors.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/mcp/bind.py tests/test_mcp_bind.py
git commit -m "feat(mcp): refuse non-loopback bind hosts"
```

---

### Task 3: Bearer token file

**Files:**
- Create: `src/ironledger/mcp/token.py`
- Test: `tests/test_mcp_token.py`

**Interfaces:**
- Consumes: `secrets`, `hmac`, `os.chmod`
- Produces:
  - `TOKEN_NAME = ".mcp-token"`
  - `load_or_create_token(projection_dir: Path) -> str` — 64 lowercase hex chars; create dir if needed; do not create `projection.sqlite`; write `.mcp-token.tmp` then `os.replace`; `chmod 0o600` on every load
  - `rotate_token(projection_dir: Path) -> str` — always write a new token via `.mcp-token.tmp` then `os.replace`
  - `verify_bearer(header: str | None, token: str) -> bool` — True iff header is `Bearer <token>` (single space) and `hmac.compare_digest`

Reuse existing file on `load_or_create_token` if it is exactly 64 hex chars. Corrupt/short file → rotate in place (treat as missing and rewrite). Do not log the token.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_token.py
import stat
from pathlib import Path
import pytest
from ironledger.mcp.token import load_or_create_token, rotate_token, verify_bearer


def test_create_hex_and_reuse(tmp_path: Path):
    token = load_or_create_token(tmp_path / "projection")
    assert len(token) == 64
    int(token, 16)
    again = load_or_create_token(tmp_path / "projection")
    assert again == token
    assert not (tmp_path / "projection" / "projection.sqlite").exists()


@pytest.mark.skipif(not hasattr(stat, "S_ISREG"), reason="posix mode")
def test_mode_0600(tmp_path: Path, monkeypatch):
    import os
    if os.name == "nt":
        pytest.skip("Windows chmod subset")
    load_or_create_token(tmp_path)
    mode = (tmp_path / ".mcp-token").stat().st_mode & 0o777
    assert mode == 0o600


def test_rotate_changes(tmp_path: Path):
    a = load_or_create_token(tmp_path)
    b = rotate_token(tmp_path)
    assert a != b
    assert load_or_create_token(tmp_path) == b


def test_verify_bearer():
    token = "ab" * 32
    assert verify_bearer(f"Bearer {token}", token) is True
    assert verify_bearer(f"Bearer {'cd' * 32}", token) is False
    assert verify_bearer(None, token) is False
    assert verify_bearer("Bearer", token) is False
    assert verify_bearer(f"bearer {token}", token) is False


def test_corrupt_token_rewritten(tmp_path: Path):
    path = tmp_path / ".mcp-token"
    path.write_text("nope", encoding="utf-8")
    token = load_or_create_token(tmp_path)
    assert len(token) == 64
    int(token, 16)
    assert path.read_text(encoding="utf-8").strip() == token
    assert verify_bearer("Bearer nope", token) is False


def test_reuse_chmods_0600(tmp_path: Path):
    import os, stat
    if os.name == "nt":
        pytest.skip("Windows chmod subset")
    token = load_or_create_token(tmp_path)
    path = tmp_path / ".mcp-token"
    os.chmod(path, 0o644)
    again = load_or_create_token(tmp_path)
    assert again == token
    assert path.stat().st_mode & 0o777 == 0o600
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mcp_token.py -q`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation** in `token.py` using `secrets.token_bytes(32).hex()`, write UTF-8 LF to `.mcp-token.tmp`, `os.replace` onto `.mcp-token`, `os.chmod(live, 0o600)` on every load.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_mcp_token.py tests/test_mcp_bind.py tests/test_mcp_errors.py -q`
Expected: PASS (Windows skip on mode test is allowed)

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/mcp/token.py tests/test_mcp_token.py
git commit -m "feat(mcp): 0600 bearer token file at projection/.mcp-token"
```

---

### Task 4: Lift `projection_status` into `project.query`

**Files:**
- Modify: `src/ironledger/project/query.py`
- Modify: `src/ironledger/cli/__main__.py` (`_live_project_status` becomes a wrapper or is deleted)
- Test: `tests/test_project_query.py` (add functions; file already exists)

**Interfaces:**
- Consumes: existing `assert_fresh`, compile journal `get_latest_successful_run` only when `db` is a path
- Produces: `def projection_status(ledger_dir: Path, projection_dir: Path, *, db: str | None = None) -> dict`

Return shape matches current CLI JSON: `status` in `{ok, mismatch, missing}`; `ledger_output_hash` when known; `hash_matches_files`; when `db` is set, `latest_run` and `hash_matches_compile`. Missing both sqlite and manifest → `{"status": "missing"}` without raising. CLI `_cmd_project_status` must call this and keep exit 0 for missing.

- [ ] **Step 1: Write the failing test** in `tests/test_project_query.py`:

```python
def test_projection_status_missing(tmp_path: Path):
    from ironledger.project.query import projection_status
    got = projection_status(tmp_path / "ledger", tmp_path / "projection")
    assert got == {"status": "missing"}
```

Add a second test that rebuilds via existing fixtures (`write_rendered_ledger`, `seed_successful_compile_run`, `rebuild_projection`) and asserts `status == "ok"` and `hash_matches_files is True`.

- [ ] **Step 2: Run the new tests — FAIL because `projection_status` is missing**

- [ ] **Step 3: Implement `projection_status` by moving `_live_project_status` logic. Point `_cmd_project_status` at it. Keep CLI output identical.**

- [ ] **Step 4: Run `python -m pytest tests/test_project_query.py tests/test_cli_project.py tests/test_phase4_exit_contract.py -q`**
Expected: PASS (Phase 4 must not regress)

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/project/query.py src/ironledger/cli/__main__.py tests/test_project_query.py
git commit -m "refactor(project): lift projection_status out of CLI"
```

---

### Task 5: Tool allowlist and dispatch

**Files:**
- Create: `src/ironledger/mcp/tools.py`
- Test: `tests/test_mcp_tools.py`

**Interfaces:**
- Consumes: `assert_fresh`, `search`, `balances`, `projection_status` from `project.query`; `SearchHit` / `BalanceRow`
- Produces:
  - `TOOL_NAMES = ("search", "balances", "projection_status")`
  - `list_tools() -> list[dict]` — MCP tool descriptors with `name`, `description`, `inputSchema`
  - `call_tool(name: str, arguments: dict, *, ledger_dir: Path, projection_dir: Path, db: str | None) -> dict` — return `{"isError": bool, "content": [{"type": "text", "text": <json or error formula>}]}`

`search` schema: required `["query"]`; `limit` integer 1–500 default 50; `offset` integer min 0 default 0. No path properties.

JSON text blobs: `json.dumps(..., indent=2, sort_keys=True)` of `{"hits":[...]}` / `{"balances":[...]}` / status dict. Dataclass fields as keys; `minor_units` int.

Unknown name: `isError True`, do not open sqlite. Empty/invalid query: `isError True` using existing `format_query_error` / `ProjectInputError` / `ProjectStaleError` strings.

- [ ] **Step 1: Write the failing test** covering list order, search parity with `query.search` on the sample ledger (rebuild first), unknown `compile` does not call rebuild (patch `rebuild_projection` and assert not called), integer `minor_units` after `json.loads`.

Use `tests.project_fixtures` plus `rebuild_projection` like Phase 4 tests. Safe-mode off config as needed for rebuild.

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement `tools.py`**

- [ ] **Step 4: PASS `tests/test_mcp_tools.py` plus Phase 4 query tests**

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/mcp/tools.py tests/test_mcp_tools.py
git commit -m "feat(mcp): allowlist search, balances, projection_status"
```

---

### Task 6: JSON-RPC protocol

**Files:**
- Create: `src/ironledger/mcp/protocol.py`
- Test: `tests/test_mcp_protocol.py`

**Interfaces:**
- Consumes: `list_tools`, `call_tool`, `PROTOCOL_VERSION`, `__version__` from `ironledger`
- Produces:
  - `handle_message(raw: str, *, ledger_dir: Path, projection_dir: Path, db: str | None) -> str | None`
  - `None` for notifications (`notifications/initialized`, `notifications/cancelled`, or any object without `id` that is a notification)
  - Returned string is a single JSON object, no trailing extra keys, `jsonrpc: "2.0"`

Rules:
- Invalid JSON → `{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}`
- JSON array → `-32600`
- Unknown method → `-32601`
- `initialize` result includes `protocolVersion`, `capabilities.tools.listChanged == False`, `serverInfo.name == "ironledger"`
- `ping` → `{}` result
- `tools/list` → `{ "tools": list_tools() }`
- `tools/call` params `name` + `arguments`; result is MCP `CallToolResult` (`content` + `isError`)
- `resources/list` / `prompts/list` → `-32601`
- Unexpected exception from `call_tool` (or anything after a parsed request) → `-32603` with `error.message == "internal error"`, same `id` as the request. Stdout is that one JSON object. No traceback on stdout.

- [ ] **Step 1: Failing tests** for parse error, batch, initialize, ping, tools/list names, tools/call search (needs rebuilt projection), resources/list -32601, initialized notification returns None, and `call_tool` patched to `raise RuntimeError("secret path")` → `-32603`, `"internal error"` in the body, `"secret path"` not in stdout.

- [ ] **Step 2–4:** implement and pass

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/mcp/protocol.py tests/test_mcp_protocol.py
git commit -m "feat(mcp): JSON-RPC initialize, ping, tools/list, tools/call"
```

---

### Task 7: stdio transport

**Files:**
- Create: `src/ironledger/mcp/stdio.py`
- Test: `tests/test_mcp_stdio.py`

**Interfaces:**
- Produces: `def run_stdio(stdin, stdout, stderr, *, ledger_dir: Path, projection_dir: Path, db: str | None) -> int`
- `stdin` is a **binary** buffered stream (`sys.stdin.buffer`). Read until `\n` or `MAX_HTTP_BODY + 1` bytes. Oversize → discard through `\n`, one `-32700` stdout line, continue.
- Each in-limit request line → one stdout line ending `\n`. Notifications: no stdout line. Return `0`.
- A line that is not valid UTF-8 → one stdout line with JSON-RPC `-32700`, then continue. Do not crash.
- Must not write a banner to stdout. Logs only on stderr, and stderr must not contain a 64-hex token even if a token file exists.

- [ ] **Step 1: Test with `io.BytesIO` stdin and `io.BytesIO` stdout:** write an initialize request line (UTF-8 + `b"\n"`), run `run_stdio`, `json.loads` the single stdout line, assert `serverInfo.name`, assert stdout has no prefix before `{`. Also: 1,048,577 bytes + `\n` → `-32700` and loop still handles a following initialize.

- [ ] **Step 2–4**

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/mcp/stdio.py tests/test_mcp_stdio.py
git commit -m "feat(mcp): newline-delimited stdio transport"
```

---

### Task 8: Streamable HTTP transport

**Files:**
- Create: `src/ironledger/mcp/http.py`
- Test: `tests/test_mcp_http.py`

**Interfaces:**
- Produces:
  - `def serve_http(*, host: str, port: int, ledger_dir: Path, projection_dir: Path, db: str | None, rotate: bool = False) -> HTTPServer`
  - Call `assert_loopback(host)` before bind. `load_or_create_token` or `rotate_token`. Bind `(host, port)`.
  - Handler order is locked (spec §8): path/method → Host 403 → Origin 403 → Content-Type 415 → Content-Length/chunked 413 → Bearer 401 → read body → `handle_message`.
  - Before reading the body, set a 5.0s timeout on the request socket. Timeout or undersize body: close, no `handle_message`.
  - Audit insert failure on 401/403: still return 401/403, never 500.
  - POST `/mcp` only for JSON-RPC. GET `/mcp` → 405. other path → 404.
  - If `Transfer-Encoding` contains `chunked`, or `Content-Length` is missing / not a non-negative int / `> 1048576`, return **413** and do not call `handle_message`. Constant `MAX_HTTP_BODY = 1_048_576`.
  - Bearer via `verify_bearer`. Fail → 401 + `WWW-Authenticate: Bearer`. 401 only after Host and Origin passed.
  - Origin present and not in the spec allowlist → 403 even with a valid token.
  - Host header not loopback (spec §8) → 403 even with no Authorization header (must not be 401).
  - Notification POST → 202 empty.
  - Request POST → 200 `application/json` body from `handle_message`.

Tests bind the server with port `0` (`HTTPServer((host, 0), …)` after `assert_loopback`) and read `httpd.server_address[1]`. Do **not** open-and-close a throwaway socket first (TOCTOU under parallel pytest). CLI Task 9 still rejects `--port 0` (exit 2). `serve_http` for production is called with the operator's 1..65535 port; the test fixture may pass `0`.

Use `threading.Thread(target=httpd.handle_request)` or `serve_forever` + `shutdown`. `urllib.request` for POST. Always `httpd.server_close()` in finally.

Cover: 401 missing token, 401 wrong token (search not executed — use a projection_dir without sqlite and assert 401 rather than isError stale), valid token tools/list, Origin evil 403 even with valid token, Host evil 403 with no Authorization (not 401), GET 405, POST `/other` 404, getsockname 127.0.0.1, rotate invalidates old token, POST with `Content-Length: 1048577` → 413 and `handle_message` not called, POST with `Transfer-Encoding: chunked` → 413, POST body `b"\xff\xfe"` → HTTP 200 JSON-RPC `-32700`, POST notification `notifications/initialized` (no id) → HTTP 202 empty body, raw-socket POST with `Content-Length: 100` and 2-byte body does not call `handle_message` (timeout bounded), `Content-Type: text/plain` → 415, missing Content-Type + JSON still 200.

- [ ] **Steps 1–4** as usual

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/mcp/http.py tests/test_mcp_http.py
git commit -m "feat(mcp): loopback Streamable HTTP with bearer token"
```

---

### Task 9: CLI `ironledger mcp`

**Files:**
- Modify: `src/ironledger/cli/__main__.py`
- Modify: `src/ironledger/__init__.py`, `src/ironledger/cli/__init__.py`, `pyproject.toml` phase = 5
- Test: `tests/test_cli_mcp.py`

**Interfaces:**
- Add parser `mcp` with `--db` `argparse.SUPPRESS` (same dest-split as `project` so `--db` after `mcp` works), `--ledger-dir`, `--projection-dir`, `--bind`, `--port` type=int, `--rotate-token` store_true.
- `_needs_operational_db`: include `command == "mcp"`. Missing `--db` is exit 2 **there** (`_require_db`), same as `project` rebuild. `_cmd_mcp` assumes `args.db` is set; it does not print a second missing-`--db` error. `--db` after `mcp` uses `argparse.SUPPRESS` dest-split like `project`.
- Dispatch: no bind → `run_stdio(sys.stdin.buffer, sys.stdout.buffer, sys.stderr, ...)`. bind → `assert_loopback`, reject port not in 1..65535, `serve_http` then `serve_forever` until KeyboardInterrupt, return 0. stdout writes are UTF-8 JSON + `\n` on the binary buffer.
- `--bind` without `--port`, `--port` without `--bind`, `--rotate-token` without `--bind`: print error, return 2. Do this in `_cmd_mcp` (not only argparse required=) so tests can assert return code 2 via `main(argv)` without SystemExit from `parser.error` — **or** use `parser.error` which exits 2 via SystemExit. Match existing CLI: `project` uses `_require_db` return 2. Prefer `_cmd_mcp` returning 2 for the three argv combinations so `main([...])` is testable without catching SystemExit. `--port 0` is exit 2.
- `require_operator` must not be imported on this path in a way that it runs. Safe mode on: still start stdio.

- [ ] **Step 1: Tests**
  - `main(["mcp"])` without `--db` → 2
  - `main(["mcp", "--db", db, "--ledger-dir", ledger, "--bind", "127.0.0.1"])` without port → 2
  - `main(["--help"])` stdout contains `mcp`
  - `main(["mcp", "--db", db, "--bind", "0.0.0.0", "--port", "9", "--ledger-dir", ledger])` → 1
  - `main(["mcp", "--db", str(db), "--ledger-dir", str(ledger)])` with stdin initialize via patch of `run_stdio` or StringIO monkeypatch of sys.stdin — prefer calling `main` with patched `ironledger.cli.__main__.run_stdio` if imported at dispatch time; cleaner to patch `sys.stdin`/`sys.stdout` as StringIO. Assert return 0 and JSON on stdout.

- [ ] **Step 2–4**

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/cli/__main__.py src/ironledger/__init__.py src/ironledger/cli/__init__.py pyproject.toml tests/test_cli_mcp.py
git commit -m "feat(cli): ironledger mcp stdio and loopback HTTP"
```

---

### Task 10: Audit events

**Files:**
- Modify: `src/ironledger/mcp/tools.py` and `src/ironledger/mcp/http.py`
- Test: `tests/test_mcp_audit.py`

**Interfaces:**
- `call_tool` order: query into memory → `append_audit_event` on `--db` → serialize. If audit raises: `isError: true`, no hits. Never put the FTS query in `target`. `action` one of `mcp search` / `mcp balances` / `mcp status` / `mcp tools/call`, `actor="operator"`, `result=ok|error`, `input_hash=ledger_output_hash` when opened.
- HTTP 401/403: `action="mcp auth"`, `target="http"`, `result="denied"`.
- If `db` is None inside `call_tool` (should not happen from CLI), skip audit.
- Audit insert failure on tool path: return `isError True`, no hits.

- [ ] **Step 1: Tests** using fixtures: rebuild, `call_tool("search", {"query":"Coffee"}, ...)`, `SELECT action, target, result FROM audit_events`; assert query string `"Coffee"` not in any column values. HTTP 401 test reuses server helper from Task 8 and asserts last audit row. Patch `append_audit_event` to raise: `call_tool("search", {"query":"Coffee"})` → `isError: true` and the text contains no `Coffee` and no posting_id from the sample set. Origin-403 POST (valid token, `Origin: https://evil.example`) → HTTP 403 and last audit row `action="mcp auth"`, `result="denied"`.

- [ ] **Step 2–4**

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/mcp/tools.py src/ironledger/mcp/http.py tests/test_mcp_audit.py
git commit -m "feat(mcp): audit tool calls and HTTP auth denials"
```

---

### Task 11: gitignore, README, dependency posture

**Files:**
- Modify: `.gitignore`, `README.md`, `docs/meta/ironledger-dependency-posture.md`
- Test: extend `tests/test_cli_mcp.py` or `tests/test_phase5_exit_contract.py` item 16

**Interfaces:**
- `.gitignore` contains `**/.mcp-token`
- README: after the Phase 4 golden path, 4–8 lines on optional `mcp` (stdio command + note that HTTP needs `--bind 127.0.0.1 --port` and a token file). Do not print a fake token. Keep the existing three-command golden path as primary.
- Dependency posture: new section “Phase 5: MCP is stdlib JSON-RPC; no `mcp` package; runtime deps unchanged.”

- [ ] **Step 1: Test** that `.gitignore` text includes `**/.mcp-token`. If `git` is on PATH, `git check-ignore -q projection/.mcp-token` from repo root after creating a dummy file in tmp is optional; the string check is gate item 16 minimum. Also `test_contract_19` later greps source for `import mcp`.

- [ ] **Step 2–4**

- [ ] **Step 5: Commit**

```bash
git add .gitignore README.md docs/meta/ironledger-dependency-posture.md tests/test_cli_mcp.py
git commit -m "docs(ironledger): Phase 5 mcp gitignore, README, dep posture"
```

---

### Task 12: Phase 5 exit contract

**Files:**
- Create: `tests/test_phase5_exit_contract.py`

**Interfaces:**
- Named tests `test_contract_1` … `test_contract_35` except `test_contract_20` (full suite is `pytest -q`, documented in the module docstring like Phase 4 item 12).
- Each maps 1:1 to spec §12. Reuse helpers from earlier tests; do not weaken assertions.

Item 9 “no listening TCP socket”: assert `serve_http` is not called when `run_stdio` runs (patch `ironledger.mcp.http.serve_http` / or check `mcp.http` was not asked to bind). Do not require netstat.

Item 16: `.gitignore` contains `**/.mcp-token`.

Item 19: walk `src/ironledger` for `import mcp` and `from mcp`; read `pyproject.toml` dependencies.

Item 21: `--help` lists mcp; `main(["mcp", "--db", db, "--ledger-dir", ledger])` with patched stdin works — also `main(["mcp", "--ledger-dir", ledger, "--db", db, ...])` dest-split.

- [ ] **Step 1: Write failing tests for any spec item not already covered; they should mostly PASS if Tasks 1–11 were faithful. Any FAIL is a spec gap — fix code, not the contract.**

- [ ] **Step 2: `python -m pytest tests/test_phase5_exit_contract.py -q` PASS**

- [ ] **Step 3: `python -m pytest -q` — count ≥ Phase 4 baseline, only adds**

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase5_exit_contract.py
git commit -m "test(mcp): Phase 5 exit contract items 1-35"
```

---

## Self-review (spec coverage)

| Spec § | Tasks |
|---|---|
| §3 P5-1 tools | 5, 6, 12.1/7 |
| §3 P5-2 stdio vs HTTP | 7, 8, 9 |
| §3 P5-3 token | 3, 8, 12.15, 12.33 |
| §4 CLI / argv | 9, 12.21–22 |
| §5 protocol | 6, 12.8/23/27/34 |
| §6 tool payloads | 4, 5, 12.2–6 |
| §7 stdio | 7, 12.9, 12.34 |
| §8 HTTP security | 2, 8, 12.10–14, 24–26, 30–32, 35 |
| §9 audit | 10, 12.18, 12.29–30 |
| §10 layout | 1–8 (eight modules) |
| §11 out of scope | 5, 12.7/19 |
| §12 contract | 12 |
| no `mcp` package | 11, 12.19 |
| Phase 4 non-regression | 4, 12.20 |

No TBD / FIXME / placeholder tokens in this plan.

---

## NOT in scope

- Date/account filters, category rollups, runway, health (P5-1).
- Mutation MCP tools; FastAPI/React workbench as Phase 5 (on `ironledger/phase-5-workbench`, do not merge).
- Official `mcp` package; SSE; session IDs; JSON-RPC batches.
- Non-loopback bind; Tailscale/VPN; WebAuthn (Phase 8).
- Per-request watchdog, SIGTERM handler, thread pool (21A).
- Cross-db SQLite transaction for query+audit (two files).
- `--bind localhost` (numeric bind only). Dropping `Host: localhost` (16A kept it).
- Numbered performance gate; process-local hash cache for `assert_fresh`.
- Public GitHub, LICENSE, push (D-0).
- Deleting leftover untracked `web/` (working tree junk, not this plan).

## What already exists

- `project.query.search` / `balances` / `assert_fresh` — MCP tools call these; do not fork FTS.
- CLI `_live_project_status` — Task 4 lifts it; CLI becomes a caller.
- `append_audit_event` — MCP audits through it; no second chain.
- `argparse.SUPPRESS` dest-split on `project --db` — copy for `mcp`.
- Phase 4 error formula (`format_stale`, `format_query_error`) — tool `isError` text.
- `acquire_lock` / compile / project mutators — MCP must not call them.

## Failure modes

| Path | Failure | Test | Handler | User sees |
|---|---|---|---|---|
| tools/call search | stale projection | c5 | isError formula | hashes + copy-paste project |
| tools/call search | audit insert raises | c29 | isError, no hits | error, no rows |
| HTTP POST | evil Host/Origin | c24/26/30 | 403 + mcp auth | 403 |
| HTTP POST | no/wrong bearer | c11/12 | 401 | 401 WWW-Authenticate |
| HTTP POST | oversize/chunked | c25 | 413 | 413 |
| HTTP POST | slow/short body | c32 | 5s timeout, close | hang ≤5s then close |
| HTTP POST | text/plain | c35 | 415 | 415 |
| HTTP POST | invalid UTF-8 | c28 | -32700 | JSON-RPC parse error |
| stdio | oversize line | c34 | -32700, continue | parse error, session lives |
| stdio | unexpected exception | c27 | -32603 internal error | no traceback on stdout |
| mutation name | compile via tools/call | c7 | isError, no rebuild | error, ledger unchanged |
| Crash after HTTP write | unaudited bytes on wire | inherent | none | possible; two files |

No silent-and-untested path remains at conf ≥7.

## Worktree parallelization

| Step | Modules | Depends on |
|------|---------|------------|
| T1–T3 errors/bind/token | `mcp/` | — |
| T4 lift projection_status | `project/`, `cli/` | — |
| T5–T6 tools/protocol | `mcp/` | T1, T4 |
| T7–T8 stdio/http | `mcp/` | T3, T6 |
| T9 CLI | `cli/` | T7, T8 |
| T10 audit | `mcp/` | T5, T8 |
| T11–T12 docs/contract | docs, tests | T9, T10 |

Lane A: T1 → T2 → T3. Lane B: T4 (parallel with A). Merge. Then T5→T12 sequential on `mcp/` + `cli/`.

Conflict: T4 and T9 both touch `cli/__main__.py` — run T4 before T9, not in parallel.

## Implementation Tasks

Synthesized from this review's findings. Each folds into an existing plan task; no extra SDD wave.

- [ ] **T-R1 (P1, human: ~20min / CC: ~8min)** — token — chmod 0600 on every load; write tmp + `os.replace`
  - Surfaced by: outside voice — reused 0644 file; non-atomic write
  - Files: `src/ironledger/mcp/token.py`, `tests/test_mcp_token.py`
  - Verify: `pytest tests/test_mcp_token.py -q`
- [ ] **T-R2 (P1, human: ~20min / CC: ~8min)** — stdio — binary stdin, 1 MiB line cap
  - Surfaced by: outside voice — unbounded line; text stdin vs UTF-8
  - Files: `src/ironledger/mcp/stdio.py`, `cli/__main__.py`
  - Verify: contract 34
- [ ] **T-R3 (P1, human: ~15min / CC: ~5min)** — http — 5s read timeout; tests bind port 0; Content-Type 415
  - Surfaced by: outside voice + 20B
  - Files: `src/ironledger/mcp/http.py`, `tests/test_mcp_http.py`
  - Verify: contract 32, 35
- [ ] **T-R4 (P1, human: ~10min / CC: ~5min)** — tools — query → audit → serialize
  - Surfaced by: Architecture/outside voice — two-file audit order
  - Files: `src/ironledger/mcp/tools.py`
  - Verify: contract 29

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | CLEAR | 12 findings; folded or rejected in-session |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 1A workbench off main; HTTP order/caps; contract 1–35 |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | no UI in this slice |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **CODEX:** chmod-on-reuse, atomic token, stdio 1 MiB, binary stdin, 5s read timeout, `--db` owner, port-0 fixture, 401-audit-fail, query-then-audit, Content-Type 415. Rejected: drop Host localhost; extra watchdog.
- **CROSS-MODEL:** Agreed on token/stdio/HTTP hardening. Disagreed on Host localhost (kept) and extra shutdown machinery (rejected).
- **VERDICT:** ENG CLEARED — plan ready for operator approval then implementation. CEO optional. Design not required (no UI).

NO UNRESOLVED DECISIONS
