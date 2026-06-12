import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pdfplumber

from config import ANALYSIS_MODEL
from ollama_client import call_ollama

_DOCX_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

# ── Validation constants ──────────────────────────────────────────────────────

_VALID_CATEGORIAS = frozenset({
    "Documentos", "Imágenes", "Audio", "Vídeo", "Código",
    "Datos", "Comprimidos", "Programas", "Desconocido",
})

# JSON Schema sent to Ollama — constrains keys and types; category enum is
# validated separately so old models that can't honour enums still work.
_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "categoria":  {"type": "string"},
        "etiquetas":  {"type": "array", "items": {"type": "string"}},
        "resumen":    {"type": "string"},
    },
    "required": ["categoria", "etiquetas", "resumen"],
}


# ── text extraction ───────────────────────────────────────────────────────────

def extract_text_pdf(path: Path) -> str:
    parts: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:10]:
                text = page.extract_text()
                if text:
                    parts.append(text)
    except Exception:
        pass
    return "\n".join(parts)[:4000]


def extract_text_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            if "word/document.xml" not in z.namelist():
                return ""
            with z.open("word/document.xml") as f:
                root = ET.parse(f).getroot()
                texts = [
                    node.text
                    for node in root.iter(f"{{{_DOCX_NS}}}t")
                    if node.text
                ]
                return " ".join(texts)[:4000]
    except Exception:
        return ""


def extract_text_xlsx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            if "xl/sharedStrings.xml" not in z.namelist():
                return ""
            with z.open("xl/sharedStrings.xml") as f:
                root = ET.parse(f).getroot()
                texts = [
                    t.text
                    for t in root.iter(f"{{{_XLSX_NS}}}t")
                    if t.text
                ]
                return " ".join(texts[:300])
    except Exception:
        return ""


def extract_text_plain(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:4000]
    except Exception:
        return ""


def extract_text(path: Path, extension: str) -> str:
    ext = extension.lower()
    if ext == ".pdf":
        return extract_text_pdf(path)
    if ext in (".docx", ".doc"):
        return extract_text_docx(path)
    if ext == ".xlsx":
        return extract_text_xlsx(path)
    if ext in (".txt", ".odt", ".csv"):
        return extract_text_plain(path)
    return ""


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_analysis(data) -> dict:
    """Normalize and validate an Ollama analysis result.

    Returns a dict with keys {categoria, etiquetas, resumen} on success,
    or {} if *data* is not a dict (caller should retry).

    Rules
    -----
    - categoria: must be in _VALID_CATEGORIAS; otherwise "Desconocido".
    - etiquetas: must be a list of strings; a bare string is wrapped in a list;
      non-string elements are discarded; stripped and capped at 5 items.
    - resumen: coerced to str, stripped, truncated to 300 characters.
    """
    if not isinstance(data, dict):
        return {}

    # categoria
    categoria = data.get("categoria", "")
    if categoria not in _VALID_CATEGORIAS:
        categoria = "Desconocido"

    # etiquetas
    raw_tags = data.get("etiquetas", [])
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    elif not isinstance(raw_tags, list):
        raw_tags = []
    etiquetas = [
        e.strip() for e in raw_tags
        if isinstance(e, str) and e.strip()
    ][:5]

    # resumen
    resumen = data.get("resumen", "")
    if not isinstance(resumen, str):
        resumen = str(resumen)
    resumen = resumen.strip()[:300]

    return {"categoria": categoria, "etiquetas": etiquetas, "resumen": resumen}


# ── Ollama analysis ───────────────────────────────────────────────────────────

def analyze_with_ollama(text: str, filename: str) -> dict:
    """Call Ollama with JSON Schema format and validate the result.

    Retries once on parse failure or non-dict response.
    Returns {} if both attempts fail or if Ollama is unavailable.
    """
    prompt = (
        f'Analyze this document named "{filename}". '
        "Respond in JSON with keys: categoria, etiquetas (list of tags), resumen.\n\n"
        f"Document content:\n{text[:2500]}"
    )

    for _attempt in range(2):
        try:
            raw = call_ollama(ANALYSIS_MODEL, prompt, fmt=_ANALYSIS_SCHEMA)
        except RuntimeError:
            return {}
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        result = _validate_analysis(data)
        if result is not None and isinstance(result, dict) and len(result) == 3:
            return result

    return {}


# ── public API ────────────────────────────────────────────────────────────────

def analyze_file(path: Path, extension: str) -> dict:
    """Extract text and analyze with Ollama.

    Returns a dict with keys {categoria, etiquetas, resumen, _text_len},
    or {} if the file has no extractable text or analysis fails.
    """
    text = extract_text(path, extension)
    if not text.strip():
        return {}
    result = analyze_with_ollama(text, path.name)
    if result:
        result["_text_len"] = len(text)
    return result
