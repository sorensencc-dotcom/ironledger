# IronLedger Phase 5 MCP handoff

**Date:** 2026-09-09  
**Status:** Spec + plan operator-approved. Implementation **paused** (“do not implement yet”). No `src/ironledger/mcp/`.  
**Repo:** `C:\dev\IronLedger`  
**HEAD:** `980ef05` (`main`) — `docs(ironledger): record Phase 5 MCP plan approval, implementation paused`  
**Author:** `Iron-Hammer <iron-hammer@ironledger.local>`  
**D-0:** no remote, do not push.

## Resume in one command

When the operator says implement: **do not code on current `main`**. Current `main` still contains the FastAPI/React workbench (POST `/api/compile`, CORS, Docker, Phase 6 gov docs) **on top of** the MCP spec/plan. Eng-review 1A quarantined that workbench; later sessions continued it on `main`.

```text
git worktree add .worktrees/ironledger-phase-5-mcp -b ironledger/phase-5-mcp d6632b6
# copy or cherry-pick 980ef05's two docs onto that branch, then SDD the plan
```

Phase 4 close: `d6632b6`. Workbench snapshot: branch `ironledger/phase-5-workbench` (do not merge as Phase 5).

## Canonical docs (read both)

| Role | Path |
|------|------|
| Spec (authority) | `docs/meta/specs/ironledger-phase-5-mcp-design.md` |
| TDD plan (12 tasks + T-R1..4) | `docs/meta/plans/ironledger-phase-5-plan.md` |
| Architecture (Phase 5 = read-only MCP) | `C:\dev\docs\meta\plans\ironledger-implementation-plan.md` |
| Phase 4 exit | `docs/meta/phases/ironledger-phase-4-evidence.md` |

Execute with superpowers **subagent-driven-development**. Tests: `python -m pytest -q` from repo root. Baseline at Phase 4 close: 418 passed / 2 skipped (no bean-check on PATH).

## Locked product

- Tools only: `search`, `balances`, `projection_status`. Wrap `project.query`. No compile/import/review/project/rule tools.
- stdio default (`sys.stdin.buffer`). `--bind 127.0.0.1|::1 --port 1..65535` for HTTP. Not both in one process.
- HTTP order: path → Host 403 → Origin 403 → Content-Type 415 → 413 (1 MiB, no chunked) → Bearer 401 → read (5s timeout).
- Token: `projection/.mcp-token`, 64 hex, tmp+`os.replace`, `chmod 0600` **every load**.
- `--db` required on `mcp` for `audit_events` only. Query never opens `--db`. Order: query → audit → serialize.
- No `mcp` PyPI package. No mutation. Safe mode leaves MCP up.
- Contract items **1–35** (item 20 = full suite).

## Do not

- Implement until the operator says so.
- Merge `ironledger/phase-5-workbench` as Phase 5.
- Reset `main` again without asking (1A reset was later overwritten).
- Add FastAPI/React as this phase.
- Push.

## Next session first steps

1. Confirm operator wants **implement**.
2. Isolated worktree from `d6632b6` + MCP spec/plan.
3. SDD Task 1 (`mcp/errors.py`). Do not skip TDD red.
4. After Task 12: Phase 5 evidence doc, `[tool.ironledger] phase = 5`.
