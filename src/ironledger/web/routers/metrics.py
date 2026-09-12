"""Prometheus metrics scrape endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response

from ironledger.observability.metrics import REGISTRY

router = APIRouter(tags=["observability"])


@router.get("/metrics", response_class=Response)
def get_metrics() -> Response:
    """Exposes Prometheus and OpenMetrics compliant metrics text."""
    payload = REGISTRY.render_prometheus()
    return Response(content=payload, media_type="text/plain; version=0.0.4")
