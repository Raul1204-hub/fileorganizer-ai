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
    """Run all 7 rules in a single pass, batch-insert results."""
    database.clear_recomendaciones()

    now_iso = datetime.now().isoformat()
    cutoff_2y = (datetime.now() - timedelta(days=730)).isoformat()
    cutoff_1y = (datetime.now() - timedelta(days=365)).isoformat()
    VIDEO_EXTS = {".mp4", ".mkv"}
    TEMP_EXTS = {".tmp", ".log", ".bak"}
    VIDEO_SIZE_MIN = 500 * 1024 * 1024

    recs: list[tuple] = []  # (archivo_id, tipo, mensaje, fecha)

    # ── R1: Duplicates (requires hash GROUP BY — separate SQL query) ──────────
    conn = database.get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT hash_blake2, COUNT(*) AS cnt, GROUP_CONCAT(id) AS ids
           FROM archivos
           WHERE hash_blake2 != '' AND hash_blake2 IS NOT NULL AND existe = 1
           GROUP BY hash_blake2
           HAVING cnt > 1"""
    )
    dup_rows = cur.fetchall()
    conn.close()
    for row in dup_rows:
        ids = [int(i) for i in row["ids"].split(",")]
        msg = f"{row['cnt']} archivos duplicados detectados (mismo contenido)"
        for archivo_id in ids:
            recs.append((archivo_id, "R1", msg, now_iso))

    # ── R3: Top 5 heaviest files ──────────────────────────────────────────────
    conn = database.get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, tamaño_bytes FROM archivos WHERE existe = 1 ORDER BY tamaño_bytes DESC LIMIT 5"
    )
    heavy_rows = cur.fetchall()
    conn.close()
    for row in heavy_rows:
        mb = (row["tamaño_bytes"] or 0) / (1024 * 1024)
        recs.append((row["id"], "R3", f"Uno de los 5 archivos más pesados ({mb:.1f} MB)", now_iso))

    # ── R2, R4, R5, R6, R7: single scan of all active files ──────────────────
    all_files = database.get_all_archivos_minimal()

    cat_folders: dict[int, set] = defaultdict(set)  # categoria_id → set of parent dirs
    cat_file_ids: dict[int, list] = defaultdict(list)
    cat_names: dict[int, str] = {}

    for a in all_files:
        aid = a["id"]
        mod = a.get("fecha_modificacion") or ""
        ext = (a.get("extension") or "").lower()
        size = a.get("tamaño_bytes") or 0
        cat_id = a.get("categoria_id")

        # R2: old files
        if mod and mod < cutoff_2y:
            recs.append((aid, "R2", "Sin modificar desde hace más de 2 años", now_iso))

        # R5: sensitive names
        nombre_lower = a["nombre"].lower()
        for kw in SENSITIVE_KEYWORDS:
            if kw in nombre_lower:
                recs.append((aid, "R5", f"Nombre sugiere contenido sensible (contiene '{kw}')", now_iso))
                break

        # R6: temp files
        if ext in TEMP_EXTS:
            recs.append((aid, "R6", "Archivo temporal, probablemente innecesario", now_iso))

        # R7: heavy video not recently used
        if ext in VIDEO_EXTS and size > VIDEO_SIZE_MIN and mod and mod < cutoff_1y:
            mb = size / (1024 * 1024)
            recs.append((aid, "R7", f"Vídeo pesado ({mb:.0f} MB) sin uso reciente (más de 1 año)", now_iso))

        # R4: accumulate category → folder mapping
        if cat_id:
            parent = str(Path(a["ruta_actual"]).parent)
            cat_folders[cat_id].add(parent)
            cat_file_ids[cat_id].append(aid)

    # Fetch category names for R4 messages
    if cat_folders:
        conn = database.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, nombre FROM categorias")
        for row in cur.fetchall():
            cat_names[row["id"]] = row["nombre"]
        conn.close()

    for cat_id, folders in cat_folders.items():
        if len(folders) >= 3:
            cat_name = cat_names.get(cat_id, str(cat_id))
            n_files = len(cat_file_ids[cat_id])
            n_folders = len(folders)
            msg = f"{n_files} archivos de '{cat_name}' dispersos en {n_folders} carpetas"
            for aid in cat_file_ids[cat_id]:
                recs.append((aid, "R4", msg, now_iso))

    database.insert_recomendaciones_batch(recs)
