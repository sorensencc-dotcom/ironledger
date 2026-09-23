"""CLI command to launch the IronLedger Operator Workbench web service."""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Optional
import uvicorn

from ironledger.web.app import create_app


def run_web(
    db_path: str | Path = 'ironledger.db',
    projection_db_path: Optional[str | Path] = None,
    config_dir: Optional[str | Path] = None,
    host: str = '127.0.0.1',
    port: int = 8000,
    open_browser: bool = False,
    reload: bool = False,
) -> None:
    """Start the FastAPI backend service and serve the Operator Workbench SPA."""
    resolved_db = Path(db_path).resolve()
    resolved_proj = Path(projection_db_path).resolve() if projection_db_path else None
    resolved_config = (
        Path(config_dir).resolve() if config_dir else resolved_db.parent / 'config'
    )

    # Path to web/dist from src/ironledger/cli/commands/web.py
    repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
    static_dist = repo_root / 'web' / 'dist'
    if not static_dist.is_dir():
        # Fallback to current working directory if running in project root
        static_dist = Path.cwd() / 'web' / 'dist'
    static_dir = static_dist if static_dist.is_dir() else None

    import os
    from ironledger.db.connection import connect
    from ironledger.governance.migrations import migrate_governed

    conn = connect(resolved_db)
    try:
        migrate_governed(conn, resolved_db)
        views_dir = repo_root / "sql" / "views"
        if not views_dir.is_dir():
            views_dir = Path.cwd() / "sql" / "views"
        if views_dir.is_dir():
            for sql_file in sorted(views_dir.glob("*.sql")):
                conn.executescript(sql_file.read_text(encoding="utf-8"))
            conn.commit()
    finally:
        conn.close()

    app = create_app(
        db_path=resolved_db,
        projection_db_path=resolved_proj,
        config_dir=resolved_config,
        static_dir=static_dir,
    )
    app.state.op_token = os.environ.get("IRONLEDGER_OP_TOKEN", "d0-localhost-token")

    if open_browser:
        webbrowser.open(f'http://{host}:{port}')

    uvicorn.run(app, host=host, port=port, reload=reload)
