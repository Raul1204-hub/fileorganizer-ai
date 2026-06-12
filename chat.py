import json
import re

import requests

import database

OLLAMA_BASE = "http://localhost:11434/api"
SQL_MODEL = "qwen2.5-coder:7b"
RESPONSE_MODEL = "qwen3:8b"

DB_SCHEMA = """
Tables:
  categorias(id, nombre, color, icono)
  archivos(id, nombre, extension, ruta_actual, tamaño_bytes, fecha_modificacion,
           fecha_indexado, hash_blake2, categoria_id, resumen_ia)
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
"""

_BLOCKED = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|CREATE|TRUNCATE|REPLACE)\b",
    re.IGNORECASE,
)


def safety_check(sql: str) -> bool:
    if _BLOCKED.search(sql):
        return False
    if not re.search(r"\bSELECT\b", sql, re.IGNORECASE):
        return False
    return True


def _check_ollama() -> tuple[bool, list[str]]:
    """Returns (is_running, installed_model_names)."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        return True, models
    except Exception:
        return False, []


def _call_ollama(model: str, prompt: str, timeout: int = 180) -> str:
    try:
        resp = requests.post(
            f"{OLLAMA_BASE}/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        # Strip <think>…</think> blocks
        return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    except requests.exceptions.ConnectionError:
        raise RuntimeError("ollama_not_running")
    except Exception as e:
        err = str(e)
        if "model" in err.lower() and ("not found" in err.lower() or "pull" in err.lower()):
            raise RuntimeError("model_not_found")
        return ""


def generate_sql(question: str) -> str:
    tags = database.get_all_etiquetas()
    tags_str = ", ".join(tags) if tags else "none"

    recent = database.get_chat_historial(limit=3)
    history_lines = "\n".join(
        f"Q: {h['pregunta']}\nSQL: {h['sql_generada']}" for h in reversed(recent)
    )

    prompt = (
        "You are a SQLite expert. Generate ONLY a valid SQLite SELECT query.\n"
        "No explanation. No markdown. No backticks. No semicolons.\n\n"
        f"Schema:\n{DB_SCHEMA}\n"
        f"Available tags: {tags_str}\n\n"
        f"Recent conversation:\n{history_lines}\n\n"
        f"Question: {question}\n\n"
        "SQL:"
    )

    raw = _call_ollama(SQL_MODEL, prompt)
    # Strip any accidental code fences
    raw = raw.replace("```sql", "").replace("```", "").strip().rstrip(";")
    return raw


def _execute_query(sql: str) -> list[dict]:
    conn = database.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        raise ValueError(f"SQL error: {e}") from e
    finally:
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
    answer = _call_ollama(RESPONSE_MODEL, prompt)
    if not answer:
        return f"Encontré {len(results)} resultado(s) para tu consulta."
    return answer


def chat_query(question: str) -> dict:
    # Pre-flight: check Ollama before wasting time
    running, installed_models = _check_ollama()
    if not running:
        return {
            "respuesta": "⚠️ Ollama no está respondiendo. Asegúrate de que Ollama está en ejecución.",
            "resultados": [], "sql": "", "error": "ollama_not_running",
        }

    missing = [m for m in (SQL_MODEL, RESPONSE_MODEL) if not any(m in im for im in installed_models)]
    if missing:
        cmds = "\n".join(f"  ollama pull {m}" for m in missing)
        return {
            "respuesta": (
                f"⚠️ Los modelos de IA no están instalados en Ollama.\n\n"
                f"Ejecuta estos comandos en tu terminal:\n{cmds}"
            ),
            "resultados": [], "sql": "", "error": "models_not_installed",
            "missing_models": missing,
        }

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
        database.insert_chat_historial(question, sql, str(e))
        return {"respuesta": f"Error al ejecutar la consulta: {e}", "resultados": [], "sql": sql}

    respuesta = _generate_response(question, resultados)
    database.insert_chat_historial(question, sql, respuesta)

    return {
        "respuesta": respuesta,
        "resultados": resultados[:50],
        "sql": sql,
    }
