"""Smoke tests — no Ollama, no network, no file-system side-effects.

Quick sanity-check for the core pure-Python functions:
  scanner.classify_extension, scanner._magic_to_category,
  chat.safety_check, analyzer._validate_analysis.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from analyzer import _validate_analysis
from chat import safety_check
from scanner import _magic_to_category, classify_extension

# ── classify_extension ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ext, expected",
    [
        (".pdf", "Documentos"),
        (".docx", "Documentos"),
        (".txt", "Documentos"),
        (".xlsx", "Documentos"),
        (".csv", "Documentos"),
        (".jpg", "Imágenes"),
        (".png", "Imágenes"),
        (".mp3", "Audio"),
        (".wav", "Audio"),
        (".mp4", "Vídeo"),
        (".mkv", "Vídeo"),
        (".py", "Código"),
        (".js", "Código"),
        (".json", "Datos"),
        (".xml", "Datos"),
        (".zip", "Comprimidos"),
        (".7z", "Comprimidos"),
        (".exe", "Programas"),
        (".msi", "Programas"),
        (".xyz", "Desconocido"),
        ("", "Desconocido"),
    ],
)
def test_classify_extension(ext, expected):
    assert classify_extension(ext) == expected


def test_classify_extension_case_insensitive():
    assert classify_extension(".PDF") == "Documentos"
    assert classify_extension(".MP3") == "Audio"
    assert classify_extension(".PY") == "Código"


# ── _magic_to_category ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mime, expected",
    [
        ("image/jpeg", "Imágenes"),
        ("image/png", "Imágenes"),
        ("image/gif", "Imágenes"),
        ("audio/mpeg", "Audio"),
        ("audio/wav", "Audio"),
        ("video/mp4", "Vídeo"),
        ("video/x-matroska", "Vídeo"),
        ("application/pdf", "Documentos"),
        ("text/plain", "Documentos"),
        ("text/html", "Documentos"),
        ("application/zip", "Comprimidos"),
        ("application/x-rar-compressed", "Comprimidos"),
        ("application/x-7z-compressed", "Comprimidos"),
        ("application/gzip", "Comprimidos"),
        ("application/octet-stream", "Desconocido"),
        ("application/x-executable", "Desconocido"),
    ],
)
def test_magic_to_category(mime, expected):
    assert _magic_to_category(mime) == expected


# ── safety_check ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM archivos",
        "SELECT nombre, tamaño_bytes FROM archivos WHERE categoria_id = 1",
        "SELECT COUNT(*) FROM archivos WHERE existe = 1",
        "SELECT a.nombre, e.etiqueta FROM archivos a JOIN etiquetas e ON e.archivo_id = a.id",
    ],
)
def test_safety_check_passes_select(sql):
    assert safety_check(sql) is True


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE archivos",
        "DELETE FROM archivos",
        "UPDATE archivos SET nombre='x'",
        "INSERT INTO archivos VALUES (1,'x','.txt','/tmp',0,'','','','',1,'')",
        "ALTER TABLE archivos ADD COLUMN evil TEXT",
        "CREATE TABLE evil (id INTEGER)",
        "TRUNCATE TABLE archivos",
        "REPLACE INTO archivos VALUES (1,'x')",
        "PRAGMA table_info(archivos)",
        "ATTACH ':memory:' AS mem",
        "VACUUM",
    ],
)
def test_safety_check_blocks_dangerous(sql):
    assert safety_check(sql) is False


def test_safety_check_requires_select():
    assert safety_check("VALUES (1, 2, 3)") is False
    assert safety_check("WITH x AS (VALUES (1)) SELECT * FROM x") is True


# ── _validate_analysis ────────────────────────────────────────────────────────


def test_validate_analysis_happy_path():
    data = {"categoria": "Documentos", "etiquetas": ["report", "finance"], "resumen": "Annual report"}
    r = _validate_analysis(data)
    assert r == {"categoria": "Documentos", "etiquetas": ["report", "finance"], "resumen": "Annual report"}


def test_validate_analysis_unknown_category_fallback():
    data = {"categoria": "Alien", "etiquetas": [], "resumen": "x"}
    assert _validate_analysis(data)["categoria"] == "Desconocido"


def test_validate_analysis_tags_capped_at_five():
    data = {"categoria": "Datos", "etiquetas": ["a", "b", "c", "d", "e", "f"], "resumen": ""}
    assert len(_validate_analysis(data)["etiquetas"]) == 5


def test_validate_analysis_resumen_truncated():
    data = {"categoria": "Código", "etiquetas": [], "resumen": "x" * 500}
    assert len(_validate_analysis(data)["resumen"]) == 300


def test_validate_analysis_non_dict_returns_empty():
    assert _validate_analysis(None) == {}
    assert _validate_analysis([1, 2]) == {}
    assert _validate_analysis("string") == {}
