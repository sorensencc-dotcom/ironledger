# Review: IronLedger Phase 5 MCP

Reviewed: 2026-09-09T00:00:00Z
Reviewer: ijfw-review
Domain: software
Range: `799c203^..0b63ec9` on local `main` (`C:\dev\IronLedger`)
HEAD: `0b63ec9032174ff9197413be3a901170bd70dc94`

## Summary

The 12 TDD commits exist, match the planned messages and author (`Iron-Hammer`), stay local (D-0, no remote), and the claimed pytest counts are real: **34 exit-contract tests pass**, **63 MCP-focused tests pass (2 skipped)**, **full suite 521 passed / 4 skipped**. The eight-module layout, loopback bind literals, token tmp+replace+chmod, JSON-RPC subset, and no-`mcp`-SDK invariant are in place.

Phase 5 is **not** complete as an operator-facing ship. `python -m ironledger.cli mcp` — the invocation in the spec and README — raises `NameError: name '_cmd_mcp' is not defined` because `_cmd_mcp` is defined after `if __name__ == "__main__"`. The HTTP 5s body-read timeout path raises a second `NameError` (`timeout` is not imported). The README documents a `--transport` flag the parser does not implement.

## BLOCK findings (must-fix)

- `src/ironledger/cli/__main__.py:921-924`: [BLOCK] `_cmd_mcp` is defined after `if __name__ == "__main__": raise SystemExit(main())`. `python -m ironledger.cli mcp` (spec §4 and README) raises `NameError: name '_cmd_mcp' is not defined`. Tests import the module (`__name__ != "__main__"`), so they never see it. Console-script `ironledger mcp` works because the import finishes. Move `_cmd_mcp` above the main guard.
- `src/ironledger/mcp/http.py:156`: [BLOCK] `except (timeout, socket.timeout, OSError)` evaluates undefined `timeout`. A 5s body-read timeout (spec §8 step 7, contract 32) becomes `NameError` and can crash the handler thread instead of closing with no `handle_message`. Use `except (TimeoutError, OSError)`.

## FLAG findings (should-discuss)

- `README.md:70-73`: [FLAG] Documents `mcp --transport stdio` and `mcp --transport http`. Parser has no `--transport`; copy-paste is argv exit 2. Spec/plan: no `--bind` → stdio; `--bind 127.0.0.1 --port N` → HTTP.
- `src/ironledger/mcp/http.py:31-45`: [FLAG] `_is_allowed_origin` uses `startswith(prefix + ':')`. `http://127.0.0.1:8765.evil.com` returns True (probed). Parse origin with `urllib.parse.urlparse` and require hostname in `{127.0.0.1, localhost, ::1}` and scheme `http` (or `null`).
- `src/ironledger/mcp/http.py:23-29`: [FLAG] `_is_loopback_host` takes everything through the first `]` as the host, then `split(':')[0]` for the rest. Probed True: `[::1]evil.example`, `[::1]:80.evil.com`, `localhost:8765.evil.com`, `127.0.0.1:80.evil.com`. Unbracketed `::1` never matches (`split(':')[0]` is empty; `'::1'` in `ALLOWED_HOSTS` is dead). After `]`, allow only EOS or `:<digits>`; for v4/`localhost`, require the port (if present) to be all digits.
- `src/ironledger/mcp/http.py:198-244`: [FLAG] `HTTPServer.address_family` is `AF_INET`. `--bind ::1` (spec-legal) cannot listen. Set `AF_INET6` when host is `::1`. Catch bind `OSError` in `_cmd_mcp` and return 1.
- `src/ironledger/mcp/http.py:149-158` / `tests/test_phase5_exit_contract.py:622-641`: [FLAG] Contract 32 does not spy `handle_message`, does not wait 5s, and closes the client after 0.5s. The NameError on timeout is untested. Assert `handle_message` is not called and keep the socket open across the 5s timeout.
- `src/ironledger/mcp/tools.py:138-139`: [FLAG] Unexpected exceptions from `search()`/`balances()` become `isError` text `Audit failure: ` + `str(exc)` instead of JSON-RPC `-32603` / `internal error` (spec §5). Live probe: patched `search` raising `RuntimeError("secret")` returned a JSON-RPC **result** with `"secret"` in the tool text, not `-32603`. Item 27 monkeypatches `protocol.call_tool`, so that leak is invisible to the named test. Let non-`ProjectError` exceptions propagate to `handle_message`.
- `src/ironledger/cli/__main__.py:961-965`: [FLAG] HTTP `serve_forever` does not catch `KeyboardInterrupt`. Spec/plan: Ctrl+C → exit 0. Wrap with `except KeyboardInterrupt: return 0`.
- `tests/test_phase5_exit_contract.py` items 7, 15, 18, 25: [FLAG] Weak vs spec §12: no `rebuild_projection` spy (7); token rotation not proven over HTTP 401/200 (15); HTTP 401 audit not asserted (18); `Transfer-Encoding: chunked` not sent (25).
- `pyproject.toml:38-41` / `src/ironledger/__init__.py:4`: [FLAG] `phase = 5` but comments still say “MCP and network code remain out of scope”; package docstring still omits MCP.
- `docs/meta/phases/ironledger-phase-5-evidence.md`: [FLAG] Still describes Phase 5 as the FastAPI/React workbench. Eng-review lock 1A says Phase 5 is this MCP plan; workbench lives on `ironledger/phase-5-workbench`. Two Phase 5 identities on `main`.
- `src/ironledger/web/` + `web/`: [FLAG] Workbench is already on `main` (pre-MCP). It is a loopback HTTP mutation surface (compile/approve) without a bearer token. Out of the 12-commit MCP range, but it undercuts “MCP is the locked-down network surface.”

## NIT findings (polish)

- `src/ironledger/mcp/stdio.py:30-44`: [NIT] `readline(MAX+1)` then `len(line) > MAX_HTTP_BODY` rejects an exact 1 MiB line plus newline. Strip `\n` before comparing to `MAX_HTTP_BODY`.
- `.gitignore`: [NIT] `**/.mcp-token` is present; `**/.mcp-token.tmp` is not. A crash-before-replace leftover can be committed.
- `src/ironledger/mcp/http.py:2`: [NIT] Unused `import hmac` (verify is in `token.py`).
- `src/ironledger/mcp/http.py`: [NIT] OPTIONS is 501 (no `do_OPTIONS`); spec allows 405.
- `src/ironledger/mcp/errors.py:29`: [NIT] `format_auth_denied` is unused; HTTP 401 is header-only.

## PLAN COMPLETION AUDIT

Plan: `docs/meta/plans/ironledger-phase-5-plan.md`
Spec: `docs/meta/specs/ironledger-phase-5-mcp-design.md` §12

### Implementation items

- [DONE] T1 error types + formatters — `src/ironledger/mcp/errors.py`
- [DONE] T2 `assert_loopback` literals `127.0.0.1` / `::1` — `src/ironledger/mcp/bind.py`
- [DONE] T3 token 64-hex, tmp+`os.replace`, chmod 0600 every load — `src/ironledger/mcp/token.py` (Windows mode tests skipped as planned)
- [DONE] T4 lift `projection_status` — `src/ironledger/project/query.py:194`
- [DONE] T5 allowlist `search` / `balances` / `projection_status` — `src/ironledger/mcp/tools.py`
- [DONE] T6 JSON-RPC initialize / ping / tools/list / tools/call / `-32603` mask — `src/ironledger/mcp/protocol.py`
- [DONE] T7 binary stdio + 1 MiB cap — `src/ironledger/mcp/stdio.py` (off-by-one on exact 1 MiB)
- [PARTIAL] T8 Streamable HTTP — handler order matches spec; timeout except is broken; Origin allowlist is prefix-based
- [PARTIAL] T9 CLI `mcp` — dest-split `--db`, bind/port pairing, port 1..65535; `__main__` NameError; no KeyboardInterrupt
- [DONE] T10 audit query→audit→serialize; HTTP 403 `mcp auth` (HTTP 401 audit weakly tested)
- [PARTIAL] T11 gitignore `**/.mcp-token`, dep posture no SDK; README invents `--transport`
- [PARTIAL] T12 34 named contract tests; several assertions weaker than §12
- [DONE] T-R1 chmod on every load
- [DONE] T-R2 binary stdin 1 MiB
- [NOT DONE] T-R3 5s read timeout (NameError)
- [DONE] T-R4 query then audit then serialize

### Spec §12 (gate items)

DONE: 1–6, 8–14, 16–17, 19, 21–24, 26–31, 33–35 (with the weakness notes above).
PARTIAL / WEAK TEST: 7, 15, 18, 25, 32.
DONE (live this review): 20 — `python -m pytest -q` → **521 passed, 4 skipped**.

COMPLETION: 12/16 plan tasks DONE, 4 PARTIAL, 1 NOT DONE (T-R3). Spec items mostly present; two production NameErrors and a false README golden path block “complete.”

## Verification (this review)

```
python -m pytest tests/test_phase5_exit_contract.py tests/test_mcp_*.py tests/test_cli_mcp.py -q
→ 63 passed, 2 skipped in 8.72s

python -m pytest -q
→ 521 passed, 4 skipped in 20.24s

runpy.run_path('src/ironledger/cli/__main__.py', run_name='__main__') with argv mcp
→ NameError: name '_cmd_mcp' is not defined

_is_allowed_origin('http://127.0.0.1:8765.evil.com')
→ True
```

No remote. Branch `main`. Author `Iron-Hammer <iron-hammer@ironledger.local>` on all 12 commits.

## Assessment

**Ready to merge / call Phase 5 complete?** No — with fixes.

Move `_cmd_mcp` above the main guard, fix the HTTP `except` to `TimeoutError`, delete `--transport` from README, and tighten Origin parsing plus contract 32. After that the MCP slice matches the spec well enough to ratify. Do not treat the pre-existing workbench on `main` as this phase.
