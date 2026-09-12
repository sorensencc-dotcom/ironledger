"""ASGI HTTP metrics middleware for FastAPI / Starlette applications."""

from __future__ import annotations

import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ironledger.observability.metrics import HTTP_REQUEST_DURATION_MS, HTTP_REQUESTS_TOTAL


class MetricsMiddleware(BaseHTTPMiddleware):
    """Measures request duration and status counts without floating point drift."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_ns = time.perf_counter_ns()
        method = request.method
        path = request.url.path

        # Correlation ID propagation
        correlation_id = request.headers.get("X-Correlation-ID") or f"req_{uuid.uuid4().hex[:16]}"
        request.state.correlation_id = correlation_id

        response: Response
        try:
            response = await call_next(request)
            status_str = str(response.status_code)
        except Exception:
            status_str = "500"
            raise
        finally:
            elapsed_ns = time.perf_counter_ns() - start_ns
            # Convert nanoseconds to integer milliseconds (exact integer division)
            elapsed_ms = elapsed_ns // 1_000_000

            # Record Prometheus metrics
            HTTP_REQUESTS_TOTAL.inc(1, labels={"method": method, "path": path, "status": status_str})
            HTTP_REQUEST_DURATION_MS.observe(elapsed_ms, labels={"method": method, "path": path})

        response.headers["X-Correlation-ID"] = correlation_id
        return response
