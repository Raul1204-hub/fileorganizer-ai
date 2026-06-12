"""Unit tests for analyzer._validate_analysis."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from analyzer import _validate_analysis

# ── helpers ───────────────────────────────────────────────────────────────────


def _ok(result: dict) -> None:
    assert isinstance(result, dict) and len(result) == 3, f"Expected 3-key dict, got {result!r}"
    assert set(result) == {"categoria", "etiquetas", "resumen"}


# ── valid / happy-path cases ──────────────────────────────────────────────────


def test_valid_input_passes_through():
    data = {"categoria": "Documentos", "etiquetas": ["informe", "pdf"], "resumen": "Un documento."}
    result = _validate_analysis(data)
    _ok(result)
    assert result["categoria"] == "Documentos"
    assert result["etiquetas"] == ["informe", "pdf"]
    assert result["resumen"] == "Un documento."


def test_all_valid_categories_accepted():
    valid = [
        "Documentos",
        "Imágenes",
        "Audio",
        "Vídeo",
        "Código",
        "Datos",
        "Comprimidos",
        "Programas",
        "Desconocido",
    ]
    for cat in valid:
        r = _validate_analysis({"categoria": cat, "etiquetas": [], "resumen": ""})
        assert r["categoria"] == cat, f"{cat!r} should be accepted as-is"


# ── categoria normalisation ───────────────────────────────────────────────────


def test_unknown_category_becomes_desconocido():
    data = {"categoria": "Alien", "etiquetas": [], "resumen": ""}
    assert _validate_analysis(data)["categoria"] == "Desconocido"


def test_empty_category_becomes_desconocido():
    data = {"categoria": "", "etiquetas": [], "resumen": ""}
    assert _validate_analysis(data)["categoria"] == "Desconocido"


def test_missing_category_key_becomes_desconocido():
    data = {"etiquetas": [], "resumen": "hello"}
    assert _validate_analysis(data)["categoria"] == "Desconocido"


# ── etiquetas normalisation ───────────────────────────────────────────────────


def test_tags_capped_at_five():
    tags = ["a", "b", "c", "d", "e", "f", "g"]
    result = _validate_analysis({"categoria": "Datos", "etiquetas": tags, "resumen": ""})
    assert len(result["etiquetas"]) == 5
    assert result["etiquetas"] == ["a", "b", "c", "d", "e"]


def test_tags_bare_string_wrapped_in_list():
    result = _validate_analysis({"categoria": "Datos", "etiquetas": "solo", "resumen": ""})
    assert result["etiquetas"] == ["solo"]


def test_tags_non_list_non_string_becomes_empty():
    result = _validate_analysis({"categoria": "Datos", "etiquetas": 42, "resumen": ""})
    assert result["etiquetas"] == []


def test_tags_strips_whitespace_and_discards_empty():
    tags = ["  informe  ", "", "   ", "pdf"]
    result = _validate_analysis({"categoria": "Documentos", "etiquetas": tags, "resumen": ""})
    assert result["etiquetas"] == ["informe", "pdf"]


def test_tags_non_string_elements_discarded():
    tags = ["valid", 123, None, "also valid"]
    result = _validate_analysis({"categoria": "Datos", "etiquetas": tags, "resumen": ""})
    assert result["etiquetas"] == ["valid", "also valid"]


def test_missing_tags_key_gives_empty_list():
    result = _validate_analysis({"categoria": "Documentos", "resumen": "ok"})
    assert result["etiquetas"] == []


# ── resumen normalisation ─────────────────────────────────────────────────────


def test_resumen_truncated_at_300():
    long = "x" * 500
    result = _validate_analysis({"categoria": "Documentos", "etiquetas": [], "resumen": long})
    assert len(result["resumen"]) == 300


def test_resumen_non_string_coerced():
    result = _validate_analysis({"categoria": "Datos", "etiquetas": [], "resumen": 999})
    assert result["resumen"] == "999"


def test_resumen_stripped():
    result = _validate_analysis({"categoria": "Datos", "etiquetas": [], "resumen": "  hola  "})
    assert result["resumen"] == "hola"


def test_missing_resumen_key_gives_empty_string():
    result = _validate_analysis({"categoria": "Documentos", "etiquetas": []})
    assert result["resumen"] == ""


# ── non-dict / broken input ───────────────────────────────────────────────────


def test_non_dict_returns_empty():
    assert _validate_analysis(None) == {}
    assert _validate_analysis([1, 2, 3]) == {}
    assert _validate_analysis("string") == {}
    assert _validate_analysis(42) == {}


def test_empty_dict_normalises_gracefully():
    result = _validate_analysis({})
    _ok(result)
    assert result["categoria"] == "Desconocido"
    assert result["etiquetas"] == []
    assert result["resumen"] == ""


# ── nested / unusual structures ───────────────────────────────────────────────


def test_nested_dict_as_resumen_coerced_to_string():
    result = _validate_analysis({"categoria": "Documentos", "etiquetas": [], "resumen": {"sub": "val"}})
    assert isinstance(result["resumen"], str)


def test_tags_with_nested_list_discards_non_strings():
    tags = [["nested", "list"], "valid", {"key": "val"}]
    result = _validate_analysis({"categoria": "Datos", "etiquetas": tags, "resumen": ""})
    assert result["etiquetas"] == ["valid"]


if __name__ == "__main__":
    # Run with: python tests/test_analyzer_validation.py -v
    # or: python -m pytest tests/test_analyzer_validation.py -v
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
