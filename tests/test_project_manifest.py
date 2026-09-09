from __future__ import annotations

from pathlib import Path

from ironledger.db.connection import connect
from ironledger.manifests import generate_projection_manifest, verify_manifest
from ironledger.project.migrate import PROJECT_SCHEMA_VERSION, apply_schema


def test_generate_with_schema_version_skips_operational_migrator(tmp_path: Path):
    db_path = tmp_path / "projection.sqlite"
    conn = connect(db_path)
    apply_schema(conn)
    conn.execute(
        "INSERT INTO projection_meta (singleton, compile_run_id, ledger_input_hash, "
        " ledger_output_hash, schema_version, built_at_utc, beancount_version, compiler_version) "
        "VALUES (1, 'run-1', ?, ?, 1, '2026-09-08T12:00:00Z', '3.2.3', '0.1.0')",
        ("a" * 64, "b" * 64),
    )
    conn.commit()
    manifest = generate_projection_manifest(
        conn,
        compile_run_id="run-1",
        ledger_input_hash="a" * 64,
        output_hash="b" * 64,
        db_path=db_path,
        created_ts_utc="2026-09-08T12:00:00Z",
        schema_version=PROJECT_SCHEMA_VERSION,
    )
    assert manifest.schema_version == PROJECT_SCHEMA_VERSION
    assert manifest.schema_version == 1
    assert "schema_migrations" not in (manifest.row_counts or {})
    assert (manifest.row_counts or {}).get("projection_meta") == 1
    result = verify_manifest(
        manifest, conn=conn, base_dir=tmp_path, schema_version=PROJECT_SCHEMA_VERSION
    )
    assert result.is_valid is True
