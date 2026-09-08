from __future__ import annotations

import importlib.metadata
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ironledger.compile.errors import BeanCheckUnavailableError

COMPILER_VERSION: Final[str] = "0.1.0"

_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"\b(\d+\.\d+(?:\.\d+)?)\b")


@dataclass(frozen=True)
class BeanCheckResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    beancount_version: str
    compiler_version: str


def get_beancount_version(bean_check_bin: str | None = None) -> str:
    """Best-effort beancount version string.

    beancount is deliberately not a dependency of this package, so
    ``importlib.metadata`` almost never resolves it in a real deployment. Ask
    the resolved ``bean-check`` binary itself first (``bean-check --version``),
    then fall back to installed package metadata, then to ``"unknown"``.
    """
    if bean_check_bin is not None:
        try:
            proc = subprocess.run(
                [bean_check_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            match = _VERSION_RE.search(proc.stdout) or _VERSION_RE.search(proc.stderr)
            if match:
                return match.group(1)
        except (subprocess.SubprocessError, OSError):
            pass
    try:
        return importlib.metadata.version("beancount")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def run_bean_check(
    main_beancount_path: Path,
    *,
    timeout_seconds: float = 10.0,
    bean_check_bin: str | None = None,
) -> BeanCheckResult:
    resolved_bin = bean_check_bin or shutil.which("bean-check")
    if resolved_bin is None:
        raise BeanCheckUnavailableError("bean-check executable not found on PATH")

    b_ver = get_beancount_version(resolved_bin)

    try:
        proc = subprocess.run(
            [resolved_bin, str(main_beancount_path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return BeanCheckResult(
            ok=(proc.returncode == 0),
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            beancount_version=b_ver,
            compiler_version=COMPILER_VERSION,
        )
    except subprocess.TimeoutExpired as e:
        return BeanCheckResult(
            ok=False,
            exit_code=-1,
            stdout="",
            stderr=f"bean-check timed out after {timeout_seconds}s: {e}",
            beancount_version=b_ver,
            compiler_version=COMPILER_VERSION,
        )
