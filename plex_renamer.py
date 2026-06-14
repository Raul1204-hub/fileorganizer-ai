"""
PLEX library renamer.

Scans a TV-show root (or library root with multiple shows) and proposes renames:

    Season 01/s01e01.mkv
    Season 02/s02e01.mkv
    Specials/s00e01.mkv

Usage:
    series = plex_renamer.scan_library(root, show_name)
    # [{series_name, series_path, ops, videos_found}]
"""

import re
from pathlib import Path

VIDEO_EXTS: frozenset[str] = frozenset({
    ".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".ts", ".m2ts",
    ".mpg", ".mpeg", ".flv", ".webm", ".vob", ".ogv", ".3gp", ".rmvb", ".divx",
})

COMPRESS_EXTS: frozenset[str] = frozenset({
    ".rar", ".zip", ".7z", ".tar", ".gz", ".bz2",
    ".r00", ".r01", ".r02", ".r03", ".r04", ".r05",
    ".r06", ".r07", ".r08", ".r09",
    ".001", ".002", ".003", ".004",
    ".nfo", ".sfv", ".nzb", ".srr",
})

_SE_PATTERNS: list[re.Pattern] = [
    re.compile(r'[Ss](\d{1,2})[Ee](\d{1,3})'),
    re.compile(r'(\d{1,2})[xX](\d{2})'),
    re.compile(r'[Ss]eason[\s._-]*(\d{1,2}).*?[Ee](?:p|pisode)?[\s._-]*(\d{1,3})', re.IGNORECASE),
    re.compile(r'(?:^|[._\s-])(\d{1,2})(\d{2})(?:[._\s-]|$)'),
]
_E_ONLY: re.Pattern = re.compile(r'(?:^|[._\s-])(?:[Ee][Pp]?\.?)(\d{1,3})(?:[._\s-]|$)')

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

# Valid PLEX folder names at series root level
_PLEX_FOLDER_RE = re.compile(
    r'^(Season\s+\d+|Specials?|Extras?|OVA|Bonus)$', re.IGNORECASE
)


def _detect_se_from_filename(name: str) -> tuple[int | None, int | None]:
    stem = Path(name).stem
    for pat in _SE_PATTERNS:
        m = pat.search(stem)
        if m:
            s, e = int(m.group(1)), int(m.group(2))
            if s > 50 or e > 200:
                continue
            return s, e
    m = _E_ONLY.search(stem)
    if m:
        ep = int(m.group(1))
        if ep <= 200:
            return None, ep
    return None, None


def _detect_season_from_folder(folder_name: str) -> int | None:
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
    name = re.sub(r'\s*[\[\(]\d{4}[\]\)]', '', name)
    name = re.sub(r'\s*[\[\(][^\]\)]{1,30}[\]\)]', '', name)
    name = re.sub(r'[._]+', ' ', name).strip().rstrip('. ')
    return name or "Show"


def _season_folder_name(season: int) -> str:
    return "Specials" if season == 0 else f"Season {season:02d}"


def _has_plex_season_folders(path: Path) -> bool:
    """Return True if path has direct Season XX / Specials subfolders."""
    try:
        return any(
            child.is_dir() and _PLEX_FOLDER_RE.match(child.name)
            for child in path.iterdir()
        )
    except PermissionError:
        return False


def scan_for_operations(root: str, show_name: str | None = None) -> list[dict]:
    """Scan a single series root and return proposed operations."""
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise ValueError(f"La carpeta no existe: {root}")

    if not show_name:
        show_name = _sanitize_show_name(root_path.name)

    ops: list[dict] = []
    seen_src: set[str] = set()

    # ── Scan video and compressed files ──────────────────────────────────────
    for item in sorted(root_path.rglob("*")):
        if not item.is_file():
            continue
        src_str = str(item)
        if src_str in seen_src:
            continue
        seen_src.add(src_str)

        ext = item.suffix.lower()

        if ext in COMPRESS_EXTS:
            ops.append({
                "type": "delete_compress",
                "src": src_str,
                "dst": None,
                "season": None,
                "episode": None,
                "src_folder": item.parent.name,
                "src_name": item.name,
                "dst_folder": None,
                "dst_name": None,
                "approved": True,
                "reason": f"Archivo comprimido/escena ({ext})",
            })
            continue

        if ext not in VIDEO_EXTS:
            continue

        season_from_folder: int | None = None
        if item.parent != root_path:
            season_from_folder = _detect_season_from_folder(item.parent.name)

        season_from_file, episode = _detect_se_from_filename(item.name)
        season = season_from_file if season_from_file is not None else season_from_folder

        if episode is None:
            ops.append({
                "type": "rename_file",
                "src": src_str,
                "dst": None,
                "season": season,
                "episode": None,
                "src_folder": item.parent.name if item.parent != root_path else ".",
                "src_name": item.name,
                "dst_folder": None,
                "dst_name": None,
                "approved": False,
                "reason": "No se pudo detectar episodio — revisión manual",
            })
            continue

        if season is None:
            season = 1

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
            "src_folder": item.parent.name if item.parent != root_path else ".",
            "src_name": item.name,
            "dst_folder": _season_folder_name(season),
            "dst_name": new_filename,
            "approved": True,
            "reason": ep_tag,
        })

    # ── Detect non-PLEX subfolders at series root ─────────────────────────────
    for child in sorted(root_path.iterdir()):
        if not child.is_dir():
            continue
        if _PLEX_FOLDER_RE.match(child.name):
            continue

        try:
            all_files = [f for f in child.rglob("*") if f.is_file()]
        except PermissionError:
            continue

        has_videos = any(f.suffix.lower() in VIDEO_EXTS for f in all_files)
        is_empty = len(all_files) == 0
        file_count = len(all_files)

        if is_empty:
            reason = "Carpeta vacía"
        elif not has_videos:
            reason = f"Sin vídeos ({file_count} archivo(s): NFO, imágenes…) — se moverá a backup"
        else:
            reason = f"Carpeta de lanzamiento escena ({file_count} archivo(s)) — se moverá a backup"

        ops.append({
            "type": "delete_folder",
            "src": str(child),
            "dst": None,
            "season": None,
            "episode": None,
            "src_folder": ".",
            "src_name": child.name,
            "dst_folder": None,
            "dst_name": None,
            "approved": True,
            "reason": reason,
            "is_empty": is_empty,
            "has_videos": has_videos,
            "file_count": file_count,
        })

    # Sort: rename_file → delete_folder → delete_compress
    def _sort_key(o: dict) -> tuple:
        return (
            {"rename_file": 0, "delete_folder": 1, "delete_compress": 2}.get(o["type"], 9),
            o.get("season") or 99,
            o.get("episode") or 999,
        )

    ops.sort(key=_sort_key)
    return ops


def scan_library(root: str, show_name: str | None = None) -> list[dict]:
    """
    Scan root as library or single series.

    Library detection: if any direct subdirectory (non-PLEX-named) contains
    Season XX folders inside it → each such subfolder is a separate series.
    Root-level PLEX folders (stray Specials/, Season XX/ at library root) do NOT
    trigger single-series mode if show folders are also present.
    Returns [{series_name, series_path, ops, videos_found}]
    """
    root_path = Path(root).resolve()

    def _make_entry(path: Path, name: str | None = None) -> dict:
        ops = scan_for_operations(str(path), name)
        videos = sum(
            1 for f in path.rglob("*")
            if f.is_file() and f.suffix.lower() in VIDEO_EXTS
        )
        return {
            "series_name": name or _sanitize_show_name(path.name),
            "series_path": str(path),
            "ops": ops,
            "videos_found": videos,
        }

    if show_name:
        return [_make_entry(root_path, show_name)]

    # Detect show folders: non-PLEX-named dirs whose children include Season XX
    series_dirs = [
        child for child in sorted(root_path.iterdir())
        if child.is_dir()
        and not _PLEX_FOLDER_RE.match(child.name)
        and _has_plex_season_folders(child)
    ]

    if series_dirs:
        # Library mode: each show folder is a separate entry
        results = []
        for child in series_dirs:
            try:
                results.append(_make_entry(child))
            except Exception:
                continue
        return results

    # No show sub-folders detected → treat root itself as a single series
    return [_make_entry(root_path, show_name)]
