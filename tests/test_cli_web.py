"""Tests for the `ironledger web` CLI command."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from ironledger.cli.__main__ import main
from ironledger.cli.commands.web import run_web


def test_cli_web_parser_defaults() -> None:
    with patch("ironledger.cli.commands.web.run_web") as mock_run_web:
        exit_code = main(["web"])
        assert exit_code == 0
        mock_run_web.assert_called_once()
        kwargs = mock_run_web.call_args.kwargs
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 8000
        assert kwargs["open_browser"] is False
        assert kwargs["reload"] is False


def test_cli_web_parser_custom_args(tmp_path: Path) -> None:
    db_file = tmp_path / "test.db"
    proj_db = tmp_path / "proj.db"
    cfg_dir = tmp_path / "config"

    with patch("ironledger.cli.commands.web.run_web") as mock_run_web:
        exit_code = main([
            "--db", str(db_file),
            "--config-dir", str(cfg_dir),
            "web",
            "--host", "0.0.0.0",
            "--port", "9000",
            "--projection-db", str(proj_db),
            "--open-browser",
            "--reload",
        ])
        assert exit_code == 0
        mock_run_web.assert_called_once_with(
            db_path=str(db_file),
            projection_db_path=str(proj_db),
            config_dir=cfg_dir,
            host="0.0.0.0",
            port=9000,
            open_browser=True,
            reload=True,
        )


def test_run_web_invokes_uvicorn(tmp_path: Path) -> None:
    db_file = tmp_path / "test.db"
    with patch("uvicorn.run") as mock_uvicorn_run, patch("webbrowser.open") as mock_browser:
        run_web(
            db_path=db_file,
            host="127.0.0.1",
            port=8080,
            open_browser=True,
            reload=False,
        )
        mock_browser.assert_called_once_with("http://127.0.0.1:8080")
        mock_uvicorn_run.assert_called_once()
        app_arg = mock_uvicorn_run.call_args[0][0]
        assert app_arg is not None

