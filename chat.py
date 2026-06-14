import json
import re
import sqlite3
import threading

import database
import embeddings as _emb
from config import EMBED_MODEL, RESPONSE_MODEL, SQL_MODEL
from ollama_client import call_ollama, check_ollama, pull_commands

DB_SCHEMA = """
Tables:
  categorias(id, nombre, color, icono)
  archivos(id, nombre, extension, ruta_actual, tamaño_bytes,
           fecha_modificacion TEXT,   -- last write (ISO 8601)
           fecha_acceso TEXT,         -- last open/read (ISO 8601; may equal mtime if NTFS tracking disabled)
           fecha_creacion TEXT,       -- file creation time on Windows (ISO 8601)
           fecha_indexado TEXT,       -- when FileOrganizer indexed it (ISO 8601)
           hash_blake2, categoria_id, resumen_ia,
           texto_via TEXT,            -- 'pdf'|'ocr'|'vision'|NULL
           existe INTEGER DEFAULT 1)
  etiquetas(id, archivo_id, etiqueta)
  historial(id, archivo_id, ruta_origen, ruta_destino, operacion, fecha, revertido)
  recomendaciones(id, archivo_id, tipo, mensaje, fecha, vista, descartada)
  chat_historial(id, pregunta, sql_generada, respuesta, fecha)
  backup_operaciones(id, archivo_id, nombre_original, ruta_original, ruta_nueva,
                     operacion, fecha_operacion, revertido, fecha_reversion)

Key joins:
  archivos.categoria_id -> categorias.id
  etiquetas.archivo_id  -> archivos.id
  historial.archivo_id  -> archivos.id

Date query examples:
  "archivos no abiertos en un año" -> WHERE fecha_acceso < datetime('now','-1 year')
  "archivos creados este mes"      -> WHERE fecha_creacion >= datetime('now','start of month')
  "modificado recientemente"       -> WHERE fecha_modificacion >= datetime('now','-7 days')
"""

# Pre-filter: cheap regex check for an early, human-readable rejection.
# Security does NOT depend on this — get_readonly_connection() is the real boundary.
_BLOCKED = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|CREATE|TRUNCATE|REPLACE"
    r"|PRAGMA|ATTACH|VACUUM)\b",
    re.IGNORECASE,
)

_QUERY_LIMIT = 200  # max rows returned by the chat query engine
_QUERY_TIMEOUT_S = 30  # seconds before conn.interrupt() fires


# ── Intent routing ────────────────────────────────────────────────────────────

# Fast heuristic patterns — avoid an Ollama round-trip for obvious cases
_SEMANTIC_RE = re.compile(
    r"\b(sobre|acerca\s+de|relacionad[ao]s?\s+con|que\s+trat[ae]n?|que\s+habl[ae]n?|"
    r"de\s+tema|contenid[oa]|busca(?:r)?\s+archivos|archivo[s]?\s+(?:sobre|acerca)|"
    r"documentos?\s+sobre|similar(?:es)?\s+a|que\s+mencione?n?|hablan?\s+de)\b",
    re.IGNORECASE,
)
_SQL_RE = re.compile(
    r"\b(cu[aá]ntos?|total\s+de|m[aá]s\s+grande|m[aá]s\s+(?:reciente|pesado)|"
    r"extensi[oó]n|categor[ií]a|cu[aá]ndo|promedio|suma|lista\s+de|muestra|"
    r"muéstrame|dame\s+(?:los|un\s+listado)|ordenad[oa]s?\s+por)\b",
    re.IGNORECASE,
)


def _classify_intent(question: str) -> str:
    """Return 'semantica' or 'sql' for the question.

    Uses fast regex heuristics first; falls back to a short RESPONSE_MODEL call
    only when the heuristics are inconclusive.  Defaults to 'sql' on any error.
    """
    if _SEMANTIC_RE.search(question):
        return "semantica"
    if _SQL_RE.search(question):
        return "sql"
    # Uncertain — ask the model for a quick single-word classification
    prompt = (
        "Clasifica la pregunta en UNA categoría:\n"
        '"semantica" → busca archivos por contenido, tema o descripción\n'
        '"sql"       → pide estadísticas, fechas, tamaños, conteos o listados técnicos\n\n'
        f'Pregunta: "{question}"\n'
        "Categoría (escribe solo la palabra):"
    )
    try:
        raw = call_ollama(RESPONSE_MODEL, prompt, timeout=15)
        if "semant" in raw.lower():
            return "semantica"
    except Exception:
        pass
    return "sql"


def safety_check(sql: str) -> bool:
    """Return False if SQL looks dangerous or is not a SELECT.

    This is a pre-filter for a friendlier error message, not a security boundary.
    The structural read-only enforcement is in get_readonly_connection().
    """
    if _BLOCKED.search(sql):
        return False
    if not re.search(r"\bSELECT\b", sql, re.IGNORECASE):
        return False
    return True


def _wrap_limit(sql: str) -> str:
    """Wrap query in an outer LIMIT if none is present at the top level."""
    if not re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        return f"SELECT * FROM ({sql}) LIMIT {_QUERY_LIMIT}"
    return sql


def generate_sql(question: str) -> str:
    tags = database.get_all_etiquetas()
    tags_str = ", ".join(tags) if tags else "none"

    recent = database.get_chat_historial(limit=3)
    history_lines = "\n".join(f"Q: {h['pregunta']}\nSQL: {h['sql_generada']}" for h in reversed(recent))

    prompt = (
        "You are a SQLite expert. Generate ONLY a valid SQLite SELECT query.\n"
        "No explanation. No markdown. No backticks. No semicolons.\n"
        "IMPORTANT: When selecting from archivos, always include the `id` column "
        "(e.g. SELECT a.id, a.nombre, ...) so results can be linked in the UI.\n\n"
        f"Schema:\n{DB_SCHEMA}\n"
        f"Available tags: {tags_str}\n\n"
        f"Recent conversation:\n{history_lines}\n\n"
        f"Question: {question}\n\n"
        "SQL:"
    )

    raw = call_ollama(SQL_MODEL, prompt)
    raw = raw.replace("```sql", "").replace("```", "").strip().rstrip(";")
    return raw


def _execute_query(sql: str) -> list[dict]:
    """Execute sql against the read-only database connection.

    Enforcement layers
    ------------------
    1. get_readonly_connection() opens the file with mode=ro (OS-level) and
       installs an authorizer that denies all non-read opcodes at compile time.
    2. _wrap_limit() adds LIMIT if absent so a runaway query cannot return
       unlimited rows.
    3. A threading.Timer fires conn.interrupt() after _QUERY_TIMEOUT_S seconds
       to kill long-running queries.
    """
    sql = _wrap_limit(sql)
    conn = database.get_readonly_connection()
    timer = None
    try:
        timer = threading.Timer(_QUERY_TIMEOUT_S, conn.interrupt)
        timer.start()
        cur = conn.cursor()
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]
    except sqlite3.OperationalError as e:
        if "interrupt" in str(e).lower():
            raise ValueError(f"La consulta fue interrumpida (límite de {_QUERY_TIMEOUT_S}s superado)") from e
        raise ValueError(f"SQL error: {e}") from e
    except Exception as e:
        raise ValueError(f"SQL error: {e}") from e
    finally:
        if timer is not None:
            timer.cancel()
        conn.close()


def _generate_response(question: str, results: list[dict]) -> str:
    if not results:
        return "No encontré archivos que coincidan con tu búsqueda en la base de datos."

    results_str = json.dumps(results[:20], ensure_ascii=False, default=str)
    prompt = (
        f"Database results (JSON): {results_str}\n\n"
        "Answer the following question in friendly Spanish. "
        "Be concise — summarize key findings, do not list every row.\n\n"
        f"Question: {question}\n\nAnswer:"
    )
    answer = call_ollama(RESPONSE_MODEL, prompt)
    if not answer:
        return f"Encontré {len(results)} resultado(s) para tu consulta."
    return answer


def chat_query(question: str, conversacion_id: int | None = None) -> dict:
    # ── Pre-flight: Ollama running + core models present ─────────────────────
    status = check_ollama([SQL_MODEL, RESPONSE_MODEL])
    if not status["running"]:
        return {
            "respuesta": "⚠️ Ollama no está respondiendo. Asegúrate de que Ollama está en ejecución.",
            "resultados": [],
            "sql": "",
            "error": "ollama_not_running",
        }
    if status["missing"]:
        cmds = pull_commands(status["missing"])
        return {
            "respuesta": (
                "⚠️ Los modelos de IA no están instalados en Ollama.\n\n"
                f"Ejecuta estos comandos en tu terminal:\n{cmds}"
            ),
            "resultados": [],
            "sql": "",
            "error": "models_not_installed",
            "missing_models": status["missing"],
        }

    # ── Intent routing ────────────────────────────────────────────────────────
    intent = _classify_intent(question)

    if intent == "semantica":
        embed_status = check_ollama([EMBED_MODEL])
        if embed_status["running"] and not embed_status["missing"]:
            results = _emb.semantic_search(question)
            if results:
                top_names = ", ".join(r["nombre"] for r in results[:3])
                respuesta = (
                    f"Encontré **{len(results)}** archivo(s) relacionados con «{question}».\n"
                    f"Los más relevantes: {top_names}."
                )
            else:
                respuesta = (
                    f"No encontré archivos indexados con contenido relacionado a «{question}». "
                    "Asegúrate de haber escaneado y analizado los documentos primero."
                )
            database.insert_chat_historial(question, "[búsqueda semántica]", respuesta, conversacion_id, results)
            return {
                "respuesta": respuesta,
                "resultados": results,
                "sql": "[búsqueda semántica]",
                "modo": "semantica",
            }
        # Embed model unavailable → fall through to SQL

    # ── Text-to-SQL path ──────────────────────────────────────────────────────
    try:
        sql = generate_sql(question)
    except RuntimeError as e:
        return {"respuesta": f"⚠️ Error conectando con Ollama: {e}", "resultados": [], "sql": ""}

    if not sql:
        return {
            "respuesta": "No pude generar una consulta para esa pregunta. ¿Puedes reformularla?",
            "resultados": [],
            "sql": "",
        }

    if not safety_check(sql):
        return {
            "respuesta": "Solo puedo responder preguntas de consulta. No puedo modificar la base de datos.",
            "resultados": [],
            "sql": sql,
        }

    try:
        resultados = _execute_query(sql)
    except ValueError as e:
        database.insert_chat_historial(question, sql, str(e), conversacion_id, [])
        return {"respuesta": f"Error al ejecutar la consulta: {e}", "resultados": [], "sql": sql}

    respuesta = _generate_response(question, resultados)
    database.insert_chat_historial(question, sql, respuesta, conversacion_id, resultados)

    return {
        "respuesta": respuesta,
        "resultados": resultados[:50],
        "sql": sql,
        "modo": "sql",
    }
