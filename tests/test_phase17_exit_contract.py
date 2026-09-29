from __future__ import annotations

import ast
from pathlib import Path
import pytest


def test_phase17_ast_invariants():
    """Verify zero ast.Div and zero import beancount across all Phase 17 and modified modules."""
    files_to_check = [
        Path("src/ironledger/compile/model.py"),
        Path("src/ironledger/compile/render.py"),
        Path("src/ironledger/web/routers/staging.py"),
        Path("src/ironledger/mcp/tools.py"),
        Path("src/ironledger/ingest/formats/amazon_order_normalizer.py"),
        Path("src/ironledger/ingest/formats/venmo_normalizer.py"),
        Path("src/ironledger/ingest/formats/email_receipt_engine.py"),
        Path("src/ironledger/ingest/split_linker.py"),
    ]

    for file_path in files_to_check:
        assert file_path.exists(), f"File {file_path} must exist"
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            assert not isinstance(node, ast.Div), f"Forbidden ast.Div (float division) found in {file_path}"
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names]
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                for mod in names:
                    assert "beancount" not in mod, f"Forbidden import beancount in {file_path}: {mod}"
