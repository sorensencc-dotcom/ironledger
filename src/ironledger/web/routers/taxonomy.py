"""Configurable item taxonomy endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import sqlite3
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from ironledger.conventions import validate_account_name
from ironledger.web.auth import require_operator

router = APIRouter(prefix="/api/taxonomy", tags=["taxonomy"])


def _path(request: Request) -> Path:
    return Path(request.app.state.config_dir) / "taxonomy.json"


class TaxonomyPayload(BaseModel):
    categories: list[dict[str, Any]]


def _validate(payload: TaxonomyPayload) -> dict[str, list[dict[str, Any]]]:
    categories = []
    for category in payload.categories:
        keywords = [str(k).strip().lower() for k in category.get("keywords", []) if str(k).strip()]
        account = str(category.get("account", "")).strip()
        if not keywords or not account:
            raise HTTPException(status_code=400, detail="Each category needs keywords and account")
        try:
            validate_account_name(account)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        categories.append({"keywords": keywords, "account": account})
    if not categories:
        raise HTTPException(status_code=400, detail="At least one taxonomy category is required")
    return {"categories": categories}


@router.get("")
def get_taxonomy(request: Request):
    path = _path(request)
    if not path.exists():
        return {"categories": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Taxonomy file is unreadable") from exc


@router.put("")
def put_taxonomy(payload: TaxonomyPayload, request: Request, _auth: None = Depends(require_operator)):
    data = _validate(payload)
    path = _path(request)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data