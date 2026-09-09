# tests/test_project_lock.py
from __future__ import annotations

from pathlib import Path

import pytest

from ironledger.compile.errors import CompileLockedError
from ironledger.compile.writer import acquire_compile_lock, acquire_lock
from ironledger.project.errors import ProjectLockedError


def test_acquire_compile_lock_still_raises_compile_locked(tmp_path: Path):
    with acquire_compile_lock(tmp_path):
        with pytest.raises(CompileLockedError, match="Compile lock is currently held"):
            with acquire_compile_lock(tmp_path):
                pass


def test_acquire_lock_project_name_raises_project_locked(tmp_path: Path):
    with acquire_lock(tmp_path, name=".project.lock", error_cls=ProjectLockedError):
        with pytest.raises(ProjectLockedError, match="Projection lock is currently held"):
            with acquire_lock(tmp_path, name=".project.lock", error_cls=ProjectLockedError):
                pass


def test_compile_and_project_locks_are_independent(tmp_path: Path):
    with acquire_lock(tmp_path, name=".compile.lock"):
        with acquire_lock(tmp_path, name=".project.lock", error_cls=ProjectLockedError) as proj:
            assert proj.name == ".project.lock"
