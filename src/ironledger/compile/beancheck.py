from __future__ import annotations

import importlib.metadata
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ironledger.compile.errors import BeanCheckUnavailableError

COMPILER_VERSION: Final[str] = "0.1.0"


@dataclass(frozen=True)
class BeanCheckResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    beancount_version: str
    compiler_version: str


def get_beancount_version() -> str:
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

    try:
        proc = subprocess.run(
            [resolved_bin, str(main_beancount_path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        b_ver = get_beancount_version()
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
            beancount_version=get_beancount_version(),
            compiler_version=COMPILER_VERSION,
        )
