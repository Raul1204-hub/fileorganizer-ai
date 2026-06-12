import hashlib
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from log import get_logger

try:
    import magic
    _MAGIC_AVAILABLE = True
except ImportError:
    _MAGIC_AVAILABLE = False

logger = get_logger("fileorganizer.scanner")

# Document extensions that always get hashed (BLAKE2b is the AI analysis cache key)
DOC_EXTS = frozenset({".pdf", ".docx", ".doc", ".txt", ".odt", ".xlsx", ".csv"})

_PREFIX_BYTES = 8192   # bytes read for quick-compare before full hash

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


# ── Hashing ───────────────────────────────────────────────────────────────────

def compute_blake2b(path: Path) -> str:
    """Full BLAKE2b hash of a file. Returns '' on permission/IO error."""
    h = hashlib.blake2b()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError as e:
        logger.warning("hash | %s | %s", path, e)
        return ""


def _read_prefix(path: Path) -> bytes:
    """Read first _PREFIX_BYTES for cheap pre-comparison."""
    try:
        with open(path, "rb") as f:
            return f.read(_PREFIX_BYTES)
    except OSError as e:
        logger.warning("read_prefix | %s | %s", path, e)
        return b""


def smart_hash_files(
    candidates: list[dict],
    all_disk_files: list[dict],
    on_progress=None,   # on_progress(ruta: str, hashed: bool) — called per candidate
    is_cancelled=None,  # is_cancelled() -> bool
) -> dict[str, str]:
    """Selective BLAKE2b hashing. Returns {ruta_actual: hex_or_empty}.

    Rules
    -----
    - Documents (DOC_EXTS) always hashed — hash is the AI analysis cache key.
    - Non-docs skipped when their size is unique on disk (can't be duplicates).
    - Same-size non-doc candidates (2+): compare first 8 KB first; only do a
      full hash when the prefix matches OR a same-size file exists in the DB
      (i.e., there are unchanged files that could be duplicates).
    - '' (empty string) means "not hashed / no access" and never groups as duplicate.
    """
    result: dict[str, str] = {f["ruta_actual"]: "" for f in candidates}
    if not candidates:
        return result

    # How many disk files share each size (includes unchanged files already in DB)
    size_freq: Counter[int] = Counter(f["tamaño_bytes"] for f in all_disk_files)

    # Group candidates by size
    by_size: dict[int, list[dict]] = defaultdict(list)
    for f in candidates:
        by_size[f["tamaño_bytes"]].append(f)

    for size, group in by_size.items():
        docs     = [f for f in group if f["extension"] in DOC_EXTS]
        non_docs = [f for f in group if f["extension"] not in DOC_EXTS]

        # Documents → always hash
        for f in docs:
            if is_cancelled and is_cancelled():
                return result
            result[f["ruta_actual"]] = compute_blake2b(Path(f["ruta_actual"]))
            if on_progress:
                on_progress(f["ruta_actual"], True)

        if not non_docs:
            continue

        if size_freq[size] < 2:
            # Unique size across entire disk scan → no duplicate possible
            for f in non_docs:
                if on_progress:
                    on_progress(f["ruta_actual"], False)
            continue

        # Unchanged files (already in DB) that share this size
        n_db_same_size = size_freq[size] - len(group)

        if len(non_docs) == 1:
            # Single candidate whose size also exists in DB → hash to allow comparison
            f = non_docs[0]
            if is_cancelled and is_cancelled():
                return result
            result[f["ruta_actual"]] = compute_blake2b(Path(f["ruta_actual"]))
            if on_progress:
                on_progress(f["ruta_actual"], True)
            continue

        # 2+ candidates with same size → 8 KB prefix-compare before full hash
        by_prefix: dict[bytes, list[dict]] = defaultdict(list)
        for f in non_docs:
            by_prefix[_read_prefix(Path(f["ruta_actual"]))].append(f)

        for prefix, pgroup in by_prefix.items():
            # Hash if: prefix shared within candidates (likely duplicate)
            #      OR  unchanged DB files with this size exist (could match)
            needs_hash = len(pgroup) >= 2 or n_db_same_size > 0
            for f in pgroup:
                if is_cancelled and is_cancelled():
                    return result
                if needs_hash:
                    result[f["ruta_actual"]] = compute_blake2b(Path(f["ruta_actual"]))
                    if on_progress:
                        on_progress(f["ruta_actual"], True)
                else:
                    if on_progress:
                        on_progress(f["ruta_actual"], False)

    return result


# ── Magic detection ───────────────────────────────────────────────────────────

def detect_magic(path: Path) -> str:
    if not _MAGIC_AVAILABLE:
        return ""
    try:
        return magic.from_file(str(path), mime=True) or ""
    except Exception as e:
        logger.warning("detect_magic | %s | %s", path, e)
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


# ── Metadata & scan ───────────────────────────────────────────────────────────

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
        "hash_blake2": "",
    }


def scan_directory(
    root_path: str | Path,
    progress_callback=None,
) -> list[dict]:
    """Full scan with BLAKE2b hash for every file."""
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Path does not exist or is not a directory: {root_path}")

    files: list[dict] = []
    all_file_paths = [p for p in root.rglob("*") if p.is_file()]
    total = len(all_file_paths)

    for idx, path in enumerate(all_file_paths, 1):
        try:
            meta = get_file_metadata(path)
            meta["hash_blake2"] = compute_blake2b(path)
            files.append(meta)
        except (PermissionError, OSError) as e:
            logger.warning("scan | %s | %s", path, e)
            continue
        if progress_callback:
            progress_callback(idx, total, path.name)

    return files


def scan_directory_fast(
    root_path: str | Path,
    progress_callback=None,
) -> list[dict]:
    """Stat-only scan — no hashing. Used by the incremental indexing pipeline."""
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Path does not exist or is not a directory: {root_path}")

    files: list[dict] = []
    all_file_paths = [p for p in root.rglob("*") if p.is_file()]
    total = len(all_file_paths)

    for idx, path in enumerate(all_file_paths, 1):
        try:
            meta = get_file_metadata(path)
            files.append(meta)
        except (PermissionError, OSError) as e:
            logger.warning("scan | %s | %s", path, e)
            continue
        if progress_callback:
            progress_callback(idx, total, path.name)

    return files
