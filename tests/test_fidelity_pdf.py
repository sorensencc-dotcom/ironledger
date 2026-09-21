from pathlib import Path

from pypdf import PdfWriter

from ironledger.ingest.formats.fidelity_pdf import parse_fidelity_pdf


def test_parse_fidelity_statement(tmp_path: Path) -> None:
    path = tmp_path / "statement.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)

    # Exercise text extraction seam without requiring a PDF text fixture.
    from ironledger.ingest.formats import fidelity_pdf
    page = type("Page", (), {"extract_text": lambda self: """Account # 1234XXXX\n01/15/26 BUY XYZ 037833100 10 100.00 1,000.00\n01/20/26 Dividend ABC 594918104 1 0.50 0.50"""})()
    fidelity_pdf.PdfReader = lambda _: type("Reader", (), {"pages": [page]})()  # type: ignore[assignment]
    records = parse_fidelity_pdf(path)

    assert records[0].account_id == "1234XXXX"
    assert records[0].posted_date == "2026-01-15"
    assert records[0].quantity == 10
    assert records[0].price == 100
    assert records[0].amount_minor == 100000
    assert records[0].transaction_type == "buy"
    assert records[1].transaction_type == "dividend"
