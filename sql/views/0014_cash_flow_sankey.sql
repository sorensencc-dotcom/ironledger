CREATE VIEW IF NOT EXISTS v_sankey_cash_flows AS
WITH classified_postings AS (
    SELECT
        t.entry_date AS tx_date,
        strftime('%Y-%m', t.entry_date) AS period_month,
        p.account,
        p.currency,
        p.minor_units AS amount,
        CASE
            WHEN p.account LIKE 'Income:%' THEN 'SOURCE_INCOME'
            WHEN p.account LIKE 'Expenses:%' THEN 'TARGET_EXPENSE'
            WHEN p.account LIKE 'Assets:%Investments:%' OR p.account LIKE 'Assets:%Brokerage:%' THEN 'TARGET_INVESTMENT'
            WHEN p.account LIKE 'Assets:%' THEN 'BUFFER_LIQUID'
            WHEN p.account LIKE 'Liabilities:%' THEN 'TARGET_LIABILITY'
            ELSE 'OTHER'
        END AS flow_role
    FROM ledger_postings p
    JOIN ledger_entries t ON t.ledger_entry_id = p.ledger_entry_id
)
-- Layer 1: Aggregated Income streams -> Central Aggregation Node
SELECT
    period_month,
    currency,
    account AS source_node,
    'Operating:GrossFlow' AS target_node,
    SUM(-amount) AS amount_minor_units
FROM classified_postings
WHERE flow_role = 'SOURCE_INCOME' AND amount < 0
GROUP BY period_month, currency, account

UNION ALL

-- Layer 2: Central Aggregation Node -> Aggregated Leaf Categories & Capital Allocations
SELECT
    period_month,
    currency,
    'Operating:GrossFlow' AS source_node,
    account AS target_node,
    SUM(amount) AS amount_minor_units
FROM classified_postings
WHERE flow_role IN ('TARGET_EXPENSE', 'TARGET_INVESTMENT') AND amount > 0
GROUP BY period_month, currency, account;
