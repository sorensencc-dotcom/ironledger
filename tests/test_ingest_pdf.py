"""Phase 15 T05: text-layer PDF parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from ironledger.ingest.errors import ParseError
from ironledger.ingest.formats.pdf_engine import load_pdf_profile, parse_pdf


def _minimal_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET\n".encode("latin-1")

    def _obj(n: int, body: str) -> bytes:
        return f"{n} 0 obj\n{body}\nendobj\n".encode("latin-1")

    objects = [
        _obj(1, "<< /Type /Catalog /Pages 2 0 R >>"),
        _obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        _obj(
            3,
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        ),
        f"4 0 obj\n<< /Length {len(content)} >>\nstream\n".encode("latin-1")
        + content
        + b"endstream\nendobj\n",
        _obj(5, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
    ]
    header = b"%PDF-1.4\n"
    body = header
    offsets = [0]
    for obj in objects:
        offsets.append(len(body))
        body += obj
    xref = [b"xref\n0 6\n0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n".encode("ascii"))
    trailer = (
        f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{len(body)}\n%%EOF\n".encode("ascii")
    )
    return body + b"".join(xref) + trailer


def test_parse_pdf_extracts_profiled_row(tmp_path: Path):
    config = Path("config")
    profile = load_pdf_profile(config, "example-card")
    raw = _minimal_pdf("2026-09-01  CAFE  -12.99")
    parsed = parse_pdf(raw, profile)
    assert parsed.account == "Liabilities:CreditCard:ExampleCard"
    assert parsed.default_currency == "USD"
    assert len(parsed.rows) == 1
    row = parsed.rows[0]
    assert row.posted_date == "2026-09-01"
    assert row.payee == "CAFE"
    assert row.amount_text == "-12.99"


def test_empty_text_layer_is_parse_error():
    profile = load_pdf_profile(Path("config"), "example-card")
    raw = _minimal_pdf("")
    with pytest.raises(ParseError, match="text layer"):
        parse_pdf(raw, profile)


def test_zero_line_matches_is_parse_error():
    profile = load_pdf_profile(Path("config"), "example-card")
    raw = _minimal_pdf("hello world no numbers")
    with pytest.raises(ParseError, match="no statement rows"):
        parse_pdf(raw, profile)


def test_encrypted_pdf_is_parse_error():
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    buf = BytesIO()
    writer.write(buf)
    profile = load_pdf_profile(Path("config"), "example-card")
    with pytest.raises(ParseError, match="encrypted"):
        parse_pdf(buf.getvalue(), profile)
