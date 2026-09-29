-- Migration 0021: Itemized orders and multi-leg split proposals

CREATE TABLE itemized_orders (
    order_id             TEXT PRIMARY KEY,
    source_document_id   TEXT NOT NULL REFERENCES source_documents(source_document_id) ON DELETE RESTRICT,
    ledger_id            TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    merchant             TEXT NOT NULL,
    merchant_order_ref   TEXT NOT NULL DEFAULT '',
    order_date           TEXT NOT NULL CHECK (order_date GLOB '????-??-??'),
    currency             TEXT NOT NULL CHECK (currency GLOB '[A-Z][A-Z][A-Z]'),
    subtotal_minor_units INTEGER NOT NULL,
    tax_minor_units      INTEGER NOT NULL DEFAULT 0,
    shipping_minor_units INTEGER NOT NULL DEFAULT 0,
    discount_minor_units INTEGER NOT NULL DEFAULT 0,
    total_minor_units    INTEGER NOT NULL,
    created_at_utc       TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    CHECK (total_minor_units = subtotal_minor_units + tax_minor_units + shipping_minor_units - discount_minor_units)
) STRICT;

CREATE TABLE itemized_order_lines (
    line_id              TEXT PRIMARY KEY,
    order_id             TEXT NOT NULL REFERENCES itemized_orders(order_id) ON DELETE CASCADE,
    line_index           INTEGER NOT NULL CHECK (line_index >= 0),
    item_title           TEXT NOT NULL,
    item_description     TEXT NOT NULL DEFAULT '',
    quantity             INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 1),
    unit_price_minor     INTEGER,
    total_price_minor    INTEGER NOT NULL,
    proposed_account     TEXT NOT NULL CHECK (
        proposed_account GLOB 'Expenses:*'
        OR proposed_account GLOB 'Assets:*'
        OR proposed_account GLOB 'Liabilities:*'
        OR proposed_account GLOB 'Income:*'
        OR proposed_account GLOB 'Equity:*'
    ),
    confidence_score     INTEGER NOT NULL CHECK (confidence_score BETWEEN 0 AND 100),
    created_at_utc       TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    UNIQUE (order_id, line_index)
) STRICT;

CREATE TABLE split_proposals (
    proposal_id          TEXT PRIMARY KEY,
    order_id             TEXT NOT NULL REFERENCES itemized_orders(order_id) ON DELETE CASCADE,
    target_type          TEXT NOT NULL CHECK (target_type IN ('staged_transaction', 'ledger_entry')),
    target_id            TEXT NOT NULL,
    parent_amount_minor  INTEGER NOT NULL,
    match_confidence     INTEGER NOT NULL CHECK (match_confidence BETWEEN 0 AND 100),
    status               TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'confirmed', 'rejected')),
    created_at_utc       TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    decided_at_utc       TEXT CHECK (decided_at_utc IS NULL OR decided_at_utc GLOB '????-??-??T??:??:??*Z'),
    UNIQUE (order_id, target_type, target_id)
) STRICT;

CREATE INDEX idx_itemized_orders_search ON itemized_orders(ledger_id, order_date, total_minor_units);
CREATE INDEX idx_itemized_orders_merchant ON itemized_orders(ledger_id, merchant, order_date);
CREATE INDEX idx_itemized_order_lines_order ON itemized_order_lines(order_id, line_index);
CREATE INDEX idx_split_proposals_lookup ON split_proposals(target_type, target_id, status);
CREATE INDEX idx_split_proposals_order ON split_proposals(order_id);
