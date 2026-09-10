# Numbered migration SQL files live here as package data.
# Applied in ascending order by ironledger.db.migrations.migrate().

MIGRATIONS = [
    "0001_core_schema.sql",
    "0002_audit_append_only_triggers.sql",
    "0003_staged_postings.sql",
    "0004_review_workflow.sql",
    "0005_compile_journal.sql",
    "0006_mutation_events.sql",
    "0007_simplefin_sync.sql",
]
