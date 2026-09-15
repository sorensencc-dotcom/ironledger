# IronLedger Project Status

## Active Goal
Phase 15 — Inbox attach + PDF statement wedge: later evidence hangs off an existing economic event after operator confirm. Packaging waits.


## Milestone Status: Inbox Attach + PDF Statement Wedge v0.15.0
- **Preceding Baseline:** MCP Tax & Gains Tools v0.14.0 (1000 passed, 4 skipped).
- **Regression Invariant:** 1023 passed, 4 skipped (51.56s).
- **Current Milestone:** Phase 15 inbox attach. Later CSV/OFX/PDF rows propose attach to an existing economic event. Operator confirms in the inbox. No second posting. PDF text-layer `example-card` profile. SimpleFIN ingest unchanged (match-target only).


## Completed Work
1. **In-Memory Lot Disposal Simulation Engine (`src/ironledger/valuation/lots.py`)**:
   - Implemented `simulate_lot_disposal()` function supporting `FIFO`, `LIFO`, and `HIFO` lot matching strategies.
   - Operates strictly on detached in-memory deep-copies of `open_lots` without mutating SQLite tables or ledger state.
   - Preserves basis residue conservation and integer rational precision across partial lot liquidations.

2. **MCP Tool Schemas & Tool Registry (`src/ironledger/mcp/tools.py`)**:
   - Registered `TAX_TOOL_NAMES = ('get_capital_gains_summary', 'list_open_tax_lots', 'get_unrealized_gains', 'preview_lot_disposal')` in `ALL_TOOL_NAMES`.
   - Added schema definitions with `include_tax` parameter in `list_tools(include_analytics=False, include_tax=False, include_all=False)`.
   - Implemented full parameter validation and schema contracts for capital gains summary filters, open tax lot queries, unrealized gain calculations, and disposal simulations.

3. **Read-Only MCP Tool Dispatchers & Handlers (`src/ironledger/mcp/tools.py`)**:
   - `get_capital_gains_summary`: Dispatches gain/loss aggregation filterable by tax year, term, account, and commodity with formatted decimal display strings.
   - `list_open_tax_lots`: Returns active open tax lots with cost basis, remaining units, acquisition dates, and source posting IDs.
   - `get_unrealized_gains`: Recomputes valuation cost basis vs mark-to-market prices from price directives and returns per-position and aggregate unrealized gains.
   - `preview_lot_disposal`: Runs pure simulation of candidate sales, returning allocated lots, holding period classifications, proceeds, cost basis, and projected realized gain/loss.

4. **Security Audit Logging & Dual Transport Compatibility (`src/ironledger/mcp/tools.py`, `src/ironledger/mcp/stdio.py`, `src/ironledger/mcp/http.py`)**:
   - Enforced fail-closed parameter validation and sanitization across all tax tool dispatchers.
   - Routed execution through `_audit_tool()` to record immutable audit events without leaking sensitive payloads.
   - Verified seamless execution across both standard I/O (`stdio.py`) and loopback HTTP JSON-RPC (`http.py`) MCP transports.

5. **Phase 14 Integration & Exit Contract Test Suite (`tests/test_mcp_tax_tools.py`, `tests/test_phase14_exit_contract.py`)**:
   - Comprehensive unit and integration test coverage for all 4 tax tools, strategy variations (FIFO, LIFO, HIFO), invalid inputs, and dual transport mechanisms.
   - AST static analysis verification enforcing zero floating-point division (`ast.Div`) and zero runtime `import beancount`.
   - End-to-end multi-lot lifecycle testing asserting exact minor unit calculations and database immutability.
   - Sealed exit contract at `docs/meta/contracts/ironledger-phase-14-exit-contract.md`.

## Core Architectural Invariants Maintained
- **Plaintext Ground Truth:** Plaintext Beancount files remain the sole financial authority.
- **Decoupled Runtime:** Zero runtime `import beancount` enforced via static AST visitor.
- **Pure Integer Arithmetic:** Exact rational arithmetic without float representation or drift.
- **Cost Basis Conservation:** Exact integer balance conservation across partial lot liquidations.
- **Envelope Encryption:** AES-256-GCM with separate IV/auth tags and zero plaintext payload leakage.
- **Append-Only Immutability:** SQLite triggers guarding outbox, audit, mutation, and governance event streams.
- **Multi-Tenant Boundaries:** Relational composite keys and tenant registries enforcing strict ledger isolation.

## Next Action
Operator try-on of one real PDF profile against live SimpleFIN charges (not packaging, not OCR). Resume: `docs/meta/plans/ironledger-phase-15-handoff.md`.



