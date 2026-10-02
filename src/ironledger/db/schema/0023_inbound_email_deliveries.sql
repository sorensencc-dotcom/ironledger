-- Migration 0023: replay registry for inbound email webhooks
CREATE TABLE inbound_email_deliveries (
    delivery_id         TEXT PRIMARY KEY,
    event_id            TEXT NOT NULL,
    received_at_utc     TEXT NOT NULL CHECK (received_at_utc GLOB '????-??-??T??:??:??*Z'),
    source_document_id  TEXT
) STRICT;
