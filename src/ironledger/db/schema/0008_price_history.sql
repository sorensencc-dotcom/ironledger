-- Migration 0008: Multi-Asset Valuation Engine & Price Directives Cache

CREATE TABLE IF NOT EXISTS ledgers (
    ledger_id TEXT PRIMARY KEY CHECK(length(ledger_id) >= 1 AND length(ledger_id) <= 64 AND ledger_id NOT GLOB '*[^a-zA-Z0-9_-]*'),
    name TEXT NOT NULL CHECK(length(name) >= 1 AND length(name) <= 128),
    root_account TEXT NOT NULL DEFAULT 'Assets' CHECK(length(root_account) >= 1),
    base_currency TEXT NOT NULL DEFAULT 'USD' CHECK(length(base_currency) >= 1 AND length(base_currency) <= 12 AND base_currency NOT GLOB '*[^A-Z0-9_.-]*'),
    storage_root TEXT NOT NULL DEFAULT '' CHECK(length(storage_root) <= 256),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
) STRICT;

INSERT OR IGNORE INTO ledgers (ledger_id, name, root_account, base_currency, storage_root)
VALUES ('default', 'Default Ledger', 'Assets', 'USD', 'default');

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER NOT NULL,
    ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    directive_date TEXT NOT NULL CHECK(length(directive_date) = 10 AND directive_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND directive_date NOT GLOB '*[^0-9-]*'),
    base_currency TEXT NOT NULL CHECK(length(base_currency) >= 1 AND length(base_currency) <= 12 AND base_currency NOT GLOB '*[^A-Z0-9_.-]*'),
    quote_currency TEXT NOT NULL CHECK(length(quote_currency) >= 1 AND length(quote_currency) <= 12 AND quote_currency NOT GLOB '*[^A-Z0-9_.-]*'),
    rate_numerator INTEGER NOT NULL CHECK(rate_numerator > 0),
    rate_denominator INTEGER NOT NULL CHECK(rate_denominator > 0),
    precision_scale INTEGER NOT NULL DEFAULT 4 CHECK(precision_scale >= 0 AND precision_scale <= 18),
    source TEXT NOT NULL CHECK(source IN ('MANUAL', 'POLLED_FEED', 'EXCHANGE_API')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    PRIMARY KEY(ledger_id, id),
    UNIQUE(ledger_id, directive_date, base_currency, quote_currency)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_price_history_lookup 
ON price_history(ledger_id, base_currency, quote_currency, directive_date DESC, id DESC);
