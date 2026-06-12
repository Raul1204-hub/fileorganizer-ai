import hashlib
from datetime import datetime
from pathlib import Path

try:
    import magic
    _MAGIC_AVAILABLE = True
except ImportError:
    _MAGIC_AVAILABLE = False

EXTENSION_MAP: dict[str, str] = {
    ".exe": "Programas", ".msi": "Programas", ".bat": "Programas",
    ".cmd": "Programas", ".ps1": "Programas",

    ".pdf": "Documentos", ".docx": "Documentos", ".doc": "Documentos",
    ".txt": "Documentos", ".odt": "Documentos", ".xlsx": "Documentos",
    ".csv": "Documentos",

    ".jpg": "Imágenes", ".jpeg": "Imágenes", ".png": "Imágenes",
    ".gif": "Imágenes", ".bmp": "Imágenes", ".raw": "Imágenes",
    ".webp": "Imágenes",

    ".mp3": "Audio", ".wav": "Audio", ".flac": "Audio",
    ".aac": "Audio", ".ogg": "Audio",

    ".mp4": "Vídeo", ".mkv": "Vídeo", ".avi": "Vídeo",
    ".mov": "Vídeo", ".wmv": "Vídeo",

    ".py": "Código", ".js": "Código", ".ts": "Código",
    ".cpp": "Código", ".java": "Código", ".cs": "Código",
    ".html": "Código", ".css": "Código",

    ".json": "Datos", ".xml": "Datos", ".yaml": "Datos",
    ".yml": "Datos", ".sql": "Datos", ".db": "Datos",

    ".zip": "Comprimidos", ".rar": "Comprimidos", ".7z": "Comprimidos",
    ".tar": "Comprimidos", ".gz": "Comprimidos",
}

CATEGORIA_IDS: dict[str, int] = {
    "Documentos": 1,
    "Imágenes":   2,
    "Audio":      3,
    "Vídeo":      4,
    "Código":     5,
    "Datos":      6,
    "Comprimidos":7,
    "Programas":  8,
    "Desconocido":9,
}


def classify_extension(ext: str) -> str:
    return EXTENSION_MAP.get(ext.lower(), "Desconocido")


def compute_md5(path: Path) -> str:
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except (PermissionError, OSError):
        return ""


def detect_magic(path: Path) -> str:
    if not _MAGIC_AVAILABLE:
        return ""
    try:
        return magic.from_file(str(path), mime=True) or ""
    except Exception:
        return ""


def _magic_to_category(mime: str) -> str:
    if mime.startswith("image/"):
        return "Imágenes"
    if mime.startswith("audio/"):
        return "Audio"
    if mime.startswith("video/"):
        return "Vídeo"
    if mime in ("application/pdf",):
        return "Documentos"
    if mime.startswith("text/"):
        return "Documentos"
    if mime in ("application/zip", "application/x-rar-compressed",
                "application/x-7z-compressed", "application/gzip"):
        return "Comprimidos"
    return "Desconocido"


def get_file_metadata(path: Path) -> dict:
    stat = path.stat()
    ext = path.suffix.lower()
    categoria_nombre = classify_extension(ext)

    if categoria_nombre == "Desconocido":
        mime = detect_magic(path)
        if mime:
            categoria_nombre = _magic_to_category(mime)

    return {
        "nombre": path.name,
        "extension": ext,
        "ruta_actual": str(path),
        "tamaño_bytes": stat.st_size,
        "fecha_modificacion": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "categoria_nombre": categoria_nombre,
        "categoria_id": CATEGORIA_IDS.get(categoria_nombre, 9),
        "hash_md5": "",
    }


def scan_directory(
    root_path: str | Path,
    progress_callback=None,
) -> list[dict]:
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Path does not exist or is not a directory: {root_path}")

    files: list[dict] = []
    all_file_paths = [p for p in root.rglob("*") if p.is_file()]
    total = len(all_file_paths)

    for idx, path in enumerate(all_file_paths, 1):
        try:
            meta = get_file_metadata(path)
            meta["hash_md5"] = compute_md5(path)
            files.append(meta)
        except (PermissionError, OSError):
            continue
        if progress_callback:
            progress_callback(idx, total, path.name)

    return files
