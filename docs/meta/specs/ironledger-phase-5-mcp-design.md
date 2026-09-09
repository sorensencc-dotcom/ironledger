# IronLedger Phase 5 read-only MCP design

Status: design for operator review; no implementation approval.
Scope: expose the Phase 4 projection as a read-only MCP server. Default transport is stdio (no socket). Optional Streamable HTTP binds `127.0.0.1` or `::1` only, with a bearer token. Tools are `search`, `balances`, and `projection_status`. Date/account filters, category aggregation, runway, health, mutation tools, and a public listener stay out of scope.

Locked in the Phase 5 discuss (2026-09-09): wrap Phase 4 query surface only; stdio default plus optional localhost HTTP; HTTP bind requires a 0600 bearer token at `projection/.mcp-token`; stdio is process-inherited and does not use the token.

## 1. Why this phase exists

Phase 4 rebuilt a disposable SQLite projection and exposed `search` / `balances` / `project status` on the local CLI. Architecture already says default MCP is read-only, binds localhost or nothing, and has no compile or mutation capability. Phase 5 is that surface: the same query functions, reached by an agent over MCP, without standing up SimpleFIN, RAG, or mobile.

Agents may pull, stage, and report. They may not approve, compile, mutate the ledger, commit, or push. The MCP server is the pull/report path. It never calls `require_operator`, never takes the compile or project lock, and never rebuilds the projection as a side effect of a tool call.

## 2. Fixed invariants inherited

- Beancount plus retained source evidence is the sole accounting authority. The projection is a cache. MCP reads `projection/projection.sqlite` the same way `search` does. It does not open the operational `--db` for query data.
- Monetary values in tool results are signed integer minor units with an explicit currency. No floating-point accounting arithmetic. Unlike currencies are never netted. `balances` returns one object per `(account, currency)` row.
- Timestamps are ISO-8601 UTC with a trailing `Z`.
- Mutation-capable operations stay on the local CLI with a phrase and safe mode. MCP is not a mutator. Safe mode ON leaves MCP available.
- `beancount` is never imported under `src/ironledger`. No new runtime third-party package. The MCP JSON-RPC subset is implemented with the standard library. `ofxtools==1.1.1` remains the only runtime third-party import.
- Windows is a first-class host. No symlink activation, no Unix-socket-only design.
- D-0: no remote, do not push.
- Search order, limits, and freshness are Phase 4's: FTS `MATCH` with a bound parameter; `--limit` default 50, hard max 500; `--offset` default 0; `ORDER BY entry_date ASC, posting_id ASC`; stale / missing projection fail closed with the same error formula as the CLI (hashes, `--ledger-dir`, copy-paste `project` line). Empty or invalid FTS is an error, not a traceback.

## 3. Operator decisions locked this phase

| ID | Decision |
|---|---|
| P5-1 | Tools are exactly `search`, `balances`, `projection_status`. Date-range and account-prefix filters, category aggregation, runway, and health are deferred. |
| P5-2 | Default transport is MCP stdio. `--bind 127.0.0.1 --port N` (or `::1`) selects Streamable HTTP. The two are mutually exclusive in one process: `--bind` present → HTTP, stdin is not an MCP stream; `--bind` absent → stdio, no socket. |
| P5-3 | HTTP bind requires a 32-byte random token, hex-encoded (64 ASCII hex chars), stored `0600` at `<projection-dir>/.mcp-token`. The file is created on first successful HTTP bind if missing, reused thereafter. `--rotate-token` requires `--bind` and replaces the file before listen. HTTP requests require `Authorization: Bearer <token>`. Missing or wrong token → HTTP 401, no tool execution, no rows. The token is never written to stdout, never included in an audit event, never interpolated into a log line. stdio does not read or require the token. |

## 4. Command and layout

```
python -m ironledger.cli mcp --db <db> --ledger-dir ledger
python -m ironledger.cli mcp --db <db> --ledger-dir ledger --bind 127.0.0.1 --port 8765
```

`--db` is **required** on `mcp` (unlike `search`). Queries still hit only the projection file. `--db` exists so tool calls and HTTP 401s can append `audit_events`. `--ledger-dir` is required. `--projection-dir` overrides the Phase 4 sibling default.

`--bind` allowed values: the literals `127.0.0.1` and `::1` only. `0.0.0.0`, `::`, `localhost`, RFC1918, public, and hostname strings are `McpBindError`, exit 1, no listen. `--bind` without `--port` is argv exit 2. `--port` without `--bind` is argv exit 2. Port is an integer `1..65535` (not `0`).

`--rotate-token` without `--bind` is argv exit 2.

No phrase. `require_operator` is not called. Safe mode does not deny `mcp`.

Exit codes: `0` clean stdio EOF or HTTP server stopped; `1` bind refuse / token write failure; `2` argv; `3` unused (no phrase on this command).

Projection layout gains one gitignored file:

```
projection/
  projection.sqlite
  projection.manifest.json
  .mcp-token          # HTTP only; 0600; never Git
  .staging/
  .project.lock
```

`.gitignore` gains `**/.mcp-token`. Creating the token file may `mkdir` the projection directory. It must not create `projection.sqlite`.

## 5. Protocol

JSON-RPC 2.0. MCP protocol version **`2025-03-26`**. No `mcp` Python package.

Supported methods:

| Method | Kind | Behavior |
|---|---|---|
| `initialize` | request | Return `protocolVersion: "2025-03-26"`, `capabilities: { "tools": { "listChanged": false } }`, `serverInfo: { "name": "ironledger", "version": <package version> }`. If the client `protocolVersion` is not `2025-03-26`, still return `2025-03-26` (server's version) per MCP lifecycle; do not crash. |
| `notifications/initialized` | notification | No-op. No JSON-RPC response. |
| `ping` | request | Empty result `{}`. |
| `tools/list` | request | The three tools in section 6, stable order `search`, `balances`, `projection_status`. |
| `tools/call` | request | Dispatch section 6. Unknown `name` → MCP tool error (`isError: true`), no query, no mutation. |
| `notifications/cancelled` | notification | No-op. |

Everything else, including `resources/*`, `prompts/*`, `sampling/*`, `roots/*`, `logging/*`, `completion/*`, and any name that looks like `compile` / `import` / `review` / `project` / `rule`: JSON-RPC `-32601` Method not found (protocol methods) or `tools/call` `isError` (unknown tool name). No code path behind those names reaches ingest, review, compile, or `rebuild_projection`.

Batches (JSON arrays) are rejected: JSON-RPC `-32600` Invalid Request. Messages MUST NOT contain embedded newlines.

Business errors (stale projection, empty query, invalid FTS, limit out of range) are `tools/call` results with `isError: true` and `content: [{ "type": "text", "text": <Phase 4 error formula> }]`, not JSON-RPC transport errors, and not Python tracebacks on stdout.

Stdout (stdio) contains only newline-delimited JSON-RPC messages. Logs go to stderr and must not include the bearer token or `Authorization` header.

## 6. Tools

Process argv supplies `--ledger-dir` / `--projection-dir` / `--db`. Tool arguments MUST NOT accept filesystem paths. That is the Phase 5 traversal control.

### `search`

Arguments (JSON Schema):

- `query` (string, required)
- `limit` (integer, optional, default 50, minimum 1, maximum 500)
- `offset` (integer, optional, default 0, minimum 0)

Calls `ironledger.project.query.assert_fresh` then `search`. Result content is one JSON text blob (pretty-printed, `sort_keys=True`) of an object:

```json
{
  "hits": [
    {
      "entry_date": "2026-09-01",
      "payee": "...",
      "narration": "...",
      "account": "Expenses:Food",
      "minor_units": 1234,
      "currency": "USD",
      "staged_transaction_id": "stx-1",
      "posting_id": "stx-1:contra"
    }
  ]
}
```

`minor_units` is JSON number (integer). Never a float. Never a decimal string in this phase (integers are the Phase 4 CLI contract).

### `balances`

No arguments. Calls `assert_fresh` then `balances`. Result:

```json
{
  "balances": [
    {
      "account": "Assets:Checking",
      "minor_units": -1234,
      "currency": "USD",
      "minor_unit_scale": 2
    }
  ]
}
```

One object per `proj_balances` row, sorted by account then currency. Two currencies for one account are two objects. Never summed.

### `projection_status`

No arguments. Same information as `ironledger project status --json` with `--db` present: `status` (`ok` / `mismatch` / `missing`), `ledger_output_hash` when known, `hash_matches_files`, `hash_matches_compile`, `latest_run`. Does not call `require_operator`. Does not take a lock. Missing projection is `status: "missing"`, `isError: false` (status is a valid answer, matching CLI exit 0).

Lift `_live_project_status` out of `cli/__main__.py` into `project.query` (or a sibling `project.status`) so MCP does not import the CLI package. The CLI command becomes a caller of that function. Behavior of `project status` does not change.

## 7. stdio transport

Client launches `python -m ironledger.cli mcp --db … --ledger-dir …` as a subprocess.

- Read UTF-8 lines from stdin. Each line is one JSON-RPC message.
- Write one JSON-RPC message per line to stdout for each request. Notifications produce no stdout line.
- EOF on stdin: exit 0.
- Parse failure: JSON-RPC `-32700` with `id` null, then continue (do not crash the process).

## 8. Streamable HTTP transport

Protocol: MCP 2025-03-26 Streamable HTTP, loopback only. Implemented with `http.server` (stdlib). Single-threaded is enough.

- MCP endpoint path is exactly `/mcp`. Other paths: HTTP 404, no JSON-RPC body required.
- POST `/mcp`: JSON-RPC in, JSON-RPC out, `Content-Type: application/json`. This phase does **not** open SSE streams. POST of a notification (no `id`) → HTTP 202 empty body.
- GET `/mcp`: HTTP 405 Method Not Allowed (server does not offer an SSE listen stream; the spec allows this).
- DELETE `/mcp`: HTTP 405 (no session teardown).
- No `Mcp-Session-Id`. No resumability. No HTTP+SSE 2024-11-05 compat endpoints.

Security (MCP Streamable HTTP MUST/SHOULD, tightened). **Handler order is locked.** Do not reorder. A rebinding client must receive 403 before 401 or 413:

1. Bind socket to the `--bind` address only. `getsockname()[0]` is `127.0.0.1` or `::1`.
2. Path and method: only POST `/mcp` continues (GET `/mcp` → 405; other path → 404).
3. `Host` header required and must be loopback: `127.0.0.1`, `127.0.0.1:<port>`, `[::1]`, `[::1]:<port>`, `localhost`, `localhost:<port>`. Anything else → HTTP 403, no query, no body read.
4. `Origin` header: if present (including empty), it must be one of `http://127.0.0.1`, `http://127.0.0.1:<port>`, `http://localhost`, `http://localhost:<port>`, `http://[::1]`, `http://[::1]:<port>`, or `null`. Anything else → HTTP 403, no body read. Missing `Origin` is allowed (non-browser clients).
5. Request body cap: **1 MiB**. Require `Content-Length` on POST `/mcp`. If `Content-Length` is missing, not a non-negative integer, or greater than 1,048,576, or `Transfer-Encoding` includes `chunked`, respond **413**, do not read the body, do not call `handle_message`, do not write the body into an audit event. A body that is shorter than `Content-Length` is a connection error (close; no tool result). This cap is HTTP-only; stdio is one JSON object per newline.
6. `Authorization: Bearer <token>` required on every POST `/mcp`. Missing, malformed, or wrong token → HTTP 401, `WWW-Authenticate: Bearer`, body not a tool result, no query. Compare with `hmac.compare_digest` against the hex token. Timing-safe. Do not distinguish "no file" from "wrong token" in the response body. 401 is only legal after Host and Origin have already passed.
7. Then read at most `Content-Length` bytes and pass them to `handle_message`.
8. Do not send `Access-Control-Allow-Origin: *`. OPTIONS may 405.

Token file: 32 bytes from `secrets.token_bytes(32)`, written as lowercase hex, POSIX `chmod 0o600` after create and after rotate. On Windows, still call `chmod`; do not fail the phase if the OS only implements a subset of POSIX bits. Tests on POSIX assert `stat.st_mode & 0o777 == 0o600`. Windows tests assert the file exists and the HTTP 401/200 contract; they do not assert Unix mode.

On first HTTP bind, if the token file is missing, create it and print **only** this line to stderr: `mcp token written to <path>` (path, not secret). On reuse, print nothing about the token.

## 9. Audit

Every `tools/call` that is a request (not a parse error) appends one `audit_events` row on `--db`:

- `actor`: `"operator"`
- `action`: `"mcp search"` / `"mcp balances"` / `"mcp status"` / `"mcp tools/call"`
- `target`: the tool name as requested (unknown names still recorded)
- `result`: `"ok"` if `isError` is false; `"error"` if `isError` is true (stale, bad query, unknown tool)
- `input_hash`: projection `ledger_output_hash` when the projection opened; otherwise null
- Do **not** store the FTS query string, tool arguments JSON, bearer token, or `Authorization` header

HTTP 401/403 append `action="mcp auth"`, `target="http"`, `result="denied"`. One event per rejected request.

stdio does not emit `mcp auth` events.

Audit write failure must not return projection rows: fail the tool with `isError` (or abort the HTTP request with 500 after 401 is already sent? 401 path: try audit, still return 401 even if audit fails). Tool-call path: if audit insert fails, `isError: true`, no hits.

## 10. Module layout

```
src/ironledger/mcp/
  __init__.py
  errors.py      # McpError, McpBindError, McpAuthError, McpProtocolError + formatters
  bind.py        # assert_loopback(host)
  token.py       # load_or_create_token, rotate_token, verify_bearer
  protocol.py    # JSON-RPC parse/serialize + initialize/ping/tools/list/tools/call
  tools.py       # allowlist, JSON Schema, dispatch into project.query
  stdio.py       # newline JSON-RPC loop
  http.py        # Streamable HTTP handler
```

CLI wiring in `cli/__main__.py`. No new phrase in `cli/auth.py`. No renderer needed beyond JSON tool content.

Do not collapse this layout.

## 11. Out of scope

- Date range, account-prefix filters, category rollups, runway, health.
- Mutation-capable MCP tools; compile/import/review/project/rule behind MCP.
- Official `mcp` Python SDK or any new runtime dependency.
- SSE listen streams, session IDs, HTTP+SSE 2024-11-05, JSON-RPC batches.
- Binding `0.0.0.0`, Tailscale/VPN, or any non-loopback address (Phase 8).
- WebAuthn, capability-token expiry/nonce (reserved for a future mutation service).
- Automatic projection rebuild from a tool call.
- Git add/commit/push of `ledger/` or `projection/`.
- SimpleFIN, RAG/NotebookLM, mobile.

## 12. Test contract for the Phase 5 exit gate

All items below are gate-blocking. Named tests in `tests/test_phase5_exit_contract.py` plus the focused modules they call.

1. `tools/list` names are exactly `["search", "balances", "projection_status"]` in that order. JSON Schema for `search` requires `query` and caps `limit` at 500.
2. `tools/call` `search` against a rebuilt projection returns the same `posting_id` set as `ironledger.project.query.search` for the same query/limit/offset. `minor_units` in the JSON is an integer (JSON number, `isinstance(..., int)` after parse).
3. `tools/call` `balances` matches `query.balances` row-for-row: account, minor_units, currency, minor_unit_scale. Two currencies on two rows; never one summed number.
4. `tools/call` `projection_status` on a missing projection returns `status: "missing"` with `isError: false`. After rebuild, `status: "ok"` and `hash_matches_files: true`.
5. Stale projection (new compile hash, no `project`): `search` and `balances` return `isError: true`; text includes short hashes, `--ledger-dir`, and `--confirm "authorize project"`. Live projection file is not written.
6. Empty `query` and invalid FTS syntax: `isError: true`, error formula, no traceback on stdout.
7. `tools/call` name `compile` / `import` / `review` / `project` / `rule` / `not-a-tool`: `isError: true`, no `rebuild_projection`, no ingest, no compile journal row, no phrase prompt. `tools/list` still does not mention them.
8. JSON-RPC method `resources/list` (and `prompts/list`) returns `-32601`. No resource payload.
9. stdio: one initialize request in, one initialize result out; stdout has no non-JSON prefix (no banner). A second process using stdio (no `--bind`) has no listening TCP socket on 127.0.0.1 (server object not started / bind not called).
10. `--bind 0.0.0.0 --port <n>` exits 1, `McpBindError` (or formatted bind error), no socket. Same for `--bind 192.168.1.1` and `--bind localhost`.
11. `--bind 127.0.0.1 --port <ephemeral>`: `getsockname` address is `127.0.0.1`. POST `/mcp` without `Authorization` is 401. POST with the token from `.mcp-token` can `initialize` and `tools/list`.
12. Wrong bearer token → 401, same body shape as missing token; `search` is not executed (spy or empty projection that would have hit if called).
13. POST `/mcp` with `Origin: https://evil.example` → 403 even with a valid token. POST with no Origin and valid token succeeds.
14. GET `/mcp` → 405. POST `/other` → 404.
15. First HTTP bind creates `.mcp-token` at 64 hex chars; POSIX mode `0o600`. `--rotate-token` changes the file bytes; the old token then 401s; the new token works.
16. `.mcp-token` is gitignored (`**/.mcp-token` matches). A helper or grep over `.gitignore` plus a test that the path is ignored by `pathspec` or by `git check-ignore` when git is available; if `git check-ignore` is used it must not require a remote.
17. Safe mode enabled: `mcp` stdio `tools/list` still succeeds. `require_operator` is not called (search/balances/status tools do not go through `cli.auth`).
18. `tools/call` `search` appends `audit_events` with `action="mcp search"`, `result="ok"`, and the FTS query string does not appear in `target` or any hash field. HTTP 401 appends `action="mcp auth"`, `result="denied"`.
19. No source file under `src/ironledger` contains `import mcp` or `from mcp`. `pyproject.toml` runtime `dependencies` remains `["ofxtools==1.1.1"]`.
20. Full suite does not drop below the Phase 4 baseline (418 passed / 2 skipped on this host without `bean-check` on PATH; 419 / 1 with). Phase 5 tests only add.
21. `python -m ironledger.cli --help` lists `mcp`. `--db` after `mcp` parses (same parent/subcommand dest split as `project`).
22. `--bind` without `--port`, `--port` without `--bind`, `--rotate-token` without `--bind`: exit 2.
23. JSON-RPC batch (a JSON array) returns `-32600`. Embedded newline inside a stdio line is a parse error (`-32700` or protocol error), process stays up.
24. Host header `evil.example:8765` on POST `/mcp` with a valid token → 403.
25. POST `/mcp` with `Content-Length` > 1048576, or with `Transfer-Encoding: chunked`, returns 413. `handle_message` is not invoked. The audit stream does not contain the request body. 413 is only reached when Host and Origin already passed.
26. POST `/mcp` with `Origin: https://evil.example` and a valid bearer token → 403 (not 401, not 200). POST with `Host: evil.example:8765` and no Authorization header → 403 (not 401).

## 13. Open items carried into the plan, not this spec

- Exact stderr wording besides the one token-path line.
- Whether `ping` is advertised in capabilities (it is a protocol method; no need to list it as a tool).
- Numbered performance gate: none. A local stdio round-trip on the Phase 4 sample ledger must finish in the same process that compiled it.
- Windows ACL beyond `chmod 0o600` best-effort.
- Public repo / LICENSE / community (D-0).

## 14. Approval gate

Phase 5 requires operator review of this design, then a TDD implementation plan, then operator approval of that plan in the transcript before any code. Phase 4 remains the projection authority. Any change to Beancount authority, evidence retention, default read-only access, non-loopback network exposure, mutation-capable MCP tools, or automatic publication requires a design amendment and renewed approval.
