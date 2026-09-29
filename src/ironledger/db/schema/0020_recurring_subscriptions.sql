-- Migration 0020: Recurring subscriptions and cadence intelligence view

DROP VIEW IF EXISTS v_recurring_subscriptions;

CREATE VIEW v_recurring_subscriptions AS
WITH expense_postings AS (
    SELECT
        st.ledger_id,
        lp.account,
        UPPER(TRIM(COALESCE(NULLIF(le.payee, ''), NULLIF(st.payee, ''), 'Unknown Payee'))) AS normalized_payee,
        COALESCE(NULLIF(le.payee, ''), NULLIF(st.payee, ''), 'Unknown Payee') AS display_payee,
        le.entry_date,
        lp.minor_units,
        lp.currency,
        lp.minor_unit_scale,
        le.ledger_entry_id,
        lp.ledger_posting_id
    FROM ledger_postings lp
    JOIN ledger_entries le ON lp.ledger_entry_id = le.ledger_entry_id
    JOIN staged_transactions st ON le.staged_transaction_id = st.staged_transaction_id
    WHERE lp.account GLOB 'Expenses:*' AND lp.minor_units > 0
),
ordered_postings AS (
    SELECT
        ledger_id,
        account,
        normalized_payee,
        display_payee,
        entry_date,
        minor_units,
        currency,
        minor_unit_scale,
        ledger_entry_id,
        ledger_posting_id,
        LAG(entry_date) OVER (
            PARTITION BY ledger_id, account, normalized_payee, currency
            ORDER BY entry_date, ledger_entry_id
        ) AS prev_date,
        LAG(minor_units) OVER (
            PARTITION BY ledger_id, account, normalized_payee, currency
            ORDER BY entry_date, ledger_entry_id
        ) AS prev_minor_units,
        ROW_NUMBER() OVER (
            PARTITION BY ledger_id, account, normalized_payee, currency
            ORDER BY entry_date DESC, ledger_entry_id DESC
        ) AS rn_desc,
        COUNT(*) OVER (
            PARTITION BY ledger_id, account, normalized_payee, currency
        ) AS occurrence_count
    FROM expense_postings
),
delta_calc AS (
    SELECT
        ledger_id,
        account,
        normalized_payee,
        display_payee,
        entry_date,
        minor_units,
        currency,
        minor_unit_scale,
        prev_date,
        prev_minor_units,
        rn_desc,
        occurrence_count,
        CASE
            WHEN prev_date IS NOT NULL
            THEN CAST(ROUND(JULIANDAY(entry_date) - JULIANDAY(prev_date)) AS INTEGER)
            ELSE NULL
        END AS interval_days
    FROM ordered_postings
),
summary_per_group AS (
    SELECT
        ledger_id,
        account,
        normalized_payee,
        display_payee,
        currency,
        minor_unit_scale,
        occurrence_count,
        MIN(entry_date) AS first_date,
        MAX(entry_date) AS last_date,
        CAST(ROUND(AVG(interval_days)) AS INTEGER) AS avg_interval_days,
        MAX(CASE WHEN rn_desc = 1 THEN minor_units END) AS last_amount_minor,
        MAX(CASE WHEN rn_desc = 1 THEN prev_minor_units END) AS prev_amount_minor
    FROM delta_calc
    WHERE occurrence_count >= 2
    GROUP BY ledger_id, account, normalized_payee, currency, minor_unit_scale
)
SELECT
    ledger_id,
    account,
    normalized_payee,
    display_payee,
    currency,
    minor_unit_scale,
    occurrence_count,
    first_date,
    last_date,
    avg_interval_days,
    last_amount_minor,
    COALESCE(prev_amount_minor, last_amount_minor) AS prev_amount_minor,
    CASE
        WHEN avg_interval_days BETWEEN 5 AND 9 THEN 'WEEKLY'
        WHEN avg_interval_days BETWEEN 12 AND 18 THEN 'BIWEEKLY'
        WHEN avg_interval_days BETWEEN 25 AND 35 THEN 'MONTHLY'
        WHEN avg_interval_days BETWEEN 75 AND 105 THEN 'QUARTERLY'
        WHEN avg_interval_days BETWEEN 340 AND 390 THEN 'ANNUAL'
        ELSE 'IRREGULAR'
    END AS cadence,
    CASE
        WHEN prev_amount_minor IS NOT NULL AND last_amount_minor > prev_amount_minor
        THEN 1
        ELSE 0
    END AS is_price_jump,
    CASE
        WHEN prev_amount_minor IS NOT NULL AND last_amount_minor > prev_amount_minor
        THEN last_amount_minor - prev_amount_minor
        ELSE 0
    END AS price_jump_minor
FROM summary_per_group;
