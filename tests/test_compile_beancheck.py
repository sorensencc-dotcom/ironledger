"""Tests for bean-check subprocess runner and version tracking."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import pytest

from ironledger.compile.errors import BeanCheckUnavailableError
from ironledger.compile.beancheck import run_bean_check, COMPILER_VERSION


def test_beancheck_unavailable_raises(tmp_path: Path):
    main_file = tmp_path / "main.beancount"
    main_file.write_text('option "title" "Test"\n')
    with patch("shutil.which", return_value=None):
        with pytest.raises(BeanCheckUnavailableError, match="bean-check executable not found"):
            run_bean_check(main_file)


def test_beancheck_success_mocked(tmp_path: Path):
    main_file = tmp_path / "main.beancount"
    main_file.write_text('option "title" "Test"\n')
    with patch("shutil.which", return_value="/bin/bean-check"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        res = run_bean_check(main_file)
        assert res.ok is True
        assert res.exit_code == 0
        assert res.compiler_version == COMPILER_VERSION


def test_beancheck_failure_captured(tmp_path: Path):
    main_file = tmp_path / "main.beancount"
    main_file.write_text('invalid syntax\n')
    with patch("shutil.which", return_value="/bin/bean-check"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "syntax error at line 1"
        res = run_bean_check(main_file)
        assert res.ok is False
        assert res.exit_code == 1
        assert "syntax error" in res.stderr
