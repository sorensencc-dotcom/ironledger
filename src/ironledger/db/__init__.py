"""Database layer: connection policy and the migration runner.

Phase 1 builds the primary evidence, staging, ledger-index, audit, and
compile-run schema. The analytical/FTS projection is Phase 4 and is a separate,
disposable database.
"""
