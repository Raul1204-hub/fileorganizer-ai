import sqlite3
from datetime import datetime
from pathlib import Path

from config import DB_PATH

CATEGORIAS_SEED = [
    (1,  "Documentos",  "#4F46E5", "📄"),
    (2,  "Imágenes",    "#10B981", "🖼️"),
    (3,  "Audio",       "#F59E0B", "🎵"),
    (4,  "Vídeo",       "#EF4444", "🎬"),
    (5,  "Código",      "#8B5CF6", "💻"),
    (6,  "Datos",       "#06B6D4", "🗄️"),
    (7,  "Comprimidos", "#6B7280", "📦"),
    (8,  "Programas",   "#F97316", "⚙️"),
    (9,  "Desconocido", "#9CA3AF", "❓"),
    (10, "Libros",      "#7C3AED", "📚"),
    (11, "Internet",    "#0EA5E9", "🌐"),
    (12, "Fuentes",     "#EC4899", "🔤"),
    (13, "Sistema",     "#64748B", "🔧"),
    (14, "Diseño",      "#F43F5E", "🎨"),
]


def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# SQLite authorizer action codes (from sqlite3.h)
_SQLITE_READ = 20
_SQLITE_SELECT = 21
_SQLITE_FUNCTION = 31
_SQLITE_OK = 0
_SQLITE_DENY = 1


def _readonly_authorizer(action_code, arg1, arg2, db_name, trigger_name):
    """Allow only read operations; deny everything else."""
    if action_code in (_SQLITE_SELECT, _SQLITE_READ, _SQLITE_FUNCTION):
        return _SQLITE_OK
    return _SQLITE_DENY


def get_readonly_connection():
    """Open DB in URI read-only mode with a write-denying authorizer.

    Two layers of enforcement:
    - mode=ro   → OS-level read-only file open; writes fail at the kernel
    - authorizer → denies non-read opcodes at SQL compile time, before execution
    """
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    # Set busy_timeout BEFORE installing the authorizer (PRAGMA would be denied after)
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.set_authorizer(_readonly_authorizer)
    return conn


def create_tables():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS categorias (
            id     INTEGER PRIMARY KEY,
            nombre TEXT NOT NULL,
            color  TEXT,
            icono  TEXT
        );

        CREATE TABLE IF NOT EXISTS archivos (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre             TEXT NOT NULL,
            extension          TEXT,
            ruta_actual        TEXT NOT NULL,
            tamaño_bytes       INTEGER,
            fecha_modificacion TEXT,
            fecha_indexado     TEXT,
            hash_md5           TEXT,
            hash_blake2        TEXT DEFAULT '',
            categoria_id       INTEGER REFERENCES categorias(id),
            resumen_ia         TEXT,
            texto_via          TEXT,
            existe             INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS etiquetas (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            archivo_id INTEGER REFERENCES archivos(id),
            etiqueta   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS historial (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            archivo_id   INTEGER REFERENCES archivos(id),
            ruta_origen  TEXT,
            ruta_destino TEXT,
            operacion    TEXT,
            fecha        TEXT,
            revertido    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS recomendaciones (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            archivo_id INTEGER REFERENCES archivos(id),
            tipo       TEXT,
            mensaje    TEXT,
            fecha      TEXT,
            vista      INTEGER DEFAULT 0,
            descartada INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS conversaciones (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo                 TEXT NOT NULL DEFAULT 'Nueva conversación',
            anclada                INTEGER DEFAULT 0,
            fecha_creacion         TEXT,
            fecha_ultima_actividad TEXT
        );

        CREATE TABLE IF NOT EXISTS chat_historial (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            pregunta         TEXT,
            sql_generada     TEXT,
            respuesta        TEXT,
            fecha            TEXT,
            conversacion_id  INTEGER REFERENCES conversaciones(id)
        );

        CREATE TABLE IF NOT EXISTS backup_operaciones (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            archivo_id      INTEGER REFERENCES archivos(id),
            nombre_original TEXT NOT NULL,
            ruta_original   TEXT NOT NULL,
            ruta_nueva      TEXT,
            operacion       TEXT,
            fecha_operacion TEXT,
            revertido       INTEGER DEFAULT 0,
            fecha_reversion TEXT
        );

        CREATE TABLE IF NOT EXISTS embeddings (
            archivo_id      INTEGER PRIMARY KEY REFERENCES archivos(id),
            vector          BLOB NOT NULL,
            dim             INTEGER NOT NULL DEFAULT 0,
            fecha_embedding TEXT
        );

        CREATE TABLE IF NOT EXISTS planes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre          TEXT,
            carpeta_raiz    TEXT NOT NULL,
            estado          TEXT DEFAULT 'borrador',
            fecha_creacion  TEXT,
            fecha_aplicado  TEXT,
            total_items     INTEGER DEFAULT 0,
            items_aplicados INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS plan_items (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id       INTEGER NOT NULL REFERENCES planes(id),
            archivo_id    INTEGER REFERENCES archivos(id),
            tipo          TEXT DEFAULT 'mover',
            origen        TEXT NOT NULL,
            destino       TEXT NOT NULL,
            motivo        TEXT,
            estado        TEXT DEFAULT 'aprobado',
            mensaje_error TEXT,
            backup_id     INTEGER,
            orden         INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS ejecuciones (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo         TEXT NOT NULL,
            descripcion  TEXT,
            fecha_inicio TEXT NOT NULL,
            fecha_fin    TEXT,
            estado       TEXT DEFAULT 'en_progreso',
            stats_json   TEXT
        );

        CREATE TABLE IF NOT EXISTS log_entradas (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ejecucion_id INTEGER NOT NULL,
            timestamp    TEXT NOT NULL,
            nivel        TEXT NOT NULL,
            mensaje      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS config (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        );
    """)
    for cat_id, nombre, color, icono in CATEGORIAS_SEED:
        cur.execute(
            "INSERT OR IGNORE INTO categorias (id, nombre, color, icono) VALUES (?, ?, ?, ?)",
            (cat_id, nombre, color, icono),
        )
    conn.commit()
    conn.close()
    migrate_schema()


def migrate_schema():
    """Idempotent: add columns introduced after initial release.

    hash_blake2 replaces hash_md5 (BLAKE2b is faster and stdlib-only).
    Old hash_md5 values are intentionally left in the column but ignored;
    hash_blake2 is empty for all existing rows and will be filled on next scan.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(archivos)")
    existing_cols = {row["name"] for row in cur.fetchall()}
    if "existe" not in existing_cols:
        cur.execute("ALTER TABLE archivos ADD COLUMN existe INTEGER DEFAULT 1")
        cur.execute("UPDATE archivos SET existe = 1 WHERE existe IS NULL")
    if "hash_blake2" not in existing_cols:
        cur.execute("ALTER TABLE archivos ADD COLUMN hash_blake2 TEXT DEFAULT ''")
    if "texto_via" not in existing_cols:
        cur.execute("ALTER TABLE archivos ADD COLUMN texto_via TEXT")
    if "fecha_acceso" not in existing_cols:
        cur.execute("ALTER TABLE archivos ADD COLUMN fecha_acceso TEXT")
    if "fecha_creacion" not in existing_cols:
        cur.execute("ALTER TABLE archivos ADD COLUMN fecha_creacion TEXT")
    # chat_historial: add conversacion_id column if missing
    cur.execute("PRAGMA table_info(chat_historial)")
    chat_cols = {row["name"] for row in cur.fetchall()}
    if "conversacion_id" not in chat_cols:
        cur.execute("ALTER TABLE chat_historial ADD COLUMN conversacion_id INTEGER")
    if "resultados_json" not in chat_cols:
        cur.execute("ALTER TABLE chat_historial ADD COLUMN resultados_json TEXT")
    # New tables for execution log feature (idempotent)
    cur.execute("""CREATE TABLE IF NOT EXISTS ejecuciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL,
        descripcion TEXT, fecha_inicio TEXT NOT NULL,
        fecha_fin TEXT, estado TEXT DEFAULT 'en_progreso', stats_json TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS log_entradas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ejecucion_id INTEGER NOT NULL,
        timestamp TEXT NOT NULL, nivel TEXT NOT NULL, mensaje TEXT NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS config (
        clave TEXT PRIMARY KEY, valor TEXT NOT NULL)""")
    # Ensure all current categories exist in existing DBs
    for cat_id, nombre, color, icono in CATEGORIAS_SEED:
        cur.execute(
            "INSERT OR IGNORE INTO categorias (id, nombre, color, icono) VALUES (?, ?, ?, ?)",
            (cat_id, nombre, color, icono),
        )
    conn.commit()
    conn.close()


# ── archivos ──────────────────────────────────────────────────────────────────


def insert_archivo(
    nombre,
    extension,
    ruta_actual,
    tamaño_bytes,
    fecha_modificacion,
    hash_blake2,
    categoria_id,
    resumen_ia=None,
    fecha_acceso=None,
    fecha_creacion=None,
):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO archivos
           (nombre, extension, ruta_actual, tamaño_bytes, fecha_modificacion,
            fecha_indexado, hash_blake2, categoria_id, resumen_ia,
            fecha_acceso, fecha_creacion)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            nombre,
            extension,
            str(ruta_actual),
            tamaño_bytes,
            fecha_modificacion,
            datetime.now().isoformat(),
            hash_blake2,
            categoria_id,
            resumen_ia,
            fecha_acceso,
            fecha_creacion,
        ),
    )
    archivo_id = cur.lastrowid
    conn.commit()
    conn.close()
    return archivo_id


def insert_archivos_batch(files: list[dict]) -> list[int]:
    """Batch-insert multiple archivos rows.

    Each dict must have keys: nombre, extension, ruta_actual, tamaño_bytes,
    fecha_modificacion, hash_blake2, categoria_id, fecha_acceso, fecha_creacion.
    Returns list of inserted IDs in the same order as ``files``.
    """
    if not files:
        return []
    now = datetime.now().isoformat()
    conn = get_connection()
    cur = conn.cursor()
    ids: list[int] = []
    for f in files:
        cur.execute(
            """INSERT INTO archivos
               (nombre, extension, ruta_actual, tamaño_bytes, fecha_modificacion,
                fecha_indexado, hash_blake2, categoria_id,
                fecha_acceso, fecha_creacion)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f["nombre"],
                f["extension"],
                str(f["ruta_actual"]),
                f["tamaño_bytes"],
                f["fecha_modificacion"],
                now,
                f.get("hash_blake2", ""),
                f["categoria_id"],
                f.get("fecha_acceso"),
                f.get("fecha_creacion"),
            ),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return ids


def insert_historial_batch(entries: list[tuple]) -> None:
    """Batch-insert multiple historial rows.

    Each tuple: (archivo_id, ruta_origen, ruta_destino, operacion).
    """
    if not entries:
        return
    now = datetime.now().isoformat()
    conn = get_connection()
    cur = conn.cursor()
    cur.executemany(
        """INSERT INTO historial (archivo_id, ruta_origen, ruta_destino, operacion, fecha, revertido)
           VALUES (?, ?, ?, ?, ?, 0)""",
        [
            (
                e[0],
                str(e[1]) if e[1] else None,
                str(e[2]) if e[2] else None,
                e[3],
                now,
            )
            for e in entries
        ],
    )
    conn.commit()
    conn.close()


def get_archivo(archivo_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT a.*, c.nombre AS categoria_nombre, c.color AS categoria_color,
                  c.icono AS categoria_icono
           FROM archivos a
           LEFT JOIN categorias c ON a.categoria_id = c.id
           WHERE a.id = ?""",
        (archivo_id,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_archivos(limit=None, offset=0, categoria_id=None, search=None):
    conn = get_connection()
    cur = conn.cursor()
    query = """SELECT a.*, c.nombre AS categoria_nombre, c.color AS categoria_color,
                      c.icono AS categoria_icono
               FROM archivos a
               LEFT JOIN categorias c ON a.categoria_id = c.id
               WHERE a.existe = 1"""
    params: list = []
    if categoria_id:
        query += " AND a.categoria_id = ?"
        params.append(categoria_id)
    if search:
        query += " AND (a.nombre LIKE ? OR a.resumen_ia LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    query += " ORDER BY a.fecha_indexado DESC"
    if limit:
        query += f" LIMIT {int(limit)} OFFSET {int(offset)}"
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_archivo_ruta(archivo_id, nueva_ruta):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE archivos SET ruta_actual = ? WHERE id = ?", (str(nueva_ruta), archivo_id))
    conn.commit()
    conn.close()


def update_archivo_resumen(archivo_id, resumen_ia, categoria_id=None, texto_via=None):
    conn = get_connection()
    cur = conn.cursor()
    sets = ["resumen_ia = ?"]
    params: list = [resumen_ia]
    if categoria_id:
        sets.append("categoria_id = ?")
        params.append(categoria_id)
    if texto_via:
        sets.append("texto_via = ?")
        params.append(texto_via)
    params.append(archivo_id)
    cur.execute(f"UPDATE archivos SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()


def delete_all_archivos():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM etiquetas")
    cur.execute("DELETE FROM archivos")
    conn.commit()
    conn.close()


def get_all_archivos_indexed(under_path: str | None = None) -> dict:
    """Return {ruta_actual: row_dict} for ALL rows including disappeared ones.

    If under_path is given, only returns rows whose ruta_actual starts with that
    prefix (case-insensitive LIKE on Windows paths).  This scopes reconciliation
    to the directory that was just scanned so files from other directories are
    never marked as disappeared.
    """
    conn = get_connection()
    cur = conn.cursor()
    if under_path:
        # Normalize to forward-slash prefix and use LIKE for Windows-style paths
        prefix = str(under_path).rstrip("/\\").replace("\\", "/")
        cur.execute(
            "SELECT id, ruta_actual, tamaño_bytes, fecha_modificacion, hash_blake2, resumen_ia, existe "
            "FROM archivos WHERE REPLACE(ruta_actual, '\\', '/') LIKE ? OR REPLACE(ruta_actual, '\\', '/') = ?",
            (prefix + "/%", prefix),
        )
    else:
        cur.execute(
            "SELECT id, ruta_actual, tamaño_bytes, fecha_modificacion, hash_blake2, resumen_ia, existe "
            "FROM archivos"
        )
    rows = cur.fetchall()
    conn.close()
    return {r["ruta_actual"]: dict(r) for r in rows}


def get_archivo_by_ruta(ruta: str) -> dict | None:
    """Return the archivos row for a given path, or None if not found."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, ruta_actual, tamaño_bytes, fecha_modificacion, hash_blake2, resumen_ia, existe "
        "FROM archivos WHERE ruta_actual = ?",
        (str(ruta),),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def move_directory_archivos(old_prefix: str, new_prefix: str) -> int:
    """Update ruta_actual for all files whose path starts with old_prefix.

    Used when a watched directory is renamed/moved so every child record
    gets its path updated atomically.  Returns the number of rows changed.
    """
    old_p = Path(old_prefix)
    new_p = Path(new_prefix)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, ruta_actual FROM archivos WHERE existe = 1")
    rows = cur.fetchall()
    count = 0
    for row in rows:
        try:
            rel = Path(row["ruta_actual"]).relative_to(old_p)
        except ValueError:
            continue
        new_ruta = str(new_p / rel)
        cur.execute("UPDATE archivos SET ruta_actual = ? WHERE id = ?", (new_ruta, row["id"]))
        count += 1
    if count:
        conn.commit()
    conn.close()
    return count


def mark_archivos_bajo_ruta_desaparecidos(prefix: str) -> int:
    """Mark all existing files whose path starts with prefix as disappeared (existe=0).

    Used when a watched directory is deleted so every child record is
    updated to reflect that the files are gone.  Returns the count updated.
    """
    prefix_p = Path(prefix)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, ruta_actual FROM archivos WHERE existe = 1")
    rows = cur.fetchall()
    count = 0
    for row in rows:
        try:
            Path(row["ruta_actual"]).relative_to(prefix_p)
        except ValueError:
            continue
        cur.execute("UPDATE archivos SET existe = 0 WHERE id = ?", (row["id"],))
        count += 1
    if count:
        conn.commit()
    conn.close()
    return count


# ── embeddings ────────────────────────────────────────────────────────────────


def upsert_embedding(archivo_id: int, vector: bytes, dim: int = 0) -> None:
    """Insert or replace the embedding vector for a file."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO embeddings (archivo_id, vector, dim, fecha_embedding)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(archivo_id) DO UPDATE SET
               vector = excluded.vector,
               dim = excluded.dim,
               fecha_embedding = excluded.fecha_embedding""",
        (archivo_id, vector, dim, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_all_embeddings() -> list[dict]:
    """Return all stored embedding rows as list of {archivo_id, vector: bytes}."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT archivo_id, vector FROM embeddings")
    rows = cur.fetchall()
    conn.close()
    return [{"archivo_id": r["archivo_id"], "vector": bytes(r["vector"])} for r in rows]


def delete_embedding(archivo_id: int) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM embeddings WHERE archivo_id = ?", (archivo_id,))
    conn.commit()
    conn.close()


def get_archivos_sin_embedding() -> list[dict]:
    """Return analyzed files that still lack an embedding (for backfill)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT a.id, a.nombre, a.resumen_ia
           FROM archivos a
           WHERE a.resumen_ia IS NOT NULL AND a.existe = 1
             AND a.id NOT IN (SELECT archivo_id FROM embeddings)
           ORDER BY a.fecha_indexado DESC"""
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_archivo_full(
    archivo_id, nombre, extension, ruta_actual, tamaño_bytes, fecha_modificacion,
    hash_blake2, categoria_id, fecha_acceso=None, fecha_creacion=None,
):
    """Update metadata for a modified file; preserves resumen_ia and etiquetas rows."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE archivos
           SET nombre=?, extension=?, ruta_actual=?, tamaño_bytes=?,
               fecha_modificacion=?, hash_blake2=?, categoria_id=?, existe=1,
               fecha_acceso=?, fecha_creacion=?
           WHERE id=?""",
        (
            nombre,
            extension,
            str(ruta_actual),
            tamaño_bytes,
            fecha_modificacion,
            hash_blake2,
            categoria_id,
            fecha_acceso,
            fecha_creacion,
            archivo_id,
        ),
    )
    conn.commit()
    conn.close()


def mark_archivo_desaparecido(archivo_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE archivos SET existe = 0 WHERE id = ?", (archivo_id,))
    conn.commit()
    conn.close()


def mark_archivos_desaparecidos_batch(archivo_ids: list[int]) -> None:
    """Batch-update existe=0 for multiple files in a single transaction."""
    if not archivo_ids:
        return
    conn = get_connection()
    cur = conn.cursor()
    # SQLite parameter limit is 999; process in chunks
    for i in range(0, len(archivo_ids), 500):
        chunk = archivo_ids[i : i + 500]
        placeholders = ",".join("?" * len(chunk))
        cur.execute(f"UPDATE archivos SET existe = 0 WHERE id IN ({placeholders})", chunk)
    conn.commit()
    conn.close()


def mark_archivo_existe(archivo_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE archivos SET existe = 1 WHERE id = ?", (archivo_id,))
    conn.commit()
    conn.close()


def get_resumen_by_hash(hash_blake2: str) -> dict | None:
    """Return {id, resumen_ia} for an existing file with matching BLAKE2b hash and cached resumen."""
    if not hash_blake2:
        return None
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, resumen_ia FROM archivos WHERE hash_blake2 = ? AND resumen_ia IS NOT NULL LIMIT 1",
        (hash_blake2,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def copy_etiquetas(source_id: int, dest_id: int):
    """Duplicate all etiquetas rows from source_id to dest_id."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT etiqueta FROM etiquetas WHERE archivo_id = ?", (source_id,))
    tags = [r["etiqueta"] for r in cur.fetchall()]
    for tag in tags:
        cur.execute("INSERT INTO etiquetas (archivo_id, etiqueta) VALUES (?, ?)", (dest_id, tag))
    conn.commit()
    conn.close()


def clear_etiquetas_archivo(archivo_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM etiquetas WHERE archivo_id = ?", (archivo_id,))
    conn.commit()
    conn.close()


# ── etiquetas ─────────────────────────────────────────────────────────────────


def insert_etiqueta(archivo_id, etiqueta):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO etiquetas (archivo_id, etiqueta) VALUES (?, ?)", (archivo_id, etiqueta))
    conn.commit()
    conn.close()


def get_etiquetas_by_archivo(archivo_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT etiqueta FROM etiquetas WHERE archivo_id = ?", (archivo_id,))
    rows = cur.fetchall()
    conn.close()
    return [r["etiqueta"] for r in rows]


def get_all_etiquetas():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT etiqueta FROM etiquetas LIMIT 50")
    rows = cur.fetchall()
    conn.close()
    return [r["etiqueta"] for r in rows]


# ── historial ─────────────────────────────────────────────────────────────────


def insert_historial(archivo_id, ruta_origen, ruta_destino, operacion):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO historial (archivo_id, ruta_origen, ruta_destino, operacion, fecha, revertido)
           VALUES (?, ?, ?, ?, ?, 0)""",
        (
            archivo_id,
            str(ruta_origen) if ruta_origen else None,
            str(ruta_destino) if ruta_destino else None,
            operacion,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_historial(limit=25, offset=0):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT h.*, a.nombre AS archivo_nombre
           FROM historial h
           LEFT JOIN archivos a ON h.archivo_id = a.id
           ORDER BY h.fecha DESC
           LIMIT ? OFFSET ?""",
        (limit, offset),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_historial_count():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS total FROM historial")
    row = cur.fetchone()
    conn.close()
    return row["total"] if row else 0


def get_historial_by_archivo(archivo_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM historial WHERE archivo_id = ? ORDER BY fecha DESC",
        (archivo_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── recomendaciones ───────────────────────────────────────────────────────────


def insert_recomendacion(archivo_id, tipo, mensaje):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM recomendaciones WHERE archivo_id = ? AND tipo = ? AND descartada = 0",
        (archivo_id, tipo),
    )
    if cur.fetchone():
        conn.close()
        return
    cur.execute(
        """INSERT INTO recomendaciones (archivo_id, tipo, mensaje, fecha, vista, descartada)
           VALUES (?, ?, ?, ?, 0, 0)""",
        (archivo_id, tipo, mensaje, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_recomendaciones(solo_activas=True, limit=100):
    conn = get_connection()
    cur = conn.cursor()
    query = """SELECT r.*, a.nombre AS archivo_nombre, a.ruta_actual
               FROM recomendaciones r
               LEFT JOIN archivos a ON r.archivo_id = a.id
               WHERE 1=1"""
    if solo_activas:
        query += " AND r.descartada = 0"
    query += f" ORDER BY r.fecha DESC LIMIT {int(limit)}"
    cur.execute(query)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_recomendaciones_batch(rows: list[tuple]) -> None:
    """Batch-insert recommendations in a single transaction.

    Each row must be (archivo_id, tipo, mensaje, fecha_str).
    Called after clear_recomendaciones() so no duplicate check is needed.
    """
    if not rows:
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.executemany(
        "INSERT INTO recomendaciones (archivo_id, tipo, mensaje, fecha, vista, descartada) VALUES (?, ?, ?, ?, 0, 0)",
        rows,
    )
    conn.commit()
    conn.close()


def get_all_archivos_minimal() -> list[dict]:
    """Lightweight fetch of all active files — only columns needed by recommendation rules."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, nombre, extension, ruta_actual, tamaño_bytes, fecha_modificacion, categoria_id "
        "FROM archivos WHERE existe = 1"
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def descartar_recomendacion(rec_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE recomendaciones SET descartada = 1 WHERE id = ?", (rec_id,))
    conn.commit()
    conn.close()


def clear_recomendaciones():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM recomendaciones")
    conn.commit()
    conn.close()


# ── chat_historial ────────────────────────────────────────────────────────────


def insert_chat_historial(pregunta, sql_generada, respuesta, conversacion_id=None, resultados=None):
    import json as _json
    conn = get_connection()
    cur = conn.cursor()
    resultados_json = _json.dumps(resultados[:6], default=str) if resultados else None
    cur.execute(
        "INSERT INTO chat_historial (pregunta, sql_generada, respuesta, fecha, conversacion_id, resultados_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (pregunta, sql_generada, respuesta, datetime.now().isoformat(), conversacion_id, resultados_json),
    )
    conn.commit()
    conn.close()


def get_chat_historial(limit=5):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM chat_historial ORDER BY fecha DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── conversaciones ────────────────────────────────────────────────────────────


def create_conversacion(titulo: str = "Nueva conversación") -> int:
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    cur.execute(
        "INSERT INTO conversaciones (titulo, fecha_creacion, fecha_ultima_actividad) VALUES (?, ?, ?)",
        (titulo, now, now),
    )
    conv_id = cur.lastrowid
    conn.commit()
    conn.close()
    return conv_id


def get_conversaciones() -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM conversaciones ORDER BY anclada DESC, fecha_ultima_actividad DESC"
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_conversacion(conv_id: int) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM conversaciones WHERE id = ?", (conv_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def update_conversacion_titulo(conv_id: int, titulo: str) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE conversaciones SET titulo = ? WHERE id = ?", (titulo.strip()[:80], conv_id))
    conn.commit()
    conn.close()


def toggle_conversacion_anclada(conv_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT anclada FROM conversaciones WHERE id = ?", (conv_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False
    new_val = 0 if row["anclada"] else 1
    cur.execute("UPDATE conversaciones SET anclada = ? WHERE id = ?", (new_val, conv_id))
    conn.commit()
    conn.close()
    return bool(new_val)


def delete_conversacion(conv_id: int) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM chat_historial WHERE conversacion_id = ?", (conv_id,))
    cur.execute("DELETE FROM conversaciones WHERE id = ?", (conv_id,))
    conn.commit()
    conn.close()


def get_mensajes_conversacion(conv_id: int) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM chat_historial WHERE conversacion_id = ? ORDER BY fecha ASC",
        (conv_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_conversacion_actividad(conv_id: int) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE conversaciones SET fecha_ultima_actividad = ? WHERE id = ?",
        (datetime.now().isoformat(), conv_id),
    )
    conn.commit()
    conn.close()


# ── backup_operaciones ────────────────────────────────────────────────────────


def insert_backup_operacion(archivo_id, nombre_original, ruta_original, ruta_nueva, operacion):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO backup_operaciones
           (archivo_id, nombre_original, ruta_original, ruta_nueva, operacion, fecha_operacion, revertido)
           VALUES (?, ?, ?, ?, ?, ?, 0)""",
        (
            archivo_id,
            nombre_original,
            str(ruta_original),
            str(ruta_nueva) if ruta_nueva else None,
            operacion,
            datetime.now().isoformat(),
        ),
    )
    backup_id = cur.lastrowid
    conn.commit()
    conn.close()
    return backup_id


def get_backup_operaciones(solo_pendientes=False):
    conn = get_connection()
    cur = conn.cursor()
    query = """SELECT b.*, a.nombre AS archivo_nombre
               FROM backup_operaciones b
               LEFT JOIN archivos a ON b.archivo_id = a.id
               WHERE 1=1"""
    if solo_pendientes:
        query += " AND b.revertido = 0"
    query += " ORDER BY b.fecha_operacion DESC"
    cur.execute(query)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_backup_operacion(backup_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM backup_operaciones WHERE id = ?", (backup_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def mark_backup_revertido(backup_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE backup_operaciones SET revertido = 1, fecha_reversion = ? WHERE id = ?",
        (datetime.now().isoformat(), backup_id),
    )
    conn.commit()
    conn.close()


# ── stats & misc ──────────────────────────────────────────────────────────────


def get_stats():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS total FROM archivos WHERE existe = 1")
    total_archivos = cur.fetchone()["total"]

    cur.execute("SELECT COALESCE(SUM(tamaño_bytes), 0) AS total FROM archivos WHERE existe = 1")
    total_size = cur.fetchone()["total"]

    cur.execute("SELECT MAX(fecha_indexado) AS last_scan FROM archivos WHERE existe = 1")
    last_scan = cur.fetchone()["last_scan"]

    cur.execute("SELECT COUNT(*) AS total FROM recomendaciones WHERE descartada = 0")
    pending_recs = cur.fetchone()["total"]

    cur.execute(
        """SELECT c.nombre, c.color, c.icono, COUNT(a.id) AS count
           FROM categorias c
           LEFT JOIN archivos a ON a.categoria_id = c.id AND a.existe = 1
           GROUP BY c.id
           ORDER BY count DESC"""
    )
    by_category = [dict(r) for r in cur.fetchall()]

    conn.close()
    return {
        "total_archivos": total_archivos,
        "total_size": total_size,
        "last_scan": last_scan,
        "pending_recs": pending_recs,
        "by_category": by_category,
    }


def get_categorias():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM categorias")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── duplicados ────────────────────────────────────────────────────────────────


def get_grupos_duplicados() -> list[dict]:
    """Return duplicate groups sorted by recoverable space (descending).

    Each group dict: hash, archivos, copias, espacio_recuperable, conservar_id.
    conservar_id is the file with the shortest path; ties broken by oldest
    fecha_modificacion.
    """
    from collections import defaultdict

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT a.id, a.nombre, a.ruta_actual, a.tamaño_bytes, a.fecha_modificacion,
                  a.hash_blake2,
                  c.nombre AS categoria_nombre, c.color AS categoria_color,
                  c.icono AS categoria_icono
           FROM archivos a
           LEFT JOIN categorias c ON a.categoria_id = c.id
           WHERE a.hash_blake2 != '' AND a.hash_blake2 IS NOT NULL AND a.existe = 1
           ORDER BY a.hash_blake2"""
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    by_hash: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_hash[row["hash_blake2"]].append(row)

    grupos: list[dict] = []
    for hash_val, archivos in by_hash.items():
        if len(archivos) < 2:
            continue
        tamaño = archivos[0]["tamaño_bytes"] or 0
        copias = len(archivos)
        espacio_recuperable = tamaño * (copias - 1)

        sorted_arch = sorted(
            archivos,
            key=lambda a: (len(a["ruta_actual"] or ""), a["fecha_modificacion"] or ""),
        )
        conservar_id = sorted_arch[0]["id"]

        grupos.append(
            {
                "hash": hash_val,
                "archivos": archivos,
                "copias": copias,
                "espacio_recuperable": espacio_recuperable,
                "conservar_id": conservar_id,
            }
        )

    grupos.sort(key=lambda g: g["espacio_recuperable"], reverse=True)
    return grupos


def get_extension_breakdown(categoria_id: int) -> list[dict]:
    """Count files per extension within a given category (active files only)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT LOWER(COALESCE(extension, '')) AS extension, COUNT(*) AS count
           FROM archivos
           WHERE categoria_id = ? AND existe = 1
           GROUP BY LOWER(COALESCE(extension, ''))
           ORDER BY count DESC""",
        (categoria_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def recategorize_by_extension(ext_map: dict[str, str], cat_ids: dict[str, int]) -> int:
    """Re-categorize existing files whose category is 'Desconocido' (id=9) if their
    extension now maps to a known category.  Also fixes any file whose extension maps
    to a category that differs from the stored one (handles added/changed mappings).

    Returns the number of rows updated.
    """
    unknown_id = cat_ids.get("Desconocido", 9)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, LOWER(COALESCE(extension,'')) AS ext, categoria_id FROM archivos WHERE existe = 1"
    )
    rows = cur.fetchall()
    updated = 0
    for row in rows:
        ext = row["ext"]
        cat_name = ext_map.get(ext)
        if cat_name is None:
            continue
        new_cat_id = cat_ids.get(cat_name)
        if new_cat_id is None:
            continue
        if row["categoria_id"] == new_cat_id:
            continue
        # Only fix Desconocido→known OR if the mapping changed since last scan
        if row["categoria_id"] == unknown_id or row["categoria_id"] != new_cat_id:
            cur.execute("UPDATE archivos SET categoria_id = ? WHERE id = ?", (new_cat_id, row["id"]))
            updated += 1
    if updated:
        conn.commit()
    conn.close()
    return updated


def get_archivos_analizados() -> list[dict]:
    """Return all analyzed (resumen_ia present) existing files with category info."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT a.id, a.nombre, a.ruta_actual, a.resumen_ia,
                  a.tamaño_bytes, a.fecha_modificacion,
                  c.nombre AS categoria_nombre, c.color AS categoria_color,
                  c.icono AS categoria_icono
           FROM archivos a
           LEFT JOIN categorias c ON a.categoria_id = c.id
           WHERE a.existe = 1 AND a.resumen_ia IS NOT NULL AND a.resumen_ia != ''
           ORDER BY a.nombre"""
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_archivo_nombre_y_ruta(archivo_id: int, nuevo_nombre: str, nueva_ruta: str) -> None:
    """Update nombre and ruta_actual together after a rename."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE archivos SET nombre = ?, ruta_actual = ? WHERE id = ?",
        (nuevo_nombre, str(nueva_ruta), archivo_id),
    )
    conn.commit()
    conn.close()


# ── Analítica de disco ────────────────────────────────────────────────────────


def get_analytics_stats(categoria_id: int | None = None) -> dict:
    """Aggregated disk-usage stats for the analytics dashboard.

    All queries use GROUP BY — never returns per-file rows to the caller.
    Safe at 100k rows.  categoria_id filters totals, top files, age buckets,
    and top folders; por_categoria always returns the full breakdown.
    """
    conn = get_connection()
    cur = conn.cursor()

    cat_filter = "AND a.categoria_id = ?" if categoria_id else ""
    params: list = [categoria_id] if categoria_id else []

    # ── Totales ────────────────────────────────────────────────────────────────
    cur.execute(
        f"SELECT COUNT(*) AS archivos, COALESCE(SUM(tamaño_bytes), 0) AS bytes "
        f"FROM archivos a WHERE a.existe = 1 {cat_filter}",
        params,
    )
    totales_row = dict(cur.fetchone())

    # ── Por categoría (always full breakdown — acts as the filter selector) ────
    cur.execute(
        """SELECT c.id, c.nombre, c.color, c.icono,
                  COUNT(a.id) AS count,
                  COALESCE(SUM(a.tamaño_bytes), 0) AS bytes
           FROM categorias c
           LEFT JOIN archivos a ON a.categoria_id = c.id AND a.existe = 1
           GROUP BY c.id, c.nombre, c.color, c.icono
           ORDER BY bytes DESC"""
    )
    por_categoria = [dict(r) for r in cur.fetchall()]

    # ── Top 20 largest files ───────────────────────────────────────────────────
    cur.execute(
        f"""SELECT a.id, a.nombre, a.ruta_actual, a.tamaño_bytes, a.fecha_modificacion,
                   c.nombre AS cat_nombre, c.color AS cat_color
            FROM archivos a
            LEFT JOIN categorias c ON a.categoria_id = c.id
            WHERE a.existe = 1 {cat_filter}
            ORDER BY a.tamaño_bytes DESC LIMIT 20""",
        params,
    )
    top_archivos = [dict(r) for r in cur.fetchall()]

    # ── Age distribution (5 fixed buckets by fecha_modificacion) ──────────────
    cur.execute(
        f"""SELECT
              CASE
                WHEN julianday('now') - julianday(fecha_modificacion) < 30   THEN '<1m'
                WHEN julianday('now') - julianday(fecha_modificacion) < 180  THEN '1-6m'
                WHEN julianday('now') - julianday(fecha_modificacion) < 365  THEN '6-12m'
                WHEN julianday('now') - julianday(fecha_modificacion) < 1095 THEN '1-3a'
                ELSE '>3a'
              END AS bucket,
              COUNT(*) AS count,
              COALESCE(SUM(tamaño_bytes), 0) AS bytes
            FROM archivos a
            WHERE a.existe = 1 {cat_filter}
              AND a.fecha_modificacion IS NOT NULL
            GROUP BY bucket""",
        params,
    )
    raw_age = {r["bucket"]: dict(r) for r in cur.fetchall()}
    bucket_defs = [
        ("<1m", "< 1 mes"),
        ("1-6m", "1–6 meses"),
        ("6-12m", "6–12 meses"),
        ("1-3a", "1–3 años"),
        (">3a", "> 3 años"),
    ]
    por_antiguedad = [
        {
            "bucket": k,
            "label": lbl,
            "count": raw_age.get(k, {}).get("count", 0),
            "bytes": raw_age.get(k, {}).get("bytes", 0),
        }
        for k, lbl in bucket_defs
    ]

    # ── Top 15 folders — parent dir extracted from ruta_actual via SUBSTR ─────
    cur.execute(
        f"""SELECT
              SUBSTR(a.ruta_actual, 1,
                     LENGTH(a.ruta_actual) - LENGTH(a.nombre) - 1) AS folder,
              COUNT(*) AS count,
              COALESCE(SUM(a.tamaño_bytes), 0) AS bytes
            FROM archivos a
            WHERE a.existe = 1 {cat_filter}
              AND a.nombre IS NOT NULL AND a.nombre != ''
              AND LENGTH(a.ruta_actual) > LENGTH(a.nombre) + 1
            GROUP BY folder
            ORDER BY bytes DESC
            LIMIT 15""",
        params,
    )
    top_carpetas = [dict(r) for r in cur.fetchall()]

    # ── Recoverable bytes from duplicates (always global — not filtered) ───────
    cur.execute(
        """SELECT COALESCE(SUM((cnt - 1) * tamaño), 0) AS dup_bytes
           FROM (
             SELECT hash_blake2, COUNT(*) AS cnt, MAX(tamaño_bytes) AS tamaño
             FROM archivos
             WHERE hash_blake2 != '' AND hash_blake2 IS NOT NULL AND existe = 1
             GROUP BY hash_blake2
             HAVING cnt > 1
           )"""
    )
    dup_bytes = (cur.fetchone() or {"dup_bytes": 0})["dup_bytes"] or 0

    # ── Cold files count (modified > 1 year ago) ───────────────────────────────
    cur.execute(
        f"""SELECT COUNT(*) AS cnt FROM archivos a
            WHERE a.existe = 1 {cat_filter}
              AND a.fecha_modificacion IS NOT NULL
              AND julianday('now') - julianday(fecha_modificacion) > 365""",
        params,
    )
    cold_count = (cur.fetchone() or {"cnt": 0})["cnt"]

    conn.close()

    return {
        "totales": {"archivos": totales_row["archivos"], "bytes": totales_row["bytes"]},
        "por_categoria": por_categoria,
        "top_archivos": top_archivos,
        "por_antiguedad": por_antiguedad,
        "top_carpetas": top_carpetas,
        "duplicados_bytes": int(dup_bytes),
        "archivos_frios": cold_count,
    }


# ── Plan de organización ──────────────────────────────────────────────────────


def insert_plan(carpeta_raiz: str, nombre: str | None = None) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO planes (nombre, carpeta_raiz, fecha_creacion) VALUES (?, ?, ?)",
        (nombre, str(carpeta_raiz), datetime.now().isoformat()),
    )
    plan_id = cur.lastrowid
    conn.commit()
    conn.close()
    return plan_id


def insert_plan_item(
    plan_id: int,
    archivo_id: int,
    origen: str,
    destino: str,
    motivo: str | None = None,
    orden: int = 0,
) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO plan_items
           (plan_id, archivo_id, tipo, origen, destino, motivo, estado, orden)
           VALUES (?, ?, 'mover', ?, ?, ?, 'aprobado', ?)""",
        (plan_id, archivo_id, str(origen), str(destino), motivo, orden),
    )
    item_id = cur.lastrowid
    conn.commit()
    conn.close()
    return item_id


def update_plan_stats(plan_id: int) -> None:
    """Recompute total_items and items_aplicados from plan_items."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM plan_items WHERE plan_id = ?", (plan_id,))
    total = cur.fetchone()["n"]
    cur.execute(
        "SELECT COUNT(*) AS n FROM plan_items WHERE plan_id = ? AND estado = 'aplicado'",
        (plan_id,),
    )
    aplicados = cur.fetchone()["n"]
    cur.execute(
        "UPDATE planes SET total_items = ?, items_aplicados = ? WHERE id = ?",
        (total, aplicados, plan_id),
    )
    conn.commit()
    conn.close()


def get_plan(plan_id: int) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM planes WHERE id = ?", (plan_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_plan_items(plan_id: int) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT pi.*, a.nombre AS archivo_nombre, a.tamaño_bytes,
                  c.nombre AS cat_nombre, c.color AS cat_color, c.icono AS cat_icono
           FROM plan_items pi
           LEFT JOIN archivos a ON pi.archivo_id = a.id
           LEFT JOIN categorias c ON a.categoria_id = c.id
           WHERE pi.plan_id = ?
           ORDER BY pi.orden""",
        (plan_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_plan_item(item_id: int) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM plan_items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def update_plan_item_estado(
    item_id: int,
    estado: str,
    mensaje_error: str | None = None,
    backup_id: int | None = None,
) -> None:
    conn = get_connection()
    cur = conn.cursor()
    sets = ["estado = ?"]
    params: list = [estado]
    if mensaje_error is not None:
        sets.append("mensaje_error = ?")
        params.append(mensaje_error)
    if backup_id is not None:
        sets.append("backup_id = ?")
        params.append(backup_id)
    params.append(item_id)
    cur.execute(f"UPDATE plan_items SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()


def update_plan_item_destino(item_id: int, nuevo_destino: str) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE plan_items SET destino = ? WHERE id = ?",
        (str(nuevo_destino), item_id),
    )
    conn.commit()
    conn.close()


def update_plan_items_estado_bulk(plan_id: int, item_ids: list[int], nuevo_estado: str) -> None:
    if not item_ids:
        return
    conn = get_connection()
    cur = conn.cursor()
    placeholders = ",".join("?" * len(item_ids))
    cur.execute(
        f"UPDATE plan_items SET estado = ? WHERE id IN ({placeholders}) AND plan_id = ?",
        [nuevo_estado, *item_ids, plan_id],
    )
    conn.commit()
    conn.close()


def update_plan_estado(plan_id: int, estado: str, fecha_aplicado: str | None = None) -> None:
    conn = get_connection()
    cur = conn.cursor()
    if fecha_aplicado:
        cur.execute(
            "UPDATE planes SET estado = ?, fecha_aplicado = ? WHERE id = ?",
            (estado, fecha_aplicado, plan_id),
        )
    else:
        cur.execute("UPDATE planes SET estado = ? WHERE id = ?", (estado, plan_id))
    conn.commit()
    conn.close()


def get_planes_recientes(limit: int = 20) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM planes ORDER BY fecha_creacion DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_etiquetas_grouped() -> dict[int, list[str]]:
    """Return {archivo_id: [etiqueta, ...]} fetched in a single query."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT archivo_id, etiqueta FROM etiquetas ORDER BY archivo_id, id")
    rows = cur.fetchall()
    conn.close()
    result: dict[int, list[str]] = {}
    for row in rows:
        result.setdefault(row["archivo_id"], []).append(row["etiqueta"])
    return result


def get_latest_backup_for_archivo(archivo_id: int) -> dict | None:
    """Return the most recent backup_operaciones row for the given file."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM backup_operaciones WHERE archivo_id = ? ORDER BY fecha_operacion DESC LIMIT 1",
        (archivo_id,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def descartar_recomendaciones_por_archivo_ids(archivo_ids: list[int]) -> None:
    """Discard all R1 (duplicate) recommendations for the given file IDs."""
    if not archivo_ids:
        return
    conn = get_connection()
    cur = conn.cursor()
    placeholders = ",".join("?" * len(archivo_ids))
    cur.execute(
        f"UPDATE recomendaciones SET descartada = 1 WHERE archivo_id IN ({placeholders}) AND tipo = 'R1'",
        archivo_ids,
    )
    conn.commit()
    conn.close()


# ── ejecuciones / log_entradas ────────────────────────────────────────────────


def create_ejecucion(tipo: str, descripcion: str) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO ejecuciones (tipo, descripcion, fecha_inicio, estado) VALUES (?, ?, ?, 'en_progreso')",
        (tipo, descripcion, datetime.now().isoformat()),
    )
    eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid


def finish_ejecucion(ejecucion_id: int, estado: str, stats_json: str | None = None) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE ejecuciones SET estado = ?, fecha_fin = ?, stats_json = ? WHERE id = ?",
        (estado, datetime.now().isoformat(), stats_json, ejecucion_id),
    )
    conn.commit()
    conn.close()


def log_entrada(ejecucion_id: int, nivel: str, mensaje: str) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO log_entradas (ejecucion_id, timestamp, nivel, mensaje) VALUES (?, ?, ?, ?)",
        (ejecucion_id, datetime.now().isoformat(), nivel, mensaje),
    )
    conn.commit()
    conn.close()


def get_ejecuciones(dias: int = 30) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT e.*, COUNT(l.id) AS total_entradas
           FROM ejecuciones e
           LEFT JOIN log_entradas l ON l.ejecucion_id = e.id
           WHERE e.fecha_inicio >= datetime('now', ?)
           GROUP BY e.id
           ORDER BY e.fecha_inicio DESC""",
        (f"-{dias} days",),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_ejecucion(ejecucion_id: int) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM ejecuciones WHERE id = ?", (ejecucion_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_entradas_ejecucion(ejecucion_id: int) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM log_entradas WHERE ejecucion_id = ? ORDER BY id ASC",
        (ejecucion_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_ejecucion(ejecucion_id: int) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM log_entradas WHERE ejecucion_id = ?", (ejecucion_id,))
    cur.execute("DELETE FROM ejecuciones WHERE id = ?", (ejecucion_id,))
    conn.commit()
    conn.close()


def purge_old_ejecuciones(dias: int) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM ejecuciones WHERE fecha_inicio < datetime('now', ?)",
        (f"-{dias} days",),
    )
    old_ids = [r["id"] for r in cur.fetchall()]
    if old_ids:
        placeholders = ",".join("?" * len(old_ids))
        cur.execute(f"DELETE FROM log_entradas WHERE ejecucion_id IN ({placeholders})", old_ids)
        cur.execute(f"DELETE FROM ejecuciones WHERE id IN ({placeholders})", old_ids)
        conn.commit()
    conn.close()
    return len(old_ids)


# ── config ────────────────────────────────────────────────────────────────────


def get_config(clave: str, default: str = "") -> str:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT valor FROM config WHERE clave = ?", (clave,))
    row = cur.fetchone()
    conn.close()
    return row["valor"] if row else default


def set_config(clave: str, valor: str) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO config (clave, valor) VALUES (?, ?) "
        "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
        (clave, valor),
    )
    conn.commit()
    conn.close()
