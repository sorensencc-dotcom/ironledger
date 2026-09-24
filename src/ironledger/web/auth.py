"""Authentication dependencies for operator-only web mutations."""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status
from ironledger.web.errors import GovernanceException


def require_operator(request: Request, *, governance_error: bool = False) -> None:
    """Require the configured operator token; missing configuration fails closed."""
    configured = getattr(request.app.state, "op_token", None)
    token = request.headers.get("X-IronLedger-Op-Token")
    if (
        not isinstance(configured, str)
        or not configured.strip()
        or not isinstance(token, str)
        or not hmac.compare_digest(token, configured.strip())
    ):
        if governance_error:
            raise GovernanceException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_code="GOVERNANCE_VALIDATION_ERROR",
                message="Unauthorized: operator token is not configured or invalid",
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
