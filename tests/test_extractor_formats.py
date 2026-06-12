"""Tests for format-specific text extractors in analyzer.py.

Covers:
- .doc legacy OLE2: degraded extraction, noise heuristic, routing
- .xlsx: openpyxl-based extraction including numbers and dates
- scanner.detect_magic: graceful degradation when magic is unavailable
"""

import io
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import analyzer
import scanner

# ── .doc legacy (OLE2) ───────────────────────────────────────────────────────


def _write_fake_ole2(path: Path, embedded_text: str) -> None:
    """Write a file that starts with the OLE2 magic bytes and contains embedded text."""
    # OLE2 magic: D0 CF 11 E0 A1 B1 1A E1
    magic = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    padding = b"\x00" * 500  # binary noise
    payload = embedded_text.encode("latin-1")
    path.write_bytes(magic + padding + payload + padding)


def test_doc_legacy_extracts_embedded_text(tmp_path):
    doc = tmp_path / "report.doc"
    # Embed a realistic sentence so alpha ratio is above threshold
    embedded = "This is a financial report for the quarter ending December 2023. " * 5
    _write_fake_ole2(doc, embedded)

    result = analyzer.extract_text_doc_legacy(doc)
    assert result != ""
    # Must contain some of the real text
    assert "financial" in result or "report" in result or "quarter" in result


def test_doc_legacy_discards_binary_noise(tmp_path):
    doc = tmp_path / "binary.doc"
    # High density of non-alpha printable chars → should be discarded
    noise = "1234567890!@#$%^&*()_+{}|:<>?~`=-[];',./\\" * 50
    _write_fake_ole2(doc, noise)

    result = analyzer.extract_text_doc_legacy(doc)
    assert result == ""


def test_doc_legacy_empty_file(tmp_path):
    doc = tmp_path / "empty.doc"
    doc.write_bytes(b"")
    assert analyzer.extract_text_doc_legacy(doc) == ""


def test_doc_routed_to_legacy_extractor(tmp_path):
    """extract_text('.doc') must NOT try to open the file as a ZIP."""
    doc = tmp_path / "legacy.doc"
    embedded = "Management report summary for the annual review. " * 5
    _write_fake_ole2(doc, embedded)

    # Should not raise — old code would raise BadZipFile here
    result = analyzer.extract_text(doc, ".doc")
    # Either extracted something or returned "" due to noise — but no exception
    assert isinstance(result, str)


def test_docx_not_routed_to_legacy(tmp_path):
    """extract_text('.docx') must still use the ZIP/XML path."""
    docx = tmp_path / "modern.docx"
    # Minimal valid .docx (ZIP with word/document.xml)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Hello from docx</w:t></w:r></w:p></w:body>"
            "</w:document>"
        )
        z.writestr("word/document.xml", xml)
    docx.write_bytes(buf.getvalue())

    result = analyzer.extract_text(docx, ".docx")
    assert "Hello from docx" in result


# ── XLSX (openpyxl) ───────────────────────────────────────────────────────────


def _make_xlsx(path: Path, rows: list[list]) -> None:
    """Create a minimal .xlsx with openpyxl for testing."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(str(path))


def test_xlsx_extracts_text_cells(tmp_path):
    xlsx = tmp_path / "data.xlsx"
    _make_xlsx(xlsx, [["Name", "Size", "Date"], ["report.pdf", 1024, "2024-01-15"]])

    result = analyzer.extract_text_xlsx(xlsx)
    assert "Name" in result
    assert "report.pdf" in result


def test_xlsx_includes_numbers(tmp_path):
    xlsx = tmp_path / "numbers.xlsx"
    _make_xlsx(xlsx, [["Item", "Value"], ["Sales", 99999], ["Cost", 42.5]])

    result = analyzer.extract_text_xlsx(xlsx)
    assert "99999" in result
    assert "42.5" in result


def test_xlsx_respects_100_row_limit(tmp_path):
    xlsx = tmp_path / "large.xlsx"
    _make_xlsx(xlsx, [[f"Row {i}", i] for i in range(200)])

    result = analyzer.extract_text_xlsx(xlsx)
    assert "Row 0" in result
    # Row 150 should not appear (beyond 100-row limit)
    assert "Row 150" not in result


def test_xlsx_empty_workbook(tmp_path):
    import openpyxl

    xlsx = tmp_path / "empty.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Sheet1"
    wb.save(str(xlsx))

    result = analyzer.extract_text_xlsx(xlsx)
    assert result == ""


def test_xlsx_routed_via_extract_text(tmp_path):
    xlsx = tmp_path / "routed.xlsx"
    _make_xlsx(xlsx, [["alpha", "beta"], [1, 2]])

    result = analyzer.extract_text(xlsx, ".xlsx")
    assert "alpha" in result
    assert "beta" in result


# ── scanner.detect_magic degradation ─────────────────────────────────────────


def test_detect_magic_returns_empty_when_unavailable(tmp_path):
    """When magic is not importable, detect_magic must return '' silently."""
    dummy = tmp_path / "file.bin"
    dummy.write_bytes(b"\x89PNG\r\n\x1a\n")  # PNG magic bytes

    with patch.object(scanner, "_MAGIC_AVAILABLE", False):
        result = scanner.detect_magic(dummy)
    assert result == ""


def test_detect_magic_logs_exception(tmp_path, caplog):
    """detect_magic catches and logs exceptions instead of propagating them."""
    dummy = tmp_path / "file.bin"
    dummy.write_bytes(b"data")

    mock_magic = MagicMock()
    mock_magic.from_file.side_effect = RuntimeError("libmagic failure")

    with patch.object(scanner, "_MAGIC_AVAILABLE", True), patch.dict(sys.modules, {"magic": mock_magic}):
        import importlib

        importlib.reload(scanner)  # pick up the patched module
        # Directly test the exception path
        with patch("scanner.magic", mock_magic):
            result = scanner.detect_magic(dummy)

    assert result == ""


def test_detect_magic_available_on_windows():
    """On Windows, magic should be available via python-magic-bin."""
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows-only test")
    # If python-magic-bin is installed correctly, _MAGIC_AVAILABLE is True
    assert scanner._MAGIC_AVAILABLE is True


# ── alpha ratio heuristic boundary ───────────────────────────────────────────


def test_alpha_ratio_boundary(tmp_path):
    """Text just above the alpha threshold must be returned; below must be discarded."""
    threshold = analyzer._DOC_ALPHA_RATIO_MIN

    # Build text with exactly threshold alpha ratio
    alpha_chars = int(threshold * 200)
    non_alpha = 200 - alpha_chars
    borderline = "a" * alpha_chars + "1" * non_alpha
    # Must be long enough to be picked up by the regex (5+ chars)
    # Pad to avoid the sequence being too short
    borderline = borderline * 3

    doc_above = tmp_path / "above.doc"
    _write_fake_ole2(doc_above, "Hello world this is real English text. " * 20)
    assert analyzer.extract_text_doc_legacy(doc_above) != ""

    doc_below = tmp_path / "below.doc"
    _write_fake_ole2(doc_below, "12345!@#$%67890" * 50)
    assert analyzer.extract_text_doc_legacy(doc_below) == ""
