"""Unified governance error taxonomy and response envelopes."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any, Dict, Optional
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class GovernanceErrorDetail(BaseModel):
    error_code: str
    message: str
    details: Dict[str, Any] = {}
    timestamp_utc: str
    trace_id: str


class GovernanceException(HTTPException):
    """Base exception for all governed operational errors."""

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(status_code=status_code, detail=message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        self.timestamp_utc = datetime.now(timezone.utc).isoformat()
        self.trace_id = f"gov-{uuid.uuid4().hex[:12]}"

    def to_envelope(self) -> GovernanceErrorDetail:
        return GovernanceErrorDetail(
            error_code=self.error_code,
            message=self.message,
            details=self.details,
            timestamp_utc=self.timestamp_utc,
            trace_id=self.trace_id,
        )


async def governance_exception_handler(
    request: Request, exc: GovernanceException
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_envelope().model_dump(),
    )
