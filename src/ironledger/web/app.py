"""FastAPI application factory for IronLedger Operator Workbench."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ironledger.db.connection import connect
from ironledger.observability.middleware import MetricsMiddleware
from ironledger.web.errors import GovernanceException, governance_exception_handler
from ironledger.web.routers import compile, connectors, failover, federation, health, metrics, projection, rules, staging, sync, system, webhooks

__all__ = ["create_app"]


def create_app(
    db_path: str | Path = "ironledger.db",
    projection_db_path: Optional[str | Path] = None,
    config_dir: Optional[str | Path] = None,
    static_dir: Optional[str | Path] = None,
) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="IronLedger Operator Workbench",
        description="Local-first Enterprise Operator Workbench API",
        version="0.11.0",
    )

    app.add_exception_handler(GovernanceException, governance_exception_handler)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    resolved_db_path = Path(db_path).resolve()
    resolved_proj_path = (
        Path(projection_db_path).resolve()
        if projection_db_path
        else resolved_db_path.parent / "projection.db"
    )
    resolved_config_dir = (
        Path(config_dir).resolve() if config_dir else resolved_db_path.parent / "config"
    )

    def get_db() -> sqlite3.Connection:
        return connect(resolved_db_path)

    def get_projection_db() -> sqlite3.Connection:
        return connect(resolved_proj_path)

    app.state.db_path = resolved_db_path
    app.state.projection_db_path = resolved_proj_path
    app.state.config_dir = resolved_config_dir
    app.state.get_db = get_db
    app.state.get_projection_db = get_projection_db

    # Include routers
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(staging.router)
    app.include_router(rules.router)
    app.include_router(projection.router)
    app.include_router(compile.router)
    app.include_router(system.router)
    app.include_router(sync.router)
    app.include_router(connectors.router)
    app.include_router(webhooks.router)
    app.include_router(federation.router)
    app.include_router(failover.router)


    # Mount static assets if build directory exists
    if static_dir and Path(static_dir).exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app

