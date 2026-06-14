"""
PLEX library renamer.

Scans a TV-show root folder and proposes renames following PLEX naming conventions:

    ShowRoot/
        Season 01/
            ShowName - s01e01.mkv
        Season 02/
            ShowName - s02e01.mkv
        Specials/
            ShowName - s00e01.mkv

Usage (from Flask route):
    ops = plex_renamer.scan_for_operations(root, show_name)
    # ops is a list of dicts with keys: type, src, dst, season, episode, approved, reason
"""

import re
from pathlib import Path

VIDEO_EXTS: frozenset[str] = frozenset({
    ".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".ts", ".m2ts",
    ".mpg", ".mpeg", ".flv", ".webm", ".vob", ".ogv", ".3gp", ".rmvb", ".divx",
})

# Compressed/scene-release files to flag for deletion
COMPRESS_EXTS: frozenset[str] = frozenset({
    ".rar", ".zip", ".7z", ".tar", ".gz", ".bz2",
    ".r00", ".r01", ".r02", ".r03", ".r04", ".r05",
    ".r06", ".r07", ".r08", ".r09",
    ".001", ".002", ".003", ".004",
    ".nfo", ".sfv", ".nzb", ".srr",
})

# Regex patterns to extract (season, episode) from filename stem
_SE_PATTERNS: list[re.Pattern] = [
    re.compile(r'[Ss](\d{1,2})[Ee](\d{1,3})'),                    # S01E01
    re.compile(r'(\d{1,2})[xX](\d{2})'),                           # 1x01
    re.compile(r'[Ss]eason[\s._-]*(\d{1,2}).*?[Ee](?:p|pisode)?'  # Season 1 Episode 1
               r'[\s._-]*(\d{1,3})', re.IGNORECASE),
    re.compile(r'(?:^|[._\s-])(\d{1,2})(\d{2})(?:[._\s-]|$)'),   # 102 → s01e02 (3-digit)
]
_E_ONLY: re.Pattern = re.compile(
    r'(?:^|[._\s-])(?:[Ee][Pp]?\.?)(\d{1,3})(?:[._\s-]|$)'
)

# Patterns to detect season number from a folder name
_SEASON_NUM_PATS: list[re.Pattern] = [
    re.compile(r'[Ss]eason[\s._-]*(\d{1,2})', re.IGNORECASE),
    re.compile(r'[Tt]emporada[\s._-]*(\d{1,2})', re.IGNORECASE),
    re.compile(r'[Ss]eries?[\s._-]*(\d{1,2})', re.IGNORECASE),
    re.compile(r'^[Ss](\d{1,2})$'),
    re.compile(r'^(\d{1,2})$'),
]
_SPECIALS_PAT: re.Pattern = re.compile(
    r'specials?|extras?|ova|ona|bonus|oav|ncop|nced|minisode', re.IGNORECASE
)


def _detect_se_from_filename(name: str) -> tuple[int | None, int | None]:
    """Return (season, episode) or (None, None)."""
    stem = Path(name).stem
    for pat in _SE_PATTERNS:
        m = pat.search(stem)
        if m:
            s, e = int(m.group(1)), int(m.group(2))
            # Ignore obviously bogus values (year-like 1080, 720, etc.)
            if s > 50 or e > 200:
                continue
            return s, e
    # Episode-only pattern — caller provides season from folder context
    m = _E_ONLY.search(stem)
    if m:
        ep = int(m.group(1))
        if ep <= 200:
            return None, ep
    return None, None


def _detect_season_from_folder(folder_name: str) -> int | None:
    """Return season number (0 = Specials) or None if undetectable."""
    if _SPECIALS_PAT.search(folder_name):
        return 0
    for pat in _SEASON_NUM_PATS:
        m = pat.search(folder_name)
        if m:
            s = int(m.group(1))
            if s <= 50:
                return s
    return None


def _sanitize_show_name(name: str) -> str:
    """Clean root folder name for use as show name in filenames."""
    # Remove year suffixes like (2020) or [2020]
    name = re.sub(r'\s*[\[\(]\d{4}[\]\)]', '', name)
    # Remove quality tags like [1080p], [BluRay], etc.
    name = re.sub(r'\s*[\[\(][^\]\)]{1,30}[\]\)]', '', name)
    # Replace dots/underscores with spaces
    name = re.sub(r'[._]+', ' ', name).strip().rstrip('. ')
    return name or "Show"


def _season_folder_name(season: int) -> str:
    return "Specials" if season == 0 else f"Season {season:02d}"


def scan_for_operations(root: str, show_name: str | None = None) -> list[dict]:
    """Scan root and return proposed operations.

    Each dict has:
        type:     'rename_file' | 'delete_compress'
        src:      str  — absolute source path
        dst:      str | None  — absolute destination (None for deletes)
        season:   int | None
        episode:  int | None
        approved: bool  — True by default
        reason:   str   — human-readable explanation shown in preview
    """
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise ValueError(f"La carpeta no existe o no es un directorio: {root}")

    if not show_name:
        show_name = _sanitize_show_name(root_path.name)

    ops: list[dict] = []
    seen_src: set[str] = set()

    for item in sorted(root_path.rglob("*")):
        if not item.is_file():
            continue
        src_str = str(item)
        if src_str in seen_src:
            continue
        seen_src.add(src_str)

        ext = item.suffix.lower()

        # ── Compressed / scene-release files ─────────────────────────────────
        if ext in COMPRESS_EXTS:
            ops.append({
                "type": "delete_compress",
                "src": src_str,
                "dst": None,
                "season": None,
                "episode": None,
                "approved": True,
                "reason": f"Archivo de escena/comprimido ({ext})",
            })
            continue

        # ── Only rename video files ───────────────────────────────────────────
        if ext not in VIDEO_EXTS:
            continue

        # Detect season from parent folder when file is not in root
        season_from_folder: int | None = None
        if item.parent != root_path:
            season_from_folder = _detect_season_from_folder(item.parent.name)

        season_from_file, episode = _detect_se_from_filename(item.name)

        season = season_from_file if season_from_file is not None else season_from_folder
        if episode is None:
            # Can't determine episode — skip (don't guess)
            ops.append({
                "type": "rename_file",
                "src": src_str,
                "dst": None,
                "season": season,
                "episode": None,
                "approved": False,
                "reason": "No se pudo detectar episodio — requiere revisión manual",
            })
            continue

        if season is None:
            season = 1  # Default to Season 01 when no context available

        # Build target path: root / Season XX / sXXeYY.ext  (no show name prefix)
        ep_tag = f"s{season:02d}e{episode:02d}"
        new_filename = f"{ep_tag}{ext}"
        dst_folder = root_path / _season_folder_name(season)
        dst = dst_folder / new_filename

        if str(item.resolve()) == str(dst.resolve()):
            continue  # already correct

        ops.append({
            "type": "rename_file",
            "src": src_str,
            "dst": str(dst),
            "season": season,
            "episode": episode,
            "approved": True,
            "reason": ep_tag,
        })

    # ── Detect junk folders at root level (not Season XX / Specials) ──────────
    # These are scene-release folders like "ShowName S01E09 WEB-DL 1080p"
    # After their video files have been moved, propose deleting the folder itself.
    _plex_folder_re = re.compile(
        r'^(Season\s+\d+|Specials?|Extras?|OVA|Bonus)$', re.IGNORECASE
    )
    seen_junk_folders: set[str] = set()
    for item in sorted(root_path.rglob("*")):
        if not item.is_file():
            continue
        # Only care about files directly inside non-standard root subdirectories
        try:
            rel_parts = item.relative_to(root_path).parts
        except ValueError:
            continue
        if len(rel_parts) < 2:
            continue
        top_folder = root_path / rel_parts[0]
        top_name   = rel_parts[0]
        if _plex_folder_re.match(top_name):
            continue  # it's a proper Season/Specials folder
        top_str = str(top_folder)
        if top_str in seen_junk_folders:
            continue
        seen_junk_folders.add(top_str)
        ops.append({
            "type": "delete_folder",
            "src": top_str,
            "dst": None,
            "season": None,
            "episode": None,
            "approved": True,
            "reason": f"Carpeta de lanzamiento escena — mover a backup tras extraer episodios",
        })

    # Sort: rename_file first, then delete_folder, then delete_compress
    def _sort_key(o: dict) -> tuple:
        type_order = {"rename_file": 0, "delete_folder": 1, "delete_compress": 2}
        return (type_order.get(o["type"], 9), o.get("season") or 99, o.get("episode") or 999)

    ops.sort(key=_sort_key)
    return ops
