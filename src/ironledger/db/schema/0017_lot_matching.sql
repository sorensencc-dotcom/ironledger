-- Migration 0017: deterministic portfolio lot projections

ALTER TABLE ledger_postings ADD COLUMN cost_numerator INTEGER;
ALTER TABLE ledger_postings ADD COLUMN cost_denominator INTEGER;
ALTER TABLE ledger_postings ADD COLUMN cost_currency TEXT;
ALTER TABLE ledger_postings ADD COLUMN lot_date TEXT;
ALTER TABLE ledger_postings ADD COLUMN lot_label TEXT;

CREATE TABLE open_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_key TEXT NOT NULL UNIQUE,
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    account TEXT NOT NULL,
    commodity TEXT NOT NULL,
    acquisition_date TEXT NOT NULL,
    original_units_minor INTEGER NOT NULL,
    remaining_units_minor INTEGER NOT NULL,
    unit_scale INTEGER NOT NULL DEFAULT 4,
    native_cost_numerator INTEGER NOT NULL,
    native_cost_denominator INTEGER NOT NULL,
    native_cost_currency TEXT NOT NULL,
    functional_currency TEXT NOT NULL,
    functional_unit_cost_numerator INTEGER NOT NULL,
    functional_unit_cost_denominator INTEGER NOT NULL,
    functional_cost_basis_minor INTEGER NOT NULL,
    remaining_functional_cost_basis_minor INTEGER NOT NULL,
    lot_label TEXT,
    source_lot_key TEXT REFERENCES open_lots(lot_key),
    origin_account TEXT,
    created_posting_id TEXT NOT NULL REFERENCES ledger_postings(ledger_posting_id),
    created_entry_id TEXT NOT NULL REFERENCES ledger_entries(ledger_entry_id),
    CHECK (original_units_minor > 0),
    CHECK (remaining_units_minor >= 0 AND remaining_units_minor <= original_units_minor),
    CHECK (remaining_functional_cost_basis_minor >= 0),
    CHECK (native_cost_denominator > 0 AND functional_unit_cost_denominator > 0)
) STRICT;

CREATE INDEX idx_open_lots_search
ON open_lots (ledger_id, account, commodity, remaining_units_minor, acquisition_date);

CREATE TABLE lot_disposal_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_key TEXT NOT NULL UNIQUE,
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    account TEXT NOT NULL,
    commodity TEXT NOT NULL,
    disposal_date TEXT NOT NULL,
    acquisition_date TEXT NOT NULL,
    units_disposed_minor INTEGER NOT NULL CHECK (units_disposed_minor > 0),
    unit_scale INTEGER NOT NULL DEFAULT 4,
    holding_period_days INTEGER NOT NULL CHECK (holding_period_days >= 0),
    term_classification TEXT NOT NULL CHECK(term_classification IN ('SHORT_TERM', 'LONG_TERM')),
    native_proceeds_minor INTEGER NOT NULL,
    native_proceeds_currency TEXT NOT NULL,
    native_cost_basis_minor INTEGER NOT NULL,
    native_cost_currency TEXT NOT NULL,
    native_realized_gain_minor INTEGER,
    functional_proceeds_minor INTEGER NOT NULL,
    functional_cost_basis_minor INTEGER NOT NULL,
    functional_realized_gain_minor INTEGER NOT NULL,
    functional_currency TEXT NOT NULL,
    strategy_applied TEXT NOT NULL CHECK(strategy_applied IN ('FIFO', 'LIFO', 'HIFO', 'SPEC_ID', 'SPEC_ID_PARTIAL_FIFO')),
    requested_lot_identifier TEXT,
    open_lot_key TEXT NOT NULL REFERENCES open_lots(lot_key),
    closing_posting_id TEXT NOT NULL REFERENCES ledger_postings(ledger_posting_id),
    closing_entry_id TEXT NOT NULL REFERENCES ledger_entries(ledger_entry_id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
) STRICT;

CREATE INDEX idx_allocations_tax
ON lot_disposal_allocations (ledger_id, disposal_date, term_classification, commodity);

CREATE TABLE portfolio_holdings_cache (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    account TEXT NOT NULL,
    commodity TEXT NOT NULL,
    total_units_minor INTEGER NOT NULL,
    unit_scale INTEGER NOT NULL DEFAULT 4,
    functional_currency TEXT NOT NULL,
    total_cost_basis_minor INTEGER NOT NULL,
    latest_price_numerator INTEGER NOT NULL,
    latest_price_denominator INTEGER NOT NULL,
    market_value_minor INTEGER NOT NULL,
    unrealized_gain_minor INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    PRIMARY KEY (ledger_id, account, commodity)
) STRICT;
