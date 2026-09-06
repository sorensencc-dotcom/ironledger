"""Phase 1 task 6: projection and source manifest tests.

Tests verify:
- Empty projections pass SQLite integrity and schema checks and produce stable manifests.
- Revalidating the same projection reproduces the identical manifest digest.
- Text rendering and parsing preserves all metadata and hashes.
- Tampering with row counts, schema versions, input hashes, or file contents fails closed.
"""

from __future__ import annotations

import sqlite3
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.manifests import (
    Manifest,
    ManifestEntry,
    ManifestVerificationError,
    compute_manifest_digest,
    generate_projection_manifest,
    parse_manifest,
    render_manifest,
    verify_manifest,
)


@pytest.fixture
def empty_db() -> sqlite3.Connection:
    """Return an in-memory database with migrations applied and empty user tables."""
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def test_empty_projection_manifest_creation_and_verification(empty_db: sqlite3.Connection):
    """An empty migrated database produces a valid projection manifest."""
    manifest = generate_projection_manifest(
        empty_db,
        created_ts_utc="2026-08-31T14:05:09Z",
        projection_version="1.0.0",
    )

    assert manifest.schema_version == migrations.current_version(empty_db)
    assert manifest.manifest_kind == "projection_manifest"
    assert len(manifest.manifest_self_hash) == 64
    assert manifest.row_counts["source_documents"] == 0
    assert manifest.row_counts["ledger_entries"] == 0
    assert manifest.row_counts["schema_migrations"] == 5

    # Verification against database connection succeeds
    res = verify_manifest(manifest, conn=empty_db)
    assert res.is_valid is True
    assert res.schema_version == manifest.schema_version
    assert res.digest == manifest.manifest_self_hash


def test_revalidation_reproduces_same_digest(empty_db: sqlite3.Connection):
    """Generating the manifest twice with identical inputs produces the exact same digest."""
    m1 = generate_projection_manifest(
        empty_db,
        created_ts_utc="2026-08-31T14:05:09Z",
        projection_version="1.0.0",
    )
    m2 = generate_projection_manifest(
        empty_db,
        created_ts_utc="2026-08-31T14:05:09Z",
        projection_version="1.0.0",
    )
    assert m1.manifest_self_hash == m2.manifest_self_hash


def test_render_and_parse_roundtrip(empty_db: sqlite3.Connection):
    """Rendering a manifest to text and parsing it back preserves all fields and digest."""
    manifest = generate_projection_manifest(
        empty_db,
        created_ts_utc="2026-08-31T14:05:09Z",
        compile_run_id="run-1",
        source_input_hash="a" * 64,
        ledger_input_hash="b" * 64,
        output_hash="c" * 64,
    )

    rendered = render_manifest(manifest)
    parsed = parse_manifest(rendered)

    assert parsed.manifest_version == manifest.manifest_version
    assert parsed.manifest_kind == manifest.manifest_kind
    assert parsed.created_ts_utc == manifest.created_ts_utc
    assert parsed.schema_version == manifest.schema_version
    assert parsed.compile_run_id == manifest.compile_run_id
    assert parsed.source_input_hash == manifest.source_input_hash
    assert parsed.manifest_self_hash == manifest.manifest_self_hash

    # Verifying parsed manifest succeeds
    res = verify_manifest(parsed, conn=empty_db)
    assert res.is_valid is True
    assert res.digest == manifest.manifest_self_hash


def test_row_count_mutation_fails_verification(empty_db: sqlite3.Connection):
    """Inserting a row after manifest generation causes verification to fail."""
    manifest = generate_projection_manifest(
        empty_db,
        created_ts_utc="2026-08-31T14:05:09Z",
    )

    # Insert a document row
    empty_db.execute(
        "INSERT INTO source_documents "
        "(source_document_id, mime_type, encoding, provenance, acquisition_time_utc, "
        " content_sha256, raw_payload_ref, created_at_utc) VALUES "
        "('doc-1', 'text/csv', 'utf-8', 'prov', '2026-08-31T14:05:09Z', "
        f"'{'a' * 64}', 'evidence/source_documents/doc-1', '2026-08-31T14:05:09Z')"
    )
    empty_db.commit()

    with pytest.raises(ManifestVerificationError, match="row count mismatch"):
        verify_manifest(manifest, conn=empty_db)


def test_schema_version_tamper_fails_verification(empty_db: sqlite3.Connection):
    """Tampering with the recorded schema version fails self-hash or DB checks."""
    manifest = generate_projection_manifest(
        empty_db,
        created_ts_utc="2026-08-31T14:05:09Z",
    )

    # 1. Tamper field without recomputing self-hash
    tampered_unhashed = Manifest(
        **{**manifest.__dict__, "schema_version": 999}
    )
    with pytest.raises(ManifestVerificationError, match="manifest self-hash mismatch"):
        verify_manifest(tampered_unhashed, conn=empty_db)

    # 2. Tamper field with recomputed self-hash (fails DB schema check)
    tampered_payload = Manifest(
        **{**manifest.__dict__, "schema_version": 999, "manifest_self_hash": ""}
    )
    new_digest = compute_manifest_digest(tampered_payload)
    tampered_hashed = Manifest(
        **{**tampered_payload.__dict__, "manifest_self_hash": new_digest}
    )
    with pytest.raises(ManifestVerificationError, match="schema version mismatch"):
        verify_manifest(tampered_hashed, conn=empty_db)


def test_input_hash_tamper_fails_verification(empty_db: sqlite3.Connection):
    """Tampering with recorded input hashes fails self-hash validation."""
    manifest = generate_projection_manifest(
        empty_db,
        created_ts_utc="2026-08-31T14:05:09Z",
        source_input_hash="a" * 64,
    )

    tampered = Manifest(
        **{**manifest.__dict__, "source_input_hash": "b" * 64}
    )
    with pytest.raises(ManifestVerificationError, match="manifest self-hash mismatch"):
        verify_manifest(tampered)


def test_file_entry_verification_and_tamper(tmp_path):
    """File entries in the manifest verify against on-disk contents."""
    f1 = tmp_path / "ledger" / "main.beancount"
    f1.parent.mkdir(parents=True)
    f1.write_text("include accounts.beancount\n", encoding="utf-8")

    import hashlib
    f1_hash = hashlib.sha256(f1.read_bytes()).hexdigest()

    manifest = Manifest(
        manifest_version="1.0",
        manifest_kind="source_manifest",
        created_ts_utc="2026-08-31T14:05:09Z",
        schema_version=2,
        entries=(ManifestEntry(path="ledger/main.beancount", sha256_hex=f1_hash),),
    )
    digest = compute_manifest_digest(manifest)
    manifest_complete = Manifest(**{**manifest.__dict__, "manifest_self_hash": digest})

    # Verification against tmp_path directory passes
    res = verify_manifest(manifest_complete, base_dir=tmp_path)
    assert res.is_valid is True
    assert res.entry_count == 1

    # Tampering with file contents fails verification
    f1.write_text("tampered content\n", encoding="utf-8")
    with pytest.raises(ManifestVerificationError, match="file hash mismatch"):
        verify_manifest(manifest_complete, base_dir=tmp_path)

    # Missing file fails verification
    f1.unlink()
    with pytest.raises(ManifestVerificationError, match="manifest entry file missing"):
        verify_manifest(manifest_complete, base_dir=tmp_path)
