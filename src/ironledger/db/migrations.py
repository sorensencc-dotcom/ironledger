"""Forward-only migration runner.

Compatibility adapter delegating to ironledger.governance.migrations.
All migration execution, schema verification, and foreign-key checks are
governed by the Phase 6 governance migration engine.
"""

from __future__ import annotations

from ironledger.governance.migrations import (
    ChecksumMismatch,
    ForeignKeyViolationError,
    Migration,
    MigrationError,
    applied_migrations,
    current_version,
    discover_migrations,
    migrate,
    migrate_governed,
    verify_schema_checksums,
)

__all__ = [
    "MigrationError",
    "ChecksumMismatch",
    "ForeignKeyViolationError",
    "Migration",
    "discover_migrations",
    "current_version",
    "applied_migrations",
    "migrate",
    "migrate_governed",
    "verify_schema_checksums",
]
