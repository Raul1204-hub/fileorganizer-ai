"""FileOrganizer AI — intelligent file rename suggestions."""

import json
import re
import unicodedata
from pathlib import Path

from config import ANALYSIS_MODEL
from ollama_client import call_ollama

# ── Candidate-detection patterns ──────────────────────────────────────────────

_PATTERNS: list[re.Pattern] = [
    re.compile(r"^img[_\s\-]?\d+$", re.IGNORECASE),
    re.compile(r"^scan\d*", re.IGNORECASE),
    re.compile(r"^document[o]?\s*\d*$", re.IGNORECASE),
    re.compile(r"^nuevo\b", re.IGNORECASE),
    re.compile(r"^sin[_\-\s]?t[ií]tulo$", re.IGNORECASE),
    re.compile(r"^\d{8,}$"),
    re.compile(r"^whatsapp\b", re.IGNORECASE),
    re.compile(r"^copy(\s+of\b|\s*\(\d+\))", re.IGNORECASE),
    re.compile(r"^copia(\s+de\b|\s*\(\d+\))", re.IGNORECASE),
    re.compile(r"^screenshot\b", re.IGNORECASE),
    re.compile(r"^captura\b", re.IGNORECASE),
    re.compile(r"^\d{4}[-_]\d{2}[-_]\d{2}$"),
    re.compile(r"^dsc\d+$", re.IGNORECASE),
    re.compile(r"^dcim\d+$", re.IGNORECASE),
    re.compile(r"^p\d{7,}$", re.IGNORECASE),
    re.compile(r"^untitled\b", re.IGNORECASE),
    re.compile(r"^archivo\b", re.IGNORECASE),
    re.compile(r"^file\b", re.IGNORECASE),
]


def es_candidato(nombre: str) -> bool:
    """Return True if the filename looks non-descriptive."""
    stem = Path(nombre).stem
    if sum(c.isalpha() for c in stem) < 4:
        return True
    for pat in _PATTERNS:
        if pat.match(stem):
            return True
    return False


def get_candidatos() -> list[dict]:
    """Return analyzed files whose names look non-descriptive."""
    import database

    archivos = database.get_archivos_analizados()
    return [a for a in archivos if es_candidato(a["nombre"])]


# ── Sanitization ───────────────────────────────────────────────────────────────


def sanitizar_nombre(raw: str, extension: str) -> str:
    """Convert LLM-supplied text into a safe, slug-style Windows filename."""
    stem = raw.strip().strip("\"'")
    # Strip any extension the model may have included
    if "." in stem:
        stem = Path(stem).stem
    # Normalize unicode to ASCII (á→a, ñ→n, ü→u, etc.)
    stem = unicodedata.normalize("NFD", stem)
    stem = "".join(c for c in stem if unicodedata.category(c) != "Mn")
    # Lowercase
    stem = stem.lower()
    # Illegal Windows chars + whitespace + underscore → hyphen
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f\s_]', "-", stem)
    # Remove anything not alphanumeric or hyphen
    stem = re.sub(r"[^a-z0-9-]", "", stem)
    # Collapse multiple hyphens, strip surrounding hyphens
    stem = re.sub(r"-{2,}", "-", stem).strip("-")
    # Ensure extension has a leading dot
    ext = extension if extension.startswith(".") else f".{extension}"
    if ext == ".":
        ext = ""
    # Truncate: keep total ≤ 64 chars
    max_stem = 60 - len(ext)
    if len(stem) > max_stem:
        stem = stem[:max_stem].rstrip("-")
    return (stem or "archivo") + ext


# ── Suggestion ────────────────────────────────────────────────────────────────


def sugerir_nombre(archivo: dict) -> str | None:
    """Ask ANALYSIS_MODEL for a descriptive filename.

    Returns sanitized full filename (stem + ext) or None on failure.
    """
    nombre = archivo.get("nombre", "")
    resumen = (archivo.get("resumen_ia") or "").strip()
    etiquetas = archivo.get("etiquetas") or []
    if isinstance(etiquetas, str):
        etiquetas = [etiquetas]
    etiquetas_str = ", ".join(str(t) for t in etiquetas) if etiquetas else "—"
    extension = Path(nombre).suffix.lower()

    prompt_lines = [
        "Eres un asistente que genera nombres de archivo descriptivos.",
        "",
        f"Archivo: {nombre}",
        f"Resumen: {resumen[:600]}",
        f"Etiquetas: {etiquetas_str}",
        "",
        "Devuelve SOLO un objeto JSON con esta clave:",
        '{"nombre_sugerido": "..."}',
        "",
        "Reglas para nombre_sugerido (solo el nombre base, sin extensión):",
        "- Minúsculas, palabras separadas por guiones",
        "- Sin espacios, acentos ni caracteres especiales",
        "- Máximo 55 caracteres",
        "- Incluye fecha si el contenido la menciona (YYYY-MM o YYYY-MM-DD)",
        "- En español, descriptivo y específico",
        "- Sin artículos ni preposiciones al inicio",
        "",
        'Ejemplos: "factura-luz-marzo-2026", "contrato-alquiler-2025-01"',
        "",
        "JSON únicamente, sin explicación:",
    ]
    prompt = "\n".join(prompt_lines)

    try:
        raw = call_ollama(ANALYSIS_MODEL, prompt, fmt="json")
    except RuntimeError:
        return None
    if not raw:
        return None

    nombre_sugerido = ""
    try:
        data = json.loads(raw)
        nombre_sugerido = data.get("nombre_sugerido", "")
    except (json.JSONDecodeError, AttributeError):
        m = re.search(r'"nombre_sugerido"\s*:\s*"([^"]+)"', raw)
        if m:
            nombre_sugerido = m.group(1)

    if not nombre_sugerido:
        return None

    result = sanitizar_nombre(nombre_sugerido, extension)
    # Reject no-op renames
    if result.lower() == nombre.lower():
        return None
    return result
