"""Safe-mode-gated compile and dry-run simulation router."""

from __future__ import annotations

import difflib
import sqlite3
from pathlib import Path
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Request

from ironledger.governance.safemode import (
    SafeModeAuthorizationError,
    require_governed_authorization,
    safe_mode_enabled,
)
from ironledger.compile.model import load_approved_set, validate_approved_set
from ironledger.compile.render import render_ledger
from ironledger.compile.writer import compile_approved
from ironledger.project.activate import rebuild_projection
from ironledger.web.schemas import CompileRequest, CompileResponse
from ironledger.web.auth import require_operator

router = APIRouter(prefix="/api", tags=["compile"])


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.get_db()


@router.post("/compile", response_model=CompileResponse)
def compile_ledger(
    payload: CompileRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> CompileResponse:
    """Compile approved staged transactions into plaintext Beancount files with safe-mode gating."""
    app_state = request.app.state
    ledger_dir = (
        Path(payload.ledger_dir).resolve()
        if payload.ledger_dir
        else getattr(app_state, "ledger_dir", Path("ledger"))
    )
    projection_dir = getattr(app_state, "projection_dir", Path("projection"))
    config_dir = getattr(app_state, "config_dir", Path("config"))

    if payload.dry_run:
        return _run_simulation(db, ledger_dir)

    # Mutation path: Enforce safe mode via governed authorization gate
    try:
        require_governed_authorization(
            db,
            token=payload.safe_mode_token,
            phrase=payload.safe_mode_token,
            scope="compile",
            target_digest="ledger",
            config_dir=config_dir,
            actor="operator",
        )
    except SafeModeAuthorizationError as exc:
        raise HTTPException(
            status_code=403,
            detail=f"Compile not authorized: {exc}",
        ) from exc

    try:
        summary = compile_approved(db, ledger_dir)
        total_postings = sum(
            len(t.postings) for t in load_approved_set(db).transactions
        ) if summary.entry_count > 0 else 0

        if payload.rebuild_projection:
            rebuild_projection(db, ledger_dir, projection_dir)

        return CompileResponse(
            success=True,
            message="Compilation and projection rebuild completed successfully.",
            run_id=summary.compile_run_id,
            dry_run=False,
            entries_compiled=summary.entry_count,
            postings_compiled=total_postings,
            diff_preview=None,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Compile failed: {exc}") from exc


@router.post("/compile/simulate", response_model=CompileResponse)
def simulate_compile(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> CompileResponse:
    """Execute a dry-run compile simulation returning diffs without touching disk."""
    app_state = request.app.state
    ledger_dir = getattr(app_state, "ledger_dir", Path("ledger"))
    return _run_simulation(db, ledger_dir)


@router.post("/project/rebuild")
def trigger_project_rebuild(
    request: Request,
    payload: Optional[dict[str, Any]] = None,
    db: sqlite3.Connection = Depends(get_db),
    _auth: None = Depends(require_operator),
):
    """Rebuild SQLite projection from plaintext ledger on disk."""
    app_state = request.app.state
    ledger_dir = getattr(app_state, "ledger_dir", Path("ledger"))
    projection_dir = getattr(app_state, "projection_dir", Path("projection"))
    config_dir = getattr(app_state, "config_dir", Path("config"))

    token = None
    phrase = None
    if isinstance(payload, dict):
        token = payload.get("safe_mode_token") or payload.get("token")
        phrase = payload.get("phrase") or payload.get("confirm")
        if "ledger_dir" in payload and payload["ledger_dir"]:
            ledger_dir = Path(payload["ledger_dir"]).resolve()
        if "projection_dir" in payload and payload["projection_dir"]:
            projection_dir = Path(payload["projection_dir"]).resolve()

    configured_ledger_dir = Path(getattr(app_state, "ledger_dir", Path("ledger"))).resolve()
    configured_projection_dir = Path(getattr(app_state, "projection_dir", Path("projection"))).resolve()
    if not ledger_dir.is_relative_to(configured_ledger_dir):
        raise HTTPException(status_code=400, detail="ledger_dir must remain inside the configured ledger directory")
    if not projection_dir.is_relative_to(configured_projection_dir):
        raise HTTPException(status_code=400, detail="projection_dir must remain inside the configured projection directory")

    try:
        require_governed_authorization(
            db,
            token=token,
            phrase=phrase,
            scope="project",
            target_digest="projection",
            config_dir=config_dir,
            actor="operator",
        )
    except SafeModeAuthorizationError as exc:
        raise HTTPException(
            status_code=403,
            detail=f"Projection rebuild not authorized: {exc}",
        ) from exc

    try:
        summary = rebuild_projection(db, ledger_dir, projection_dir)
        return {
            "success": True,
            "message": "Projection rebuilt successfully",
            "entry_count": summary.entry_count,
            "posting_count": summary.posting_count,
            "account_count": summary.account_count,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Projection rebuild failed: {exc}") from exc


def _run_simulation(db: sqlite3.Connection, ledger_dir: Path) -> CompileResponse:
    try:
        approved_set = load_approved_set(db)
        validate_approved_set(approved_set)
        rendered = render_ledger(approved_set)

        diff_lines = []
        for rel_path, new_bytes in rendered.items():
            new_text = new_bytes.decode("utf-8")
            on_disk_path = ledger_dir / rel_path
            old_text = on_disk_path.read_text(encoding="utf-8") if on_disk_path.exists() else ""
            file_diff = list(
                difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=f"a/{rel_path}",
                    tofile=f"b/{rel_path}",
                )
            )
            if file_diff:
                diff_lines.extend(file_diff)
            else:
                diff_lines.append(f"--- a/{rel_path} (new file: {len(new_text.splitlines())} lines)\n")

        diff_preview = "".join(diff_lines) if diff_lines else "No changes detected."
        total_postings = sum(len(t.postings) for t in approved_set.transactions)

        return CompileResponse(
            success=True,
            message="Dry-run simulation succeeded with zero disk mutations.",
            run_id=None,
            dry_run=True,
            entries_compiled=len(approved_set.transactions),
            postings_compiled=total_postings,
            diff_preview=diff_preview,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Simulation failed: {exc}") from exc

