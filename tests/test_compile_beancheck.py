"""Tests for bean-check subprocess runner and version tracking."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from ironledger.compile.errors import BeanCheckUnavailableError
from ironledger.compile.beancheck import run_bean_check, get_beancount_version, COMPILER_VERSION


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


def _run_by_cmd(version_stdout="", version_stderr="", check_returncode=0):
    """subprocess.run stand-in that answers `--version` and the bean-check call
    differently based on argv."""
    def fake_run(cmd, *args, **kwargs):
        m = MagicMock()
        if "--version" in cmd:
            m.returncode = 0
            m.stdout = version_stdout
            m.stderr = version_stderr
        else:
            m.returncode = check_returncode
            m.stdout = ""
            m.stderr = ""
        return m
    return fake_run


def test_beancount_version_read_from_bean_check_binary(tmp_path: Path):
    """#4: beancount is not a dependency, so importlib.metadata almost never
    resolves it. The version must come from `bean-check --version`."""
    main_file = tmp_path / "main.beancount"
    main_file.write_text('option "title" "Test"\n')
    with patch("shutil.which", return_value="/bin/bean-check"), \
         patch("subprocess.run", side_effect=_run_by_cmd(version_stdout="bean-check 2.3.6\n")):
        res = run_bean_check(main_file)
    assert res.beancount_version == "2.3.6"


def test_beancount_version_reads_from_stderr_channel(tmp_path: Path):
    main_file = tmp_path / "main.beancount"
    main_file.write_text('option "title" "Test"\n')
    with patch("shutil.which", return_value="/bin/bean-check"), \
         patch("subprocess.run", side_effect=_run_by_cmd(version_stderr="beancount 3.1.0")):
        res = run_bean_check(main_file)
    assert res.beancount_version == "3.1.0"


def test_beancount_version_falls_back_to_metadata_then_unknown(tmp_path: Path):
    main_file = tmp_path / "main.beancount"
    main_file.write_text('option "title" "Test"\n')
    with patch("shutil.which", return_value="/bin/bean-check"), \
         patch("subprocess.run", side_effect=_run_by_cmd(version_stderr="no version flag here")), \
         patch("importlib.metadata.version", side_effect=importlib.metadata.PackageNotFoundError("beancount")):
        res = run_bean_check(main_file)
    assert res.beancount_version == "unknown"


def test_get_beancount_version_without_binary_uses_metadata():
    with patch("importlib.metadata.version", return_value="2.3.6") as mv:
        assert get_beancount_version() == "2.3.6"
    mv.assert_called_once_with("beancount")
