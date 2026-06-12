import sqlite3
from datetime import datetime

from config import DB_PATH

CATEGORIAS_SEED = [
    (1, "Documentos", "#4F46E5", "📄"),
    (2, "Imágenes", "#10B981", "🖼️"),
    (3, "Audio", "#F59E0B", "🎵"),
    (4, "Vídeo", "#EF4444", "🎬"),
    (5, "Código", "#8B5CF6", "💻"),
    (6, "Datos", "#06B6D4", "🗄️"),
    (7, "Comprimidos", "#6B7280", "📦"),
    (8, "Programas", "#F97316", "⚙️"),
    (9, "Desconocido", "#9CA3AF", "❓"),
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

        CREATE TABLE IF NOT EXISTS chat_historial (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            pregunta     TEXT,
            sql_generada TEXT,
            respuesta    TEXT,
            fecha        TEXT
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
):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO archivos
           (nombre, extension, ruta_actual, tamaño_bytes, fecha_modificacion,
            fecha_indexado, hash_blake2, categoria_id, resumen_ia)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        ),
    )
    archivo_id = cur.lastrowid
    conn.commit()
    conn.close()
    return archivo_id


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


def update_archivo_resumen(archivo_id, resumen_ia, categoria_id=None):
    conn = get_connection()
    cur = conn.cursor()
    if categoria_id:
        cur.execute(
            "UPDATE archivos SET resumen_ia = ?, categoria_id = ? WHERE id = ?",
            (resumen_ia, categoria_id, archivo_id),
        )
    else:
        cur.execute("UPDATE archivos SET resumen_ia = ? WHERE id = ?", (resumen_ia, archivo_id))
    conn.commit()
    conn.close()


def delete_all_archivos():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM etiquetas")
    cur.execute("DELETE FROM archivos")
    conn.commit()
    conn.close()


def get_all_archivos_indexed() -> dict:
    """Return {ruta_actual: row_dict} for ALL rows including disappeared ones."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, ruta_actual, tamaño_bytes, fecha_modificacion, hash_blake2, resumen_ia, existe "
        "FROM archivos"
    )
    rows = cur.fetchall()
    conn.close()
    return {r["ruta_actual"]: dict(r) for r in rows}


def update_archivo_full(
    archivo_id, nombre, extension, ruta_actual, tamaño_bytes, fecha_modificacion, hash_blake2, categoria_id
):
    """Update metadata for a modified file; preserves resumen_ia and etiquetas rows."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE archivos
           SET nombre=?, extension=?, ruta_actual=?, tamaño_bytes=?,
               fecha_modificacion=?, hash_blake2=?, categoria_id=?, existe=1
           WHERE id=?""",
        (
            nombre,
            extension,
            str(ruta_actual),
            tamaño_bytes,
            fecha_modificacion,
            hash_blake2,
            categoria_id,
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


def insert_chat_historial(pregunta, sql_generada, respuesta):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_historial (pregunta, sql_generada, respuesta, fecha) VALUES (?, ?, ?, ?)",
        (pregunta, sql_generada, respuesta, datetime.now().isoformat()),
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
