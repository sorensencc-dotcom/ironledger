"""Versioned projection and source hash manifests.

IronLedger manifests record the SHA-256 digests of projection artifacts and
source evidence files alongside compile metadata, schema versions, and row counts.
Manifests use deterministic ordering and formatting to ensure tamper detection.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from ironledger.conventions import ConventionError, validate_utc_timestamp
from ironledger.db import migrations

__all__ = [
    "ManifestError",
    "ManifestVerificationError",
    "ManifestEntry",
    "Manifest",
    "ManifestVerificationResult",
    "MANIFEST_VERSION",
    "canonical_manifest_bytes",
    "compute_manifest_digest",
    "render_manifest",
    "parse_manifest",
    "generate_projection_manifest",
    "verify_manifest",
    "GENESIS_MANIFEST_HASH",
    "compute_directory_manifest_hash",
    "compute_ledger_manifest_hash",
    "render_compiled_ledger_manifest",
    "render_price_directive_manifest",
]

MANIFEST_VERSION: Final[str] = "1.0"
MANIFEST_KINDS: Final[tuple[str, ...]] = ("projection_manifest", "source_manifest")


class ManifestError(ValueError):
    """A manifest is malformed or invalid."""


class ManifestVerificationError(ManifestError):
    """Manifest verification failed due to tamper, mismatch, or corruption."""


@dataclass(frozen=True)
class ManifestEntry:
    """A single file entry with relative path and SHA-256 hash."""

    path: str
    sha256_hex: str


@dataclass(frozen=True)
class Manifest:
    """Canonical manifest envelope."""

    manifest_version: str
    manifest_kind: str
    created_ts_utc: str
    schema_version: int
    compile_run_id: str | None = None
    projection_version: str | None = None
    source_input_hash: str | None = None
    ledger_input_hash: str | None = None
    output_hash: str | None = None
    row_counts: dict[str, int] | None = None
    entries: tuple[ManifestEntry, ...] = ()
    manifest_self_hash: str = ""


@dataclass(frozen=True)
class ManifestVerificationResult:
    """Summary of manifest verification."""

    is_valid: bool
    manifest_kind: str
    schema_version: int
    entry_count: int
    digest: str


def canonical_manifest_bytes(manifest: Manifest) -> bytes:
    """Return deterministic UTF-8 bytes for a manifest payload (excluding manifest_self_hash)."""
    # Sort entries deterministically by forward-slash path
    sorted_entries = sorted(manifest.entries, key=lambda e: e.path.replace("\\", "/"))

    # Canonical dictionary of header metadata
    header = {
        "manifest_version": manifest.manifest_version,
        "manifest_kind": manifest.manifest_kind,
        "created_ts_utc": manifest.created_ts_utc,
        "schema_version": manifest.schema_version,
        "compile_run_id": manifest.compile_run_id,
        "projection_version": manifest.projection_version,
        "source_input_hash": manifest.source_input_hash,
        "ledger_input_hash": manifest.ledger_input_hash,
        "output_hash": manifest.output_hash,
        "row_counts": (
            {k: manifest.row_counts[k] for k in sorted(manifest.row_counts)}
            if manifest.row_counts is not None
            else None
        ),
        "entries": [
            {"path": e.path.replace("\\", "/"), "sha256_hex": e.sha256_hex}
            for e in sorted_entries
        ],
    }
    encoded = json.dumps(header, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return encoded.encode("utf-8")


def compute_manifest_digest(manifest: Manifest) -> str:
    """Compute the canonical SHA-256 digest of a manifest."""
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def render_manifest(manifest: Manifest) -> str:
    """Render a manifest to a standard text representation with header and entries."""
    digest = manifest.manifest_self_hash or compute_manifest_digest(manifest)

    # Format header as structured JSON lines
    header_data = {
        "manifest_version": manifest.manifest_version,
        "manifest_kind": manifest.manifest_kind,
        "created_ts_utc": manifest.created_ts_utc,
        "schema_version": manifest.schema_version,
        "compile_run_id": manifest.compile_run_id,
        "projection_version": manifest.projection_version,
        "source_input_hash": manifest.source_input_hash,
        "ledger_input_hash": manifest.ledger_input_hash,
        "output_hash": manifest.output_hash,
        "row_counts": (
            {k: manifest.row_counts[k] for k in sorted(manifest.row_counts)}
            if manifest.row_counts is not None
            else {}
        ),
        "manifest_self_hash": digest,
    }

    lines = ["# IRONLEDGER MANIFEST", json.dumps(header_data, sort_keys=True), "# ENTRIES"]
    sorted_entries = sorted(manifest.entries, key=lambda e: e.path.replace("\\", "/"))
    for entry in sorted_entries:
        normalized_path = entry.path.replace("\\", "/")
        lines.append(f"{entry.sha256_hex}  {normalized_path}")

    return "\n".join(lines) + "\n"


def parse_manifest(text: str) -> Manifest:
    """Parse rendered manifest text back into a Manifest instance."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines or lines[0] != "# IRONLEDGER MANIFEST":
        raise ManifestError("invalid manifest header format")

    try:
        header = json.loads(lines[1])
    except json.JSONDecodeError as exc:
        raise ManifestError(f"malformed manifest JSON header: {exc}") from exc

    required_fields = {
        "manifest_version",
        "manifest_kind",
        "created_ts_utc",
        "schema_version",
        "manifest_self_hash",
    }
    missing = required_fields - set(header.keys())
    if missing:
        raise ManifestError(f"manifest header missing required fields: {sorted(missing)}")

    entries: list[ManifestEntry] = []
    in_entries = False
    for line in lines[2:]:
        if line == "# ENTRIES":
            in_entries = True
            continue
        if in_entries:
            parts = line.split("  ", 1)
            if len(parts) != 2:
                raise ManifestError(f"malformed manifest entry line: {line!r}")
            sha256_hex, path = parts
            if len(sha256_hex) != 64:
                raise ManifestError(f"invalid entry hash length: {sha256_hex!r}")
            entries.append(ManifestEntry(path=path, sha256_hex=sha256_hex))

    return Manifest(
        manifest_version=header["manifest_version"],
        manifest_kind=header["manifest_kind"],
        created_ts_utc=header["created_ts_utc"],
        schema_version=header["schema_version"],
        compile_run_id=header.get("compile_run_id"),
        projection_version=header.get("projection_version"),
        source_input_hash=header.get("source_input_hash"),
        ledger_input_hash=header.get("ledger_input_hash"),
        output_hash=header.get("output_hash"),
        row_counts=header.get("row_counts"),
        entries=tuple(entries),
        manifest_self_hash=header.get("manifest_self_hash", ""),
    )


def generate_projection_manifest(
    conn: sqlite3.Connection,
    *,
    compile_run_id: str | None = None,
    projection_version: str | None = "1.0.0",
    source_input_hash: str | None = None,
    ledger_input_hash: str | None = None,
    output_hash: str | None = None,
    db_path: Path | None = None,
    created_ts_utc: str | None = None,
    schema_version: int | None = None,
) -> Manifest:
    """Generate a verified projection manifest from a live SQLite database."""
    # 1. Verify SQLite integrity
    (integrity_status,) = conn.execute("PRAGMA integrity_check").fetchone()
    if integrity_status != "ok":
        raise ManifestError(f"SQLite integrity check failed: {integrity_status}")

    # 2. Extract schema version
    schema_ver = schema_version if schema_version is not None else migrations.current_version(conn)

    # 3. Compute row counts across all user tables
    table_rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    row_counts = {}
    for (tbl_name,) in table_rows:
        quoted = '"' + tbl_name.replace('"', '""') + '"'
        count = conn.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]
        row_counts[tbl_name] = count

    if created_ts_utc is None:
        created_ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    validate_utc_timestamp(created_ts_utc)

    # 4. Generate file entries if db_path is provided
    entries: list[ManifestEntry] = []
    if db_path is not None and db_path.exists():
        file_bytes = db_path.read_bytes()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        entries.append(ManifestEntry(path=db_path.name, sha256_hex=file_hash))

    manifest_payload = Manifest(
        manifest_version=MANIFEST_VERSION,
        manifest_kind="projection_manifest",
        created_ts_utc=created_ts_utc,
        schema_version=schema_ver,
        compile_run_id=compile_run_id,
        projection_version=projection_version,
        source_input_hash=source_input_hash,
        ledger_input_hash=ledger_input_hash,
        output_hash=output_hash,
        row_counts=row_counts,
        entries=tuple(entries),
    )
    digest = compute_manifest_digest(manifest_payload)
    return Manifest(
        manifest_version=manifest_payload.manifest_version,
        manifest_kind=manifest_payload.manifest_kind,
        created_ts_utc=manifest_payload.created_ts_utc,
        schema_version=manifest_payload.schema_version,
        compile_run_id=manifest_payload.compile_run_id,
        projection_version=manifest_payload.projection_version,
        source_input_hash=manifest_payload.source_input_hash,
        ledger_input_hash=manifest_payload.ledger_input_hash,
        output_hash=manifest_payload.output_hash,
        row_counts=manifest_payload.row_counts,
        entries=manifest_payload.entries,
        manifest_self_hash=digest,
    )


def verify_manifest(
    manifest: Manifest | str,
    conn: sqlite3.Connection | None = None,
    base_dir: Path | None = None,
    schema_version: int | None = None,
) -> ManifestVerificationResult:
    """Verify manifest integrity, self-digest, database counts, and file digests.

    Raises :class:`ManifestVerificationError` on any verification failure.
    """
    if isinstance(manifest, str):
        parsed = parse_manifest(manifest)
    elif isinstance(manifest, Manifest):
        parsed = manifest
    else:
        raise TypeError("manifest must be a Manifest instance or string")

    # 1. Verify manifest version and kind
    if parsed.manifest_version != MANIFEST_VERSION:
        raise ManifestVerificationError(
            f"unsupported manifest version: expected {MANIFEST_VERSION}, found {parsed.manifest_version}"
        )
    if parsed.manifest_kind not in MANIFEST_KINDS:
        raise ManifestVerificationError(
            f"unsupported manifest kind {parsed.manifest_kind!r}; expected one of {MANIFEST_KINDS}"
        )

    # 2. Verify timestamp format
    try:
        validate_utc_timestamp(parsed.created_ts_utc)
    except ConventionError as exc:
        raise ManifestVerificationError(f"invalid manifest timestamp: {exc}") from exc

    # 3. Verify self hash
    computed_digest = compute_manifest_digest(parsed)
    if parsed.manifest_self_hash != computed_digest:
        raise ManifestVerificationError(
            f"manifest self-hash mismatch: stored {parsed.manifest_self_hash}, computed {computed_digest}"
        )

    # 4. If database connection is provided, verify integrity, schema, and row counts
    if conn is not None:
        (integrity_status,) = conn.execute("PRAGMA integrity_check").fetchone()
        if integrity_status != "ok":
            raise ManifestVerificationError(f"database integrity check failed: {integrity_status}")

        if schema_version is not None:
            current_ver = schema_version
        else:
            current_ver = migrations.current_version(conn)
        if parsed.schema_version != current_ver:
            raise ManifestVerificationError(
                f"schema version mismatch: manifest records {parsed.schema_version}, database is {current_ver}"
            )

        if parsed.row_counts is not None:
            real_tables = {
                name
                for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            for tbl_name, expected_count in parsed.row_counts.items():
                if tbl_name not in real_tables:
                    raise ManifestVerificationError(
                        f"manifest names table {tbl_name!r}, which does not exist in the database"
                    )
                quoted = '"' + tbl_name.replace('"', '""') + '"'
                count = conn.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]
                if count != expected_count:
                    raise ManifestVerificationError(
                        f"row count mismatch for table {tbl_name!r}: expected {expected_count}, found {count}"
                    )

    # 5. If base_dir is provided, verify on-disk file entries
    if base_dir is not None:
        for entry in parsed.entries:
            file_path = base_dir / entry.path
            if not file_path.is_file():
                raise ManifestVerificationError(f"manifest entry file missing: {file_path}")
            content_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if content_hash != entry.sha256_hex:
                raise ManifestVerificationError(
                    f"file hash mismatch for {entry.path}: expected {entry.sha256_hex}, found {content_hash}"
                )

    return ManifestVerificationResult(
        is_valid=True,
        manifest_kind=parsed.manifest_kind,
        schema_version=parsed.schema_version,
        entry_count=len(parsed.entries),
        digest=computed_digest,
    )


# ---------------------------------------------------------------------------
# Phase 8: Multi-Ledger Plaintext Beancount Manifest Hashing & Generation
# ---------------------------------------------------------------------------

GENESIS_MANIFEST_HASH: Final[str] = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def compute_directory_manifest_hash(target_dir: Path | str) -> str:
    """Compute canonical SHA-256 manifest hash over all *.beancount files directly within target_dir."""
    path = Path(target_dir)
    if not path.exists() or not path.is_dir():
        return GENESIS_MANIFEST_HASH

    files = sorted([f for f in path.glob("*.beancount") if f.is_file()], key=lambda f: f.name)
    if not files:
        return GENESIS_MANIFEST_HASH

    parts: list[str] = []
    for f in files:
        content_hash = hashlib.sha256(f.read_bytes()).hexdigest()
        parts.append(f"{f.name}\n{content_hash}\n")

    canonical_bytes = "".join(parts).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def compute_ledger_manifest_hash(beancount_root: Path | str, ledger_id: str) -> str:
    """Compute current manifest hash for a specific tenant ledger."""
    from ironledger.ledger.topology import validate_and_resolve_ledger_root
    tenant_dir = validate_and_resolve_ledger_root(beancount_root, ledger_id)
    return compute_directory_manifest_hash(tenant_dir / "current")


def render_compiled_ledger_manifest(target_dir: Path, ledger_id: str, payload: dict[str, Any]) -> None:
    """Render compiled directives into target_dir/*.beancount."""
    target_dir.mkdir(parents=True, exist_ok=True)
    tx_file = target_dir / "transactions.beancount"

    directives = payload.get("compiled_directives", [])
    lines: list[str] = []
    for d in directives:
        date = d["proposed_date"]
        payee = d.get("payee", "")
        narration = d.get("narration", "")
        header = f'{date} * "{payee}" "{narration}"'
        lines.append(header)
        for p in d.get("postings", []):
            acc = p["account"]
            units = p["minor_units"]
            scale = p["minor_unit_scale"]
            curr = p["currency"]
            if scale > 0:
                sign = "-" if units < 0 else ""
                abs_val = abs(units)
                int_part = abs_val // (10 ** scale)
                frac_part = abs_val % (10 ** scale)
                frac_str = f"{frac_part:0{scale}d}"
                amt_str = f"{sign}{int_part}.{frac_str}"
            else:
                amt_str = str(units)
            lines.append(f"  {acc:<40} {amt_str:>12} {curr}")
        lines.append("")

    tx_file.write_text("\n".join(lines), encoding="utf-8")


def render_price_directive_manifest(target_dir: Path, ledger_id: str, payload: dict[str, Any]) -> None:
    """Append or write price directive in prices.beancount."""
    target_dir.mkdir(parents=True, exist_ok=True)
    prices_file = target_dir / "prices.beancount"

    date = payload["directive_date"]
    base = payload["base_currency"]
    quote = payload["quote_currency"]
    num = payload["rate_numerator"]
    denom = payload["rate_denominator"]
    scale = payload.get("precision_scale", 4)

    if denom == 1:
        rate_str = f"{num:.{scale}f}" if scale > 0 else str(num)
    else:
        from ironledger.valuation.engine import convert_amount_rational
        rate_minor = convert_amount_rational(
            source_minor=1,
            source_scale=0,
            rate_numerator=num,
            rate_denominator=denom,
            target_scale=scale,
        )
        int_part = rate_minor // (10 ** scale)
        frac_part = rate_minor % (10 ** scale)
        rate_str = f"{int_part}.{frac_part:0{scale}d}"

    line = f"{date} price {base:<8} {rate_str} {quote}\n"

    existing = prices_file.read_text(encoding="utf-8") if prices_file.exists() else ""
    prices_file.write_text(existing + line, encoding="utf-8")
