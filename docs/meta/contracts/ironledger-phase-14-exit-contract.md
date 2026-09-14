# Phase 14 Exit Contract: IronLedger MCP Tool Surface Expansion (Tax & Gains)

**Milestone Version**: `v0.14.0`  
**Phase Name**: Phase 14 — Model Context Protocol (MCP) Tool Surface Expansion: Portfolio Tax & Gains Tools  
**Status**: SEALED & COMPLIANT  
**Date**: 2026-09-13  

---

## 1. Architectural Contract & Invariants

Phase 14 delivers read-only tax & gains Model Context Protocol (MCP) tool exposure for IronLedger across stdio and HTTP loopback transports, enabling autonomous agents (Claude Code, Codex, Antigravity) to query portfolio cost basis, realized/unrealized gains, open tax lots, and simulate lot disposal scenarios.

### Invariant I: Exact Rational Arithmetic & Static Zero-Float Guarantee
1. All capital gains summaries, unrealized gain calculations, lot inventory balances, and simulated disposal allocations enforce exact rational integer arithmetic using minor currency units.
2. Zero floating-point division (`ast.Div`) or float conversions in all tax valuation and MCP modules (`src/ironledger/valuation/lots.py`, `src/ironledger/valuation/models.py`, `src/ironledger/valuation/engine.py`, `src/ironledger/mcp/tools.py`).
3. Formally verified by AST static analysis visitors in `tests/test_phase14_exit_contract.py`.

### Invariant II: Zero Runtime `import beancount`
1. Zero runtime dependencies on `beancount` across all MCP tool dispatchers, serialization handlers, and valuation query engines.
2. Formally verified by AST static analysis visitors in `tests/test_phase14_exit_contract.py`.

### Invariant III: Pure Read-Only Simulation & State Immutability
1. `preview_lot_disposal` operates strictly on detached in-memory deep-copies of open lot records without mutating SQLite state, ledger postings, or `open_lots` projection tables.
2. Verified by database snapshot hash integrity checks in `tests/test_mcp_tax_tools.py`.

### Invariant IV: Structured Fail-Closed Validation & Security Audit Logging
1. All MCP tool invocations validate inputs fail-closed (invalid date formats, non-positive quantities, unknown strategies, negative proceeds).
2. Every tool invocation logs structured events to `audit_events` via `_audit_tool` with tenant ledger context and sanitization of any credential payloads.

---

## 2. Deliverable Verification Matrix

| Track | Deliverable | Location | Status |
|---|---|---|---|
| **Track 14.1** | In-Memory Lot Disposal Simulation Engine | `src/ironledger/valuation/lots.py` (`simulate_lot_disposal`) | VERIFIED |
| **Track 14.2** | MCP Tool Declarations & JSON Schema Definitions | `src/ironledger/mcp/tools.py` (`TAX_TOOL_NAMES`, `list_tools`) | VERIFIED |
| **Track 14.3** | Read-Only MCP Tool Handlers (`gains`, `lots`, `unrealized`, `preview`) | `src/ironledger/mcp/tools.py` (`call_tool`) | VERIFIED |
| **Track 14.4** | Dual Transport Compatibility (stdio + HTTP loopback) | `src/ironledger/mcp/stdio.py`, `src/ironledger/mcp/http.py` | VERIFIED |
| **Track 14.5** | Unit & Integration Test Suite | `tests/test_mcp_tax_tools.py` | VERIFIED |
| **Track 14.6** | AST Invariant & Multi-Lot E2E Exit Contract Tests | `tests/test_phase14_exit_contract.py` | VERIFIED |

---

## 3. Exit Gate Approval

The Phase 14 IronLedger MCP Tool Surface Expansion meets all technical writing heuristics, zero-float guarantees, zero-beancount import rules, and read-only transactional integrity standards with 100% test pass rate across the full 1000-test repository suite.
