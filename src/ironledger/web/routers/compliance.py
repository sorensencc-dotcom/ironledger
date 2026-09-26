"""Compliance audit bundle generation and verification endpoints."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile

from ironledger.compliance.bundle import (
    MAX_ARCHIVE_BYTES,
    ComplianceBundleError,
    generate_compliance_bundle,
    verify_compliance_bundle,
)
from ironledger.web.auth import require_operator
from ironledger.web.schemas import (
    ComplianceBundleGenerateRequest,
    ComplianceBundleResponse,
    ComplianceBundleVerifyResponse,
)

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = request.app.state.get_db()
    try:
        yield conn
    finally:
        conn.close()


@router.post("/bundles", response_model=ComplianceBundleResponse)
def generate_bundle(
    payload: ComplianceBundleGenerateRequest,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    _auth: None = Depends(require_operator),
) -> dict:
    """Generate a sealed compliance audit bundle for the given period."""
    output_dir = getattr(request.app.state, "compliance_bundle_dir", Path("compliance-bundles"))
    try:
        result = generate_compliance_bundle(
            conn=conn,
            ledger_id=payload.ledger_id,
            framework=payload.framework,
            period_start_utc=payload.period_start_utc,
            period_end_utc=payload.period_end_utc,
            output_dir=output_dir,
        )
        conn.commit()
    except ComplianceBundleError as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ledger_id": result.ledger_id,
        "bundle_id": result.bundle_id,
        "framework": result.framework,
        "period_start_utc": result.period_start_utc,
        "period_end_utc": result.period_end_utc,
        "merkle_root_hex": result.merkle_root_hex,
        "sealed_archive_sha256": result.sealed_archive_sha256,
        "record_count": result.record_count,
        "manifest": result.manifest,
    }


@router.post("/bundles/verify", response_model=ComplianceBundleVerifyResponse)
async def verify_bundle(
    archive: UploadFile,
    expected_merkle_root: str | None = None,
    expected_sha256: str | None = None,
) -> dict:
    """Cryptographically verify an uploaded sealed compliance archive. Read-only."""
    content_length = getattr(archive, "size", None)
    if content_length is not None and content_length > MAX_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail=f"Archive exceeds maximum size limit ({MAX_ARCHIVE_BYTES} bytes)")
    archive_bytes = await archive.read()
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail=f"Archive exceeds maximum size limit ({MAX_ARCHIVE_BYTES} bytes)")
    try:
        result = verify_compliance_bundle(
            archive_bytes=archive_bytes,
            expected_merkle_root=expected_merkle_root,
            expected_sha256=expected_sha256,
        )
    except ComplianceBundleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result
