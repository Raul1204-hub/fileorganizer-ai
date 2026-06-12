import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
import pdfplumber

OLLAMA_BASE = "http://localhost:11434/api"
ANALYSIS_MODEL = "qwen3:8b"

_DOCX_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


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


# ── Ollama call ───────────────────────────────────────────────────────────────

def call_ollama(model: str, prompt: str, timeout: int = 180) -> str:
    try:
        resp = requests.post(
            f"{OLLAMA_BASE}/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception:
        return ""


def analyze_with_ollama(text: str, filename: str) -> dict:
    prompt = (
        f'Analyze this document named "{filename}". '
        'Reply ONLY in JSON with no extra text, no markdown, no explanation:\n'
        '{"categoria": "one of: Documentos, Imágenes, Audio, Vídeo, Código, Datos, '
        'Comprimidos, Programas, Desconocido", '
        '"etiquetas": ["tag1", "tag2", "tag3"], '
        '"resumen": "max 2 sentences"}\n\n'
        f"Document content:\n{text[:2500]}"
    )
    raw = call_ollama(ANALYSIS_MODEL, prompt)
    if not raw:
        return {}

    # Strip <think>…</think> blocks that some qwen3 models emit
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    # Find the first JSON object in the response
    try:
        match = re.search(r"\{.*?\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}


# ── public API ────────────────────────────────────────────────────────────────

def analyze_file(path: Path, extension: str) -> dict:
    """Extract text and analyze. Returns dict with categoria, etiquetas, resumen."""
    text = extract_text(path, extension)
    if not text.strip():
        return {}
    return analyze_with_ollama(text, path.name)
