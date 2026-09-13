# Phase 14 Handoff: IronLedger MCP Tool Surface Expansion (Tax & Gains Tools)

## Context & Objective
Phase 13 delivered exact rational cost basis tracking, FIFO/LIFO/HIFO lot matching, SQLite projections (`open_lots`, `lot_disposal_allocations`), analytics REST endpoints, Form 8949 CSV export, Operator Workbench UI, live HTTP price feeds (Yahoo Finance & CoinGecko), and 24h trending signals.

The objective of **Phase 14** is to expose this rich portfolio valuation, lot inventory, and capital gains subsystem directly to autonomous coding agents (Claude Code, Codex, Antigravity) via IronLedger's built-in Model Context Protocol (MCP) server.

---

## Target MCP Tools (Read-Only)

1. **`get_capital_gains_summary`**:
   - **Inputs**: `ledger_id` (default: `"default"`), `tax_year` (optional `int`), `term` (optional `"SHORT_TERM" | "LONG_TERM"`), `account` (optional `str`), `commodity` (optional `str`).
   - **Outputs**: Total realized gain/loss (minor units + formatted decimal), breakdown by short-term vs long-term, proceeds, cost basis, and count of taxable disposal events.

2. **`list_open_tax_lots`**:
   - **Inputs**: `ledger_id` (default: `"default"`), `account` (optional `str`), `commodity` (optional `str`).
   - **Outputs**: List of open lots with `lot_id`, `acquisition_date`, `commodity`, `account`, `quantity` (fraction + decimal), `unit_cost` (fraction + decimal), `current_basis_minor`, `market_value_minor`, and `unrealized_gain_loss_minor`.

3. **`get_unrealized_gains`**:
   - **Inputs**: `ledger_id` (default: `"default"`), `commodity` (optional `str`).
   - **Outputs**: Summary of mark-to-market unrealized gains/losses across all active portfolio positions based on latest polled price directives.

4. **`preview_lot_disposal`**:
   - **Inputs**: `commodity` (`str`), `quantity` (`str` or `int/den`), `proceeds_rate` (`str`), `strategy` (`"FIFO" | "LIFO" | "HIFO"`, default: `"FIFO"`), `disposal_date` (`str`).
   - **Outputs**: Simulation of disposal allocations across open lots, estimated realized short-term vs long-term gain/loss, and remaining lot inventory without mutating the database or ledger.

---

## Architecture & Constraints
- **Zero Runtime Beancount**: Enforce zero `import beancount` globally across all MCP dispatchers.
- **Pure Integer Rational Arithmetic**: All calculations must use integer numerators/denominators and Banker's rounding.
- **Strict Read-Only Fencing**: No write operations or state mutations allowed in these tool handlers.
- **Dual Transport Support**: Available seamlessly over both stdio transport (local agent sub-processes) and HTTP loopback transport (`127.0.0.1:8765`).
- **Audit Logging**: Every MCP query records an entry in `mcp_audit_log` or SQLite audit stream without leaking sensitive credentials.

---

## File Targets for Phase 14
- `src/ironledger/mcp/tools.py` — Schema definitions and dispatcher handlers.
- `src/ironledger/valuation/lots.py` — Simulation preview helper for `preview_lot_disposal`.
- `tests/test_mcp_tax_tools.py` — Dedicated test suite validating schemas, tool calls, simulation accuracy, and error handling.
- `docs/meta/contracts/ironledger-phase-14-exit-contract.md` — Contract verification.
