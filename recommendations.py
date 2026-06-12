from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import database

SENSITIVE_KEYWORDS = [
    "password",
    "contraseña",
    "credential",
    "token",
    "secret",
    "passwd",
    "clave",
    "apikey",
    "api_key",
]


def run_all_rules():
    """Run all 7 rules, clearing old recommendations first."""
    database.clear_recomendaciones()
    r1_duplicates()
    r2_old_files()
    r3_heavy_files()
    r4_scattered_categories()
    r5_sensitive_names()
    r6_temp_files()
    r7_heavy_video()


# ── R1: Duplicates ────────────────────────────────────────────────────────────


def r1_duplicates():
    conn = database.get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT hash_blake2, COUNT(*) AS cnt, GROUP_CONCAT(id) AS ids
           FROM archivos
           WHERE hash_blake2 != '' AND hash_blake2 IS NOT NULL
           GROUP BY hash_blake2
           HAVING cnt > 1"""
    )
    rows = cur.fetchall()
    conn.close()
    for row in rows:
        ids = [int(i) for i in row["ids"].split(",")]
        for archivo_id in ids:
            database.insert_recomendacion(
                archivo_id,
                "R1",
                f"{row['cnt']} archivos duplicados detectados (mismo contenido)",
            )


# ── R2: Old files (>2 years without modification) ────────────────────────────


def r2_old_files():
    cutoff = (datetime.now() - timedelta(days=730)).isoformat()
    for a in database.get_all_archivos():
        mod = a.get("fecha_modificacion") or ""
        if mod and mod < cutoff:
            database.insert_recomendacion(
                a["id"],
                "R2",
                "Sin modificar desde hace más de 2 años",
            )


# ── R3: Top 5 heaviest files ──────────────────────────────────────────────────


def r3_heavy_files():
    conn = database.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, nombre, tamaño_bytes FROM archivos ORDER BY tamaño_bytes DESC LIMIT 5")
    rows = cur.fetchall()
    conn.close()
    for row in rows:
        mb = (row["tamaño_bytes"] or 0) / (1024 * 1024)
        database.insert_recomendacion(
            row["id"],
            "R3",
            f"Uno de los 5 archivos más pesados ({mb:.1f} MB)",
        )


# ── R4: Same category scattered across 3+ folders ────────────────────────────


def r4_scattered_categories():
    conn = database.get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT c.nombre AS cat, a.id, a.ruta_actual
           FROM archivos a
           JOIN categorias c ON a.categoria_id = c.id"""
    )
    rows = cur.fetchall()
    conn.close()

    cat_folders: dict[str, set] = defaultdict(set)
    cat_files: dict[str, list] = defaultdict(list)
    for row in rows:
        parent = str(Path(row["ruta_actual"]).parent)
        cat_folders[row["cat"]].add(parent)
        cat_files[row["cat"]].append(row["id"])

    for cat, folders in cat_folders.items():
        if len(folders) >= 3:
            n_files = len(cat_files[cat])
            n_folders = len(folders)
            for archivo_id in cat_files[cat]:
                database.insert_recomendacion(
                    archivo_id,
                    "R4",
                    f"{n_files} archivos de '{cat}' dispersos en {n_folders} carpetas",
                )


# ── R5: Sensitive filenames ───────────────────────────────────────────────────


def r5_sensitive_names():
    for a in database.get_all_archivos():
        nombre_lower = a["nombre"].lower()
        for kw in SENSITIVE_KEYWORDS:
            if kw in nombre_lower:
                database.insert_recomendacion(
                    a["id"],
                    "R5",
                    f"Nombre sugiere contenido sensible (contiene '{kw}')",
                )
                break


# ── R6: Temp / log / bak files ───────────────────────────────────────────────


def r6_temp_files():
    TEMP_EXTS = {".tmp", ".log", ".bak"}
    for a in database.get_all_archivos():
        if (a.get("extension") or "").lower() in TEMP_EXTS:
            database.insert_recomendacion(
                a["id"],
                "R6",
                "Archivo temporal, probablemente innecesario",
            )


# ── R7: Heavy video not recently used ────────────────────────────────────────


def r7_heavy_video():
    VIDEO_EXTS = {".mp4", ".mkv"}
    SIZE_LIMIT = 500 * 1024 * 1024  # 500 MB
    cutoff = (datetime.now() - timedelta(days=365)).isoformat()
    for a in database.get_all_archivos():
        ext = (a.get("extension") or "").lower()
        size = a.get("tamaño_bytes") or 0
        modified = a.get("fecha_modificacion") or ""
        if ext in VIDEO_EXTS and size > SIZE_LIMIT and modified < cutoff:
            mb = size / (1024 * 1024)
            database.insert_recomendacion(
                a["id"],
                "R7",
                f"Vídeo pesado ({mb:.0f} MB) sin uso reciente (más de 1 año)",
            )
