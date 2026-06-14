"""Plan de organización: genera en dry-run la lista de movimientos propuestos.

Strategy (archivos normales):
    carpeta_raiz / Categoría / [subcarpeta_etiqueta] / nombre_archivo

Strategy (paquetes: juegos, aplicaciones):
    carpeta_raiz / PlataformaJuego / NombreJuego / ...ruta_relativa_interna...

Los archivos de un paquete (juego, aplicación instalada) nunca se reorganizan
individualmente — se propone mover toda la carpeta raíz del paquete de una vez,
preservando su estructura interna para no romper el software.
"""

import re
from collections import defaultdict
from pathlib import Path

import database

# ── Package / game detection ──────────────────────────────────────────────────

# Path segments that strongly suggest a file is part of an installed game/app
_PACKAGE_PATH_KEYWORDS: list[str] = [
    # Steam
    "steamapps/common",
    "steamapps\\common",
    # GOG
    "gog games",
    "gog\\games",
    # Epic Games
    "epic games",
    "epicgames",
    # EA / Origin
    "origin games",
    "ea games",
    "electronic arts",
    # Ubisoft
    "ubisoft game launcher",
    "ubisoft\\games",
    # Other known launchers / publishers
    "rockstar games",
    "battle.net",
    "blizzard entertainment",
    "bethesda.net",
    "xbox games",
    "xbox game studios",
    # Generic game folders (Spanish/English)
    "/games/",
    "\\games\\",
    "/juegos/",
    "\\juegos\\",
    # Windows system areas — never touch these
    "program files",
    "archivos de programa",
    "programdata",
    "windows\\system",
    "windows\\syswow",
    "appdata\\roaming",
    "appdata\\local",
]

# Extensions that are exclusively game/engine data files.
# When found in a folder, it's a strong signal the folder is a game package.
_GAME_DATA_EXTS: frozenset[str] = frozenset({
    # Common PC game engines / packfiles
    ".pak", ".vpk", ".bsa", ".bsb", ".esm", ".esp", ".esl",
    ".big", ".tiger", ".assets", ".unity3d", ".bundle", ".resource",
    ".forge", ".bf2", ".mpq", ".mix", ".uasset", ".umap", ".upk",
    ".gcf", ".ncf", ".gob", ".lab", ".obb",
    # Console-specific game files
    ".sfo", ".edat", ".sprx", ".self",   # PS3
    ".nsp", ".xci", ".nca", ".nsz",     # Nintendo Switch
    ".xex", ".xbx", ".xbe",             # Xbox / Xbox 360
    ".elf", ".rpx",                      # Wii U
    ".cso", ".pbp",                      # PSP
    ".3ds", ".cia",                      # Nintendo 3DS
    ".nds",                              # Nintendo DS
    ".nrm",                              # PS Vita
    ".vpk",                              # PS Vita (also used for PC games)
})

# Map console-specific extensions to their platform category name
_CONSOLE_EXT_PLATFORM: dict[str, str] = {
    ".sfo":  "Juegos PS3",
    ".edat": "Juegos PS3",
    ".sprx": "Juegos PS3",
    ".self": "Juegos PS3",
    ".nsp":  "Juegos Nintendo Switch",
    ".xci":  "Juegos Nintendo Switch",
    ".nca":  "Juegos Nintendo Switch",
    ".nsz":  "Juegos Nintendo Switch",
    ".xex":  "Juegos Xbox 360",
    ".xbx":  "Juegos Xbox 360",
    ".xbe":  "Juegos Xbox Clásico",
    ".rpx":  "Juegos Wii U",
    ".cso":  "Juegos PSP",
    ".pbp":  "Juegos PSP",
    ".3ds":  "Juegos 3DS",
    ".cia":  "Juegos 3DS",
    ".nds":  "Juegos DS",
    ".nrm":  "Juegos PS Vita",
}


def _detect_package_type(folder_path: str, direct_exts: set[str]) -> str | None:
    """Return the package category name if this folder is a game/app package.

    Returns None if the folder's files can be reorganized individually.
    """
    path_lower = folder_path.lower().replace("\\", "/")

    # 1. Console game detection via exclusive extensions (highest confidence)
    for ext, platform in _CONSOLE_EXT_PLATFORM.items():
        if ext in direct_exts:
            return platform

    # 2. Known installation/game directory paths
    if any(kw in path_lower for kw in _PACKAGE_PATH_KEYWORDS):
        return "Juegos PC"

    # 3. PC game-specific data files (engine packfiles, etc.)
    #    .ini and .cfg alone are not enough — filter them out
    game_signals = direct_exts & _GAME_DATA_EXTS
    if game_signals:
        return "Juegos PC"

    # 4. Classic Windows game/app heuristic: .exe + .dll + many different types.
    #    Requiring ≥5 distinct extension types avoids false positives on simple
    #    utilities or folders with just an installer + readme.
    if ".exe" in direct_exts and ".dll" in direct_exts and len(direct_exts) >= 5:
        return "Juegos PC"

    return None


def _sanitize_folder(name: str) -> str:
    """Strip Windows-illegal chars; keep accented letters (valid on NTFS)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    return name[:50] or "General"


def generar_plan(carpeta_raiz: str, archivo_ids: list[int] | None = None) -> int:
    """Build and persist a move plan. Returns plan_id.

    - Normal files → Categoría/Subcarpeta/archivo
    - Package files (games, apps) → PlataformaJuego/NombreJuego/...ruta_relativa...
    """
    raiz = Path(carpeta_raiz)

    archivos = database.get_all_archivos()
    if archivo_ids:
        id_set = set(archivo_ids)
        archivos = [a for a in archivos if a["id"] in id_set]

    # ── Phase 1: detect package (game/app) folders ────────────────────────────
    # Build folder → set of extensions FOR FILES DIRECTLY IN THAT FOLDER
    folder_direct_exts: dict[str, set[str]] = defaultdict(set)
    for a in archivos:
        parent = str(Path(a["ruta_actual"]).parent)
        folder_direct_exts[parent].add((a.get("extension") or "").lower())

    package_folder_type: dict[str, str] = {}
    for folder, exts in folder_direct_exts.items():
        pkg_type = _detect_package_type(folder, exts)
        if pkg_type:
            package_folder_type[folder] = pkg_type

    pkg_folder_set = set(package_folder_type.keys())

    def _find_package_root(file_path: str) -> tuple[str, str] | None:
        """Walk ancestors to find the top-most package root for this file.

        'Top-most' = the highest ancestor (shortest path) that is itself a
        detected package folder.  This is the folder we want to move as a unit.
        """
        pkg_root: str | None = None
        pkg_type: str | None = None
        for ancestor in Path(file_path).parents:
            s = str(ancestor)
            if s in pkg_folder_set:
                # Keep going — we want the HIGHEST ancestor
                pkg_root = s
                pkg_type = package_folder_type[s]
        return (pkg_root, pkg_type) if pkg_root else None

    # ── Phase 2: tags (one query, no N+1) ────────────────────────────────────
    all_tags = database.get_all_etiquetas_grouped()
    plan_id = database.insert_plan(carpeta_raiz)

    orden = 0
    for archivo in archivos:
        ruta = archivo["ruta_actual"]

        pkg_info = _find_package_root(ruta)

        if pkg_info:
            # ── Package file: preserve internal structure, move whole folder ──
            pkg_root, pkg_type = pkg_info
            try:
                rel = Path(ruta).relative_to(pkg_root)
            except ValueError:
                rel = Path(Path(ruta).name)
            pkg_name = _sanitize_folder(Path(pkg_root).name)
            destino_dir = raiz / pkg_type / pkg_name / rel.parent
            destino = destino_dir / Path(ruta).name
            motivo = f"{pkg_type} — {pkg_name}"
        else:
            # ── Normal file: organize by category + tag ───────────────────────
            cat_nombre = _sanitize_folder(archivo.get("categoria_nombre") or "Desconocido")
            tags = all_tags.get(archivo["id"], [])
            subcarpeta = _sanitize_folder(tags[0]) if tags else None
            destino_dir = raiz / cat_nombre / subcarpeta if subcarpeta else raiz / cat_nombre
            destino = destino_dir / archivo["nombre"]
            motivo = cat_nombre + ("/" + subcarpeta if subcarpeta else "")

        # Skip files already in the correct destination
        try:
            if Path(ruta).parent.resolve() == destino_dir.resolve():
                continue
        except OSError:
            pass

        database.insert_plan_item(
            plan_id=plan_id,
            archivo_id=archivo["id"],
            origen=ruta,
            destino=str(destino),
            motivo=motivo,
            orden=orden,
        )
        orden += 1

    database.update_plan_stats(plan_id)
    return plan_id


def get_destinos_unicos(plan_id: int) -> list[str]:
    """Sorted list of unique destination folder paths in the plan."""
    items = database.get_plan_items(plan_id)
    return sorted({str(Path(i["destino"]).parent) for i in items})
