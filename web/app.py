import atexit
import json
import sys
import threading
import time
import webbrowser
from pathlib import Path

import ollama_client

# Ensure project root is importable regardless of how this module is loaded
sys.path.insert(0, str(Path(__file__).parent.parent))

import log as _log

_log.setup_logging()
_wlog = _log.get_logger("fileorganizer.web")

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

import analyzer
import chat as chat_module
import database
import embeddings as _embed_module
import organizer
import planner
import recommendations
import renamer
import scanner
import watcher as _watcher_module
from config import ANALYSIS_MODEL, EMBED_MODEL, VISION_MAX_MB, VISION_MODEL

app = Flask(__name__, template_folder="templates")
app.secret_key = "fileorganizer-ai-secret-2024"


# ── Global scan state ─────────────────────────────────────────────────────────

_EMA_ALPHA = 0.2


class _ScanState:
    def __init__(self):
        self.running = False
        self.cancelled = False
        self.fase = "idle"  # idle|escaneando|hasheando|analizando|recomendaciones|completado|error
        self.hechos = 0
        self.total = 0
        self.archivo_actual = ""
        self.t_inicio_fase = 0.0
        self.eta_segundos = -1.0  # -1 = calculando
        self.errores: list[str] = []
        self.summary: dict = {}
        # EMA — analysis phase (seconds per character, for Ollama ETA)
        self.ema_anal_spc = 0.0
        self.ema_anal_n = 0
        self.avg_chars = 0.0  # running mean chars per doc
        # Failure counters (accumulated during analysis phase)
        self.analizados = 0
        self.fallos_extraccion = 0
        self.fallos_ollama = 0
        # Detailed progress log (capped at 200 entries)
        self.log_lines: list[dict] = []   # [{ts, level, msg}]
        # Stats snapshot for the expanded panel
        self.stats_detail: dict = {}
        self.speed_per_min: float = 0.0
        self._t_scan_start: float = 0.0   # absolute time when scan started
        # DB ejecucion tracking
        self._ejecucion_id: int | None = None


_ss = _ScanState()
_lock = threading.Lock()


def _snapshot() -> dict:
    """Thread-safe read of the full scan state."""
    with _lock:
        return {
            "running": _ss.running,
            "cancelled": _ss.cancelled,
            "fase": _ss.fase,
            "hechos": _ss.hechos,
            "total": _ss.total,
            "archivo_actual": _ss.archivo_actual,
            "eta_segundos": round(_ss.eta_segundos, 1),
            "errores": list(_ss.errores),
            "summary": dict(_ss.summary),
            "analizados": _ss.analizados,
            "fallos_extraccion": _ss.fallos_extraccion,
            "fallos_ollama": _ss.fallos_ollama,
            # Detailed progress for expanded panel
            "log_lines": list(_ss.log_lines[-50:]),
            "stats_detail": dict(_ss.stats_detail),
            "speed_per_min": round(_ss.speed_per_min, 2),
            # Legacy fields kept for backwards compat
            "status": _ss.fase,
            "progress": _ss.hechos,
            "current_file": _ss.archivo_actual,
            "error": _ss.errores[-1] if _ss.errores else None,
        }


def _log_scan(level: str, msg: str) -> None:
    """Append a timestamped log line to the scan state and persist to DB (thread-safe, capped at 200)."""
    from datetime import datetime as _dt
    entry = {"ts": _dt.now().strftime("%H:%M:%S"), "level": level, "msg": msg}
    ejecucion_id = None
    with _lock:
        _ss.log_lines.append(entry)
        if len(_ss.log_lines) > 200:
            _ss.log_lines = _ss.log_lines[-200:]
        ejecucion_id = _ss._ejecucion_id
    if ejecucion_id:
        try:
            database.log_entrada(ejecucion_id, level, msg)
        except Exception:
            pass


# ── Template helpers ──────────────────────────────────────────────────────────


def _format_size(val) -> str:
    try:
        val = int(val or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024:
            return f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} PB"


app.jinja_env.filters["format_size"] = _format_size


# ── Page routes ───────────────────────────────────────────────────────────────


@app.route("/")
def index():
    stats = database.get_stats()
    recs = database.get_recomendaciones(solo_activas=True, limit=10)
    archivos = database.get_all_archivos(limit=20)
    categorias = database.get_categorias()
    return render_template(
        "index.html",
        stats=stats,
        recs=recs,
        archivos=archivos,
        categorias=categorias,
        scan_state=_snapshot(),
    )


@app.route("/explorar")
def explorar():
    search = request.args.get("search", "").strip() or None
    raw_cat = request.args.get("categoria_id", "")
    categoria_id = int(raw_cat) if raw_cat.isdigit() else None
    sort = request.args.get("sort", "fecha")  # fecha | nombre | tamaño
    page = max(1, int(request.args.get("page", 1)))
    per_page = 50
    offset = (page - 1) * per_page

    all_files = database.get_all_archivos(search=search, categoria_id=categoria_id)

    # Sort in Python (avoids changing DB layer)
    sort_keys = {
        "nombre": lambda f: (f["nombre"] or "").lower(),
        "tamaño": lambda f: f["tamaño_bytes"] or 0,
        "fecha": lambda f: f["fecha_modificacion"] or "",
    }
    all_files.sort(key=sort_keys.get(sort, sort_keys["fecha"]), reverse=(sort != "nombre"))

    total = len(all_files)
    pages = max(1, (total + per_page - 1) // per_page)
    archivos = all_files[offset : offset + per_page]
    categorias = database.get_categorias()

    return render_template(
        "explorar.html",
        archivos=archivos,
        categorias=categorias,
        total=total,
        page=page,
        pages=pages,
        search=search or "",
        categoria_id=categoria_id,
        sort=sort,
    )


@app.route("/organizar")
def organizar():
    archivos = database.get_all_archivos()
    categorias = {c["id"]: c for c in database.get_categorias()}

    # Group files by category, skip files that are already in a categorized subfolder
    from collections import defaultdict

    grupos: dict[str, list] = defaultdict(list)
    for a in archivos:
        cat = categorias.get(a["categoria_id"])
        cat_nombre = cat["nombre"] if cat else "Desconocido"
        grupos[cat_nombre].append(a)

    # Stats
    total = len(archivos)
    total_size = sum(a.get("tamaño_bytes") or 0 for a in archivos)

    return render_template(
        "organizar.html",
        grupos=dict(grupos),
        categorias=categorias,
        total=total,
        total_size=total_size,
    )


@app.route("/archivo/<int:archivo_id>")
def archivo_detail(archivo_id):
    archivo = database.get_archivo(archivo_id)
    if not archivo:
        return "Archivo no encontrado", 404
    etiquetas = database.get_etiquetas_by_archivo(archivo_id)
    historial = database.get_historial_by_archivo(archivo_id)
    all_recs = database.get_recomendaciones(solo_activas=True)
    recs = [r for r in all_recs if r["archivo_id"] == archivo_id]
    return render_template(
        "archivo.html",
        archivo=archivo,
        etiquetas=etiquetas,
        historial=historial,
        recs=recs,
    )


@app.route("/historial")
def historial():
    page = max(1, int(request.args.get("page", 1)))
    per_page = 25
    offset = (page - 1) * per_page
    items = database.get_historial(limit=per_page, offset=offset)
    total = database.get_historial_count()
    pages = max(1, (total + per_page - 1) // per_page)
    return render_template(
        "historial.html",
        items=items,
        page=page,
        pages=pages,
        total=total,
    )


@app.route("/backup")
def backup():
    ops = database.get_backup_operaciones(solo_pendientes=False)
    pending = sum(1 for o in ops if not o["revertido"])
    reverted = sum(1 for o in ops if o["revertido"])
    return render_template(
        "backup.html",
        ops=ops,
        total=len(ops),
        pending=pending,
        reverted=reverted,
    )


@app.route("/chat")
def chat_page():
    return render_template("chat.html")


# ── Chat API ──────────────────────────────────────────────────────────────────


@app.route("/chat/query", methods=["POST"])
def chat_query():
    data = request.get_json() or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Pregunta vacía"}), 400

    conv_id = data.get("conversacion_id")

    # Auto-create conversation on first message
    if not conv_id:
        titulo = question[:60].strip()
        conv_id = database.create_conversacion(titulo)

    result = chat_module.chat_query(question, conversacion_id=conv_id)
    database.update_conversacion_actividad(conv_id)

    # Auto-title: if it's the first exchange, set title from question
    conv = database.get_conversacion(conv_id)
    if conv and conv["titulo"] == "Nueva conversación":
        database.update_conversacion_titulo(conv_id, question[:60])

    result["conversacion_id"] = conv_id
    return jsonify(result)


# ── Conversations API ─────────────────────────────────────────────────────────


@app.route("/api/conversaciones")
def api_conversaciones():
    return jsonify(database.get_conversaciones())


@app.route("/api/conversaciones", methods=["POST"])
def api_crear_conversacion():
    titulo = (request.get_json() or {}).get("titulo", "Nueva conversación")
    conv_id = database.create_conversacion(titulo)
    return jsonify({"id": conv_id, "titulo": titulo})


@app.route("/api/conversaciones/<int:conv_id>/mensajes")
def api_mensajes_conversacion(conv_id):
    mensajes = database.get_mensajes_conversacion(conv_id)
    return jsonify(mensajes)


@app.route("/api/conversaciones/<int:conv_id>", methods=["PATCH"])
def api_actualizar_conversacion(conv_id):
    data = request.get_json() or {}
    if "titulo" in data:
        database.update_conversacion_titulo(conv_id, data["titulo"])
    if data.get("toggle_anclada"):
        new_state = database.toggle_conversacion_anclada(conv_id)
        return jsonify({"anclada": new_state})
    return jsonify({"ok": True})


@app.route("/api/conversaciones/<int:conv_id>", methods=["DELETE"])
def api_eliminar_conversacion(conv_id):
    database.delete_conversacion(conv_id)
    return jsonify({"ok": True})


# ── Logs page & API ──────────────────────────────────────────────────────────


@app.route("/logs")
def logs_page():
    return render_template("logs.html")


@app.route("/api/logs/ejecuciones")
def api_logs_ejecuciones():
    dias = int(database.get_config("logs_retencion_dias", "30"))
    return jsonify(database.get_ejecuciones(dias))


@app.route("/api/logs/ejecuciones/<int:eid>")
def api_logs_ejecucion_detail(eid):
    ejec = database.get_ejecucion(eid)
    if not ejec:
        return jsonify({"error": "No encontrado"}), 404
    entradas = database.get_entradas_ejecucion(eid)
    return jsonify({**ejec, "entradas": entradas})


@app.route("/api/logs/ejecuciones/<int:eid>", methods=["DELETE"])
def api_logs_ejecucion_delete(eid):
    database.delete_ejecucion(eid)
    return jsonify({"ok": True})


@app.route("/api/logs/config")
def api_logs_config_get():
    dias = database.get_config("logs_retencion_dias", "30")
    return jsonify({"logs_retencion_dias": int(dias)})


@app.route("/api/logs/config", methods=["POST"])
def api_logs_config_set():
    data = request.get_json() or {}
    dias = max(1, min(int(data.get("logs_retencion_dias", 30)), 365))
    database.set_config("logs_retencion_dias", str(dias))
    return jsonify({"ok": True, "logs_retencion_dias": dias})


@app.route("/api/logs/purge", methods=["POST"])
def api_logs_purge():
    dias = int(database.get_config("logs_retencion_dias", "30"))
    n = database.purge_old_ejecuciones(dias)
    return jsonify({"ok": True, "eliminados": n})


# ── Scan API ──────────────────────────────────────────────────────────────────


def _run_scan(target_path: str):
    # ── Create ejecucion record before resetting state ────────────────────────
    _eid = database.create_ejecucion(
        "escaneo",
        f"Escaneo: {Path(target_path).name} — {target_path}",
    )
    # ── Reset state ───────────────────────────────────────────────────────────
    with _lock:
        _ss.running = True
        _ss.cancelled = False
        _ss.fase = "escaneando"
        _ss.hechos = 0
        _ss.total = 0
        _ss.archivo_actual = ""
        _ss.t_inicio_fase = time.monotonic()
        _ss._t_scan_start = time.monotonic()
        _ss.eta_segundos = -1.0
        _ss.errores.clear()
        _ss.summary.clear()
        _ss.ema_anal_spc = 0.0
        _ss.ema_anal_n = 0
        _ss.avg_chars = 0.0
        _ss.analizados = 0
        _ss.fallos_extraccion = 0
        _ss.fallos_ollama = 0
        _ss.log_lines.clear()
        _ss.stats_detail.clear()
        _ss.speed_per_min = 0.0
        _ss._ejecucion_id = _eid

    try:
        _log_scan("info", f"Iniciando escaneo de: {target_path}")

        # ── Phase 1: fast parallel stat-only disk scan ────────────────────────
        _t0_scan = time.monotonic()

        def _cb_fast(done, total, filename):
            with _lock:
                _ss.hechos = done
                _ss.total = total
                _ss.archivo_actual = filename

        disk_files = scanner.scan_directory_fast(
            target_path,
            progress_callback=_cb_fast,
            is_cancelled=lambda: _ss.cancelled,
        )
        _elapsed_scan = time.monotonic() - _t0_scan
        disk_paths = {f["ruta_actual"] for f in disk_files}
        _log_scan("ok", f"Disco: {len(disk_files):,} archivos encontrados en {_elapsed_scan:.1f}s")

        # ── Reconcile disk vs DB ──────────────────────────────────────────────
        db_index = database.get_all_archivos_indexed()
        unchanged: list[dict] = []
        new_files: list[dict] = []
        modified: list[dict] = []
        disappeared_ids: list[int] = []

        for f in disk_files:
            ruta = f["ruta_actual"]
            db_row = db_index.get(ruta)
            if db_row is None:
                new_files.append(f)
            elif (
                f["tamaño_bytes"] == db_row["tamaño_bytes"]
                and f["fecha_modificacion"] == db_row["fecha_modificacion"]
            ):
                if not db_row.get("existe", 1):
                    database.mark_archivo_existe(db_row["id"])
                unchanged.append(f)
            else:
                modified.append({**f, "db_id": db_row["id"]})

        for ruta, db_row in db_index.items():
            if ruta not in disk_paths:
                disappeared_ids.append(db_row["id"])

        for aid in disappeared_ids:
            database.mark_archivo_desaparecido(aid)

        _log_scan(
            "info",
            f"Reconciliación: {len(new_files):,} nuevos · {len(modified):,} modificados"
            f" · {len(unchanged):,} sin cambios · {len(disappeared_ids):,} desaparecidos",
        )
        with _lock:
            _ss.stats_detail = {
                "nuevos": len(new_files),
                "modificados": len(modified),
                "sin_cambios": len(unchanged),
                "desaparecidos": len(disappeared_ids),
                "cache_hits": 0,
                "errores": 0,
            }

        # ── Smart BLAKE2b hashing (selective: docs always; non-docs only if
        #    size-duplicate exists; 8 KB prefix compare before full hash) ──────
        candidates = [*new_files, *modified]
        n_candidates = len(candidates)
        n_hashed = 0

        with _lock:
            _ss.fase = "hasheando"
            _ss.hechos = 0
            _ss.total = n_candidates
            _ss.archivo_actual = ""
            _ss.eta_segundos = -1.0
            _ss.t_inicio_fase = time.monotonic()

        _log_scan("info", f"Hasheando {n_candidates:,} candidatos (paralelo)…")
        _t0_hash = time.monotonic()

        def _on_hash_progress(ruta: str, hashed: bool):
            nonlocal n_hashed
            with _lock:
                _ss.hechos += 1
                _ss.archivo_actual = Path(ruta).name
                # Update speed (files per minute)
                elapsed = time.monotonic() - _ss.t_inicio_fase
                if elapsed > 0:
                    _ss.speed_per_min = (_ss.hechos / elapsed) * 60
            if hashed:
                n_hashed += 1

        hash_map = scanner.smart_hash_files(
            candidates,
            disk_files,
            on_progress=_on_hash_progress,
            is_cancelled=lambda: _ss.cancelled,
        )
        _elapsed_hash = time.monotonic() - _t0_hash
        savings_skip = n_candidates - n_hashed
        _log_scan(
            "ok",
            f"Hashing completo: {n_hashed:,} hasheados, {savings_skip:,} omitidos"
            f" en {_elapsed_hash:.1f}s",
        )

        # ── Check optional models once (vision + embed) ───────────────────────
        _vision_check = ollama_client.check_ollama([VISION_MODEL])
        _vision_available = _vision_check["running"] and not _vision_check["missing"]
        if not _vision_available:
            _wlog.warning("vision model '%s' not available — image analysis skipped", VISION_MODEL)

        # ── Insert new files (batch) ──────────────────────────────────────────
        cache_hits = 0
        to_analyze: dict[str, int] = {}

        if new_files and not _ss.cancelled:
            _log_scan("info", f"Insertando {len(new_files):,} archivos nuevos en BD…")
            # Build batch rows
            batch_rows = [
                {
                    "nombre": f["nombre"],
                    "extension": f["extension"],
                    "ruta_actual": f["ruta_actual"],
                    "tamaño_bytes": f["tamaño_bytes"],
                    "fecha_modificacion": f["fecha_modificacion"],
                    "hash_blake2": hash_map.get(f["ruta_actual"], ""),
                    "categoria_id": f["categoria_id"],
                    "fecha_acceso": f.get("fecha_acceso"),
                    "fecha_creacion": f.get("fecha_creacion"),
                }
                for f in new_files
            ]
            new_ids = database.insert_archivos_batch(batch_rows)

            # Batch historial insert
            historial_entries = [(aid, None, f["ruta_actual"], "indexar") for aid, f in zip(new_ids, new_files)]
            database.insert_historial_batch(historial_entries)

            # Post-insert: cache lookup and queue for analysis
            for f, aid in zip(new_files, new_ids):
                if _ss.cancelled:
                    break
                h = hash_map.get(f["ruta_actual"], "")
                if f["extension"] in scanner.DOC_EXTS:
                    if h:
                        cached = database.get_resumen_by_hash(h)
                        if cached and cached["resumen_ia"]:
                            database.update_archivo_resumen(aid, cached["resumen_ia"])
                            database.copy_etiquetas(cached["id"], aid)
                            cache_hits += 1
                        else:
                            to_analyze[f["ruta_actual"]] = aid
                    else:
                        to_analyze[f["ruta_actual"]] = aid
                elif f["extension"] in scanner.IMG_EXTS and _vision_available:
                    if f["tamaño_bytes"] <= VISION_MAX_MB * 1024 * 1024:
                        to_analyze[f["ruta_actual"]] = aid

            _log_scan("ok", f"{len(new_files):,} archivos nuevos insertados · {cache_hits} caché hits")

        # ── Update modified files ─────────────────────────────────────────────
        if modified and not _ss.cancelled:
            _log_scan("info", f"Actualizando {len(modified):,} archivos modificados…")
        for f in modified:
            if _ss.cancelled:
                break
            h = hash_map.get(f["ruta_actual"], "")
            database.update_archivo_full(
                archivo_id=f["db_id"],
                nombre=f["nombre"],
                extension=f["extension"],
                ruta_actual=f["ruta_actual"],
                tamaño_bytes=f["tamaño_bytes"],
                fecha_modificacion=f["fecha_modificacion"],
                hash_blake2=h,
                categoria_id=f["categoria_id"],
                fecha_acceso=f.get("fecha_acceso"),
                fecha_creacion=f.get("fecha_creacion"),
            )
            database.insert_historial(f["db_id"], f["ruta_actual"], f["ruta_actual"], "actualizar")
            database.clear_etiquetas_archivo(f["db_id"])
            database.update_archivo_resumen(f["db_id"], None)
            if f["extension"] in scanner.DOC_EXTS:
                if h:
                    cached = database.get_resumen_by_hash(h)
                    if cached and cached["resumen_ia"]:
                        database.update_archivo_resumen(f["db_id"], cached["resumen_ia"])
                        database.copy_etiquetas(cached["id"], f["db_id"])
                        cache_hits += 1
                    else:
                        to_analyze[f["ruta_actual"]] = f["db_id"]
                else:
                    to_analyze[f["ruta_actual"]] = f["db_id"]
            elif f["extension"] in scanner.IMG_EXTS and _vision_available:
                if f["tamaño_bytes"] <= VISION_MAX_MB * 1024 * 1024:
                    to_analyze[f["ruta_actual"]] = f["db_id"]
        # Update stats_detail with cache hits so far
        with _lock:
            _ss.stats_detail["cache_hits"] = cache_hits

        # ── Analysis phase (Ollama, weighted EMA) ─────────────────────────────
        # Check embed model once before the loop; missing it is non-fatal
        _embed_check = ollama_client.check_ollama([EMBED_MODEL])
        _embed_available = _embed_check["running"] and not _embed_check["missing"]
        if not _embed_available:
            _wlog.warning("embed model '%s' not available — embeddings skipped this scan", EMBED_MODEL)

        _log_scan(
            "info",
            f"Análisis IA: {len(to_analyze):,} archivos en cola"
            + (f" · modelo embed no disponible" if not _embed_available else ""),
        )

        with _lock:
            _ss.fase = "analizando"
            _ss.hechos = 0
            _ss.total = len(to_analyze)
            _ss.archivo_actual = ""
            _ss.eta_segundos = -1.0
            _ss.t_inicio_fase = time.monotonic()

        def _on_failure(reason: str) -> None:
            with _lock:
                if reason == "extraction":
                    _ss.fallos_extraccion += 1
                elif reason == "ollama":
                    _ss.fallos_ollama += 1

        for ruta, aid in to_analyze.items():
            if _ss.cancelled:
                break
            with _lock:
                _ss.archivo_actual = Path(ruta).name

            t0 = time.monotonic()
            result = analyzer.analyze_file(Path(ruta), Path(ruta).suffix.lower(), on_failure=_on_failure)
            elapsed = time.monotonic() - t0
            text_len = result.pop("_text_len", 0) if result else 0
            texto_via = result.pop("_texto_via", None) if result else None

            with _lock:
                _ss.hechos += 1
                if result:
                    _ss.analizados += 1
                if text_len > 0:
                    n = _ss.ema_anal_n
                    spc = elapsed / text_len
                    _ss.ema_anal_spc = _EMA_ALPHA * spc + (1 - _EMA_ALPHA) * _ss.ema_anal_spc if n else spc
                    _ss.avg_chars = (_ss.avg_chars * n + text_len) / (n + 1)
                    _ss.ema_anal_n = n + 1
                remaining = _ss.total - _ss.hechos
                if _ss.ema_anal_n > 0 and remaining > 0:
                    _ss.eta_segundos = _ss.ema_anal_spc * _ss.avg_chars * remaining
                elif remaining == 0:
                    _ss.eta_segundos = 0.0
                # Update speed
                phase_elapsed = time.monotonic() - _ss.t_inicio_fase
                if phase_elapsed > 0:
                    _ss.speed_per_min = (_ss.hechos / phase_elapsed) * 60

            if result:
                _log_scan("ok", f"Analizado: {Path(ruta).name} ({elapsed:.1f}s · {text_len:,} chars)")
            else:
                _log_scan("warn", f"Sin resultado: {Path(ruta).name}")

            if result:
                cat_id = scanner.CATEGORIA_IDS.get(result.get("categoria", ""), None)
                database.update_archivo_resumen(aid, result.get("resumen", ""), cat_id, texto_via=texto_via)
                etiquetas_result: list[str] = []
                for tag in result.get("etiquetas", []):
                    if tag:
                        database.insert_etiqueta(aid, str(tag))
                        etiquetas_result.append(str(tag))
                # Generate and store embedding (non-fatal if embed model absent)
                if _embed_available:
                    try:
                        _embed_module.index_archivo_from_result(
                            aid, Path(ruta).name, etiquetas_result, result.get("resumen", "")
                        )
                    except Exception as _exc:
                        _wlog.warning("embed_failed | %s | %s", Path(ruta).name, _exc)

        # ── Recommendations phase ─────────────────────────────────────────────
        if not _ss.cancelled:
            _log_scan("info", "Generando recomendaciones…")
            with _lock:
                _ss.fase = "recomendaciones"
                _ss.hechos = 0
                _ss.total = 0
                _ss.archivo_actual = ""
                _ss.eta_segundos = -1.0
            database.clear_recomendaciones()
            recommendations.run_all_rules()
            _log_scan("ok", "Recomendaciones generadas")

        # ── Complete ──────────────────────────────────────────────────────────
        with _lock:
            _ss.fase = "completado"
            _ss.eta_segundos = 0.0
            savings_pct = round(100 * (1 - n_hashed / max(n_candidates, 1)))
            total_fallos = _ss.fallos_extraccion + _ss.fallos_ollama
            total_elapsed = time.monotonic() - _ss._t_scan_start
            _ss.summary = {
                "unchanged": len(unchanged),
                "new": len(new_files),
                "modified": len(modified),
                "disappeared": len(disappeared_ids),
                "cache_hits": cache_hits,
                "cancelled": _ss.cancelled,
                "hashed": n_hashed,
                "candidates": n_candidates,
                "savings_pct": savings_pct,
                "analizados": _ss.analizados,
                "fallos_extraccion": _ss.fallos_extraccion,
                "fallos_ollama": _ss.fallos_ollama,
            }
            _ss.stats_detail.update({
                "cache_hits": cache_hits,
                "errores": total_fallos,
            })
            _wlog.info(
                "Scan complete — analizados=%d, fallidos=%d (extracción=%d, Ollama=%d)"
                " — detalle en logs/fileorganizer.log",
                _ss.analizados,
                total_fallos,
                _ss.fallos_extraccion,
                _ss.fallos_ollama,
            )
        _log_scan(
            "ok",
            f"Escaneo completado en {total_elapsed:.1f}s"
            f" — {_ss.analizados} analizados · {total_fallos} fallos"
            f" · {savings_pct}% hashing omitido",
        )
        _estado = "cancelado" if _ss.summary.get("cancelled") else "completado"
        database.finish_ejecucion(_eid, _estado, json.dumps(_ss.summary, default=str))

    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        with _lock:
            _ss.errores.append(err)
            _ss.fase = "error"
        _log_scan("error", f"Error fatal: {err}")
        try:
            database.finish_ejecucion(_eid, "error", json.dumps({"error": err}))
        except Exception:
            pass

    finally:
        with _lock:
            _ss.running = False
            _ss._ejecucion_id = None


@app.route("/api/scan", methods=["POST"])
def api_scan():
    data = request.get_json() or {}
    target_path = (data.get("path") or "").strip()
    if not target_path:
        return jsonify({"error": "Ruta no proporcionada"}), 400
    if not Path(target_path).exists():
        return jsonify({"error": f"La ruta no existe: {target_path}"}), 400
    if _ss.running:
        return jsonify({"error": "Ya hay un escaneo en curso"}), 409

    thread = threading.Thread(target=_run_scan, args=(target_path,), daemon=True)
    thread.start()
    return jsonify({"message": "Escaneo iniciado", "status": "started"})


@app.route("/api/scan/status")
def api_scan_status():
    return jsonify(_snapshot())


@app.route("/api/scan/progress")
def api_scan_progress():
    """SSE stream: emits a JSON event every second while scan is running."""

    def _generate():
        while True:
            snap = _snapshot()
            yield f"data: {json.dumps(snap)}\n\n"
            if not snap["running"] and snap["fase"] in ("completado", "error", "idle"):
                break
            time.sleep(1)

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/scan/cancel", methods=["POST"])
def api_scan_cancel():
    with _lock:
        if not _ss.running:
            return jsonify({"error": "No hay escaneo en curso"}), 409
        _ss.cancelled = True
    return jsonify({"message": "Cancelación solicitada"})


@app.route("/api/browse-folder")
def api_browse_folder():
    """Open the native Windows folder picker and return the selected path."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", 1)
    folder = filedialog.askdirectory(parent=root, title="Seleccionar carpeta para escanear")
    root.destroy()
    return jsonify({"path": folder})


@app.route("/api/open-location/<int:archivo_id>")
def api_open_location(archivo_id):
    """Open Windows Explorer with the file highlighted."""
    import subprocess

    archivo = database.get_archivo(archivo_id)
    if not archivo:
        return jsonify({"error": "Archivo no encontrado"}), 404
    path = Path(archivo["ruta_actual"])
    if not path.exists():
        return jsonify({"error": f"El archivo no existe en: {path}"}), 404
    subprocess.Popen(["explorer", "/select,", str(path)])
    return jsonify({"success": True})


@app.route("/api/open-file/<int:archivo_id>")
def api_open_file(archivo_id):
    """Open the file with its default Windows application."""
    import os

    archivo = database.get_archivo(archivo_id)
    if not archivo:
        return jsonify({"error": "Archivo no encontrado"}), 404
    path = Path(archivo["ruta_actual"])
    if not path.exists():
        return jsonify({"error": f"El archivo no existe en: {path}"}), 404
    os.startfile(str(path))
    return jsonify({"success": True})


@app.route("/api/ollama-status")
def api_ollama_status():
    """Check Ollama availability and installed models."""
    status = ollama_client.check_ollama()
    return jsonify(
        {
            "running": status["running"],
            "models": status["installed"],
            "missing": status["missing"],
        }
    )


@app.route("/api/system/check")
def api_system_check():
    """Return system resources + Ollama readiness verdict."""
    import platform
    import subprocess

    import psutil
    from config import ANALYSIS_MODEL, EMBED_MODEL, RESPONSE_MODEL, SQL_MODEL, VISION_MODEL

    # ── RAM ───────────────────────────────────────────────────────────────
    vm = psutil.virtual_memory()
    ram_total_gb = round(vm.total / 1024**3, 1)
    ram_avail_gb = round(vm.available / 1024**3, 1)

    # ── CPU ───────────────────────────────────────────────────────────────
    cpu_count = psutil.cpu_count(logical=False) or psutil.cpu_count()
    cpu_freq  = psutil.cpu_freq()
    cpu_mhz   = round(cpu_freq.max if cpu_freq else 0)

    # ── Disk ──────────────────────────────────────────────────────────────
    try:
        disk = psutil.disk_usage(Path(__file__).anchor)
        disk_free_gb  = round(disk.free  / 1024**3, 1)
        disk_total_gb = round(disk.total / 1024**3, 1)
    except Exception:
        disk_free_gb = disk_total_gb = 0

    # ── GPU detection (NVIDIA → AMD/Intel via wmic) ───────────────────────
    gpu_name    = None
    gpu_vram_gb = None
    gpu_cuda    = False   # True only when CUDA-capable (NVIDIA)

    # 1) NVIDIA via nvidia-smi
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            timeout=5, stderr=subprocess.DEVNULL,
        ).decode(errors="ignore").strip().splitlines()[0]
        parts = [p.strip() for p in out.split(",")]
        gpu_name    = parts[0]
        gpu_vram_gb = round(int(parts[1]) / 1024, 1)
        gpu_cuda    = True
    except Exception:
        pass

    # 2) Any GPU via wmic (Windows — returns one row per adapter)
    if not gpu_name and platform.system() == "Windows":
        try:
            out = subprocess.check_output(
                ["wmic", "path", "win32_VideoController",
                 "get", "Name,AdapterRAM", "/value"],
                timeout=6, stderr=subprocess.DEVNULL,
            ).decode(errors="ignore")
            names, vrams = [], []
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("Name=") and line[5:]:
                    names.append(line[5:])
                elif line.startswith("AdapterRAM=") and line[11:].isdigit():
                    vrams.append(int(line[11:]))
            if names:
                gpu_name    = names[0]
                gpu_vram_gb = round(vrams[0] / 1024**3, 1) if vrams else None
        except Exception:
            pass

    # ── Ollama + model status ─────────────────────────────────────────────
    all_models   = list({ANALYSIS_MODEL, SQL_MODEL, RESPONSE_MODEL, EMBED_MODEL})
    oll_status   = ollama_client.check_ollama(all_models)
    installed_set = set(oll_status.get("installed") or [])

    # Model catalog: required vs optional
    # REQUIRED → missing = ERROR (chat won't work)
    # OPTIONAL → missing = WARNING (feature degraded, not broken)
    MODEL_CATALOG = [
        {"name": ANALYSIS_MODEL, "role": "Análisis de documentos",      "optional": False},
        {"name": SQL_MODEL,       "role": "Text-to-SQL (chat)",          "optional": False},
        {"name": RESPONSE_MODEL,  "role": "Respuestas en lenguaje natural","optional": False},
        {"name": EMBED_MODEL,     "role": "Búsqueda semántica",           "optional": True},
        {"name": VISION_MODEL,    "role": "Análisis de imágenes",         "optional": True},
    ]
    # Deduplicate preserving first occurrence
    seen_names: set[str] = set()
    MODEL_CATALOG_DEDUP = []
    for m in MODEL_CATALOG:
        if m["name"] not in seen_names:
            MODEL_CATALOG_DEDUP.append(m)
            seen_names.add(m["name"])

    MODEL_RAM = {   # approximate GB needed in CPU-only mode
        "qwen3:8b":         5.5,  "qwen3:14b":   10,  "qwen3:30b":  22,
        "qwen2.5-coder:7b": 4.8,  "qwen2.5-coder:14b": 10,
        "nomic-embed-text": 0.4,  "moondream":    2,   "llava":       5,
    }
    MODEL_DISK = {
        "qwen3:8b":         5,    "qwen3:14b":    9,   "qwen3:30b":  18,
        "qwen2.5-coder:7b": 5,    "qwen2.5-coder:14b": 9,
        "nomic-embed-text": 0.3,  "moondream":    1.7, "llava":       4,
    }

    models_info   = []
    ram_core_need = 0.0   # only required models
    for m in MODEL_CATALOG_DEDUP:
        inst = m["name"] in installed_set
        ram_n = MODEL_RAM.get(m["name"], 4)
        models_info.append({
            "name":      m["name"],
            "role":      m["role"],
            "optional":  m["optional"],
            "installed": inst,
            "ram_gb":    ram_n,
            "disk_gb":   MODEL_DISK.get(m["name"], 3),
            "pull_cmd":  f"ollama pull {m['name']}",
        })
        if not m["optional"]:
            ram_core_need += ram_n

    # ── Verdict logic ─────────────────────────────────────────────────────
    issues   = []   # → ❌  blocks core functionality
    warnings = []   # → ⚠️  degrades optional features or performance

    if not oll_status["running"]:
        issues.append("Ollama no está en ejecución — abre una terminal y ejecuta: **ollama serve**")

    missing_required = [m for m in models_info if not m["installed"] and not m["optional"]]
    if missing_required:
        for m in missing_required:
            issues.append(f"Modelo requerido no instalado: **{m['name']}** — `ollama pull {m['name']}`")

    missing_optional = [m for m in models_info if not m["installed"] and m["optional"]]
    for m in missing_optional:
        warnings.append(
            f"Modelo opcional no instalado: **{m['name']}** ({m['role']}) — "
            f"`ollama pull {m['name']}`"
        )

    if ram_total_gb < 8:
        issues.append(f"RAM insuficiente: **{ram_total_gb} GB** (mínimo recomendado: 8 GB)")
    elif ram_avail_gb < 3:
        warnings.append(f"Poca RAM disponible: **{ram_avail_gb} GB** libres — cierra otras aplicaciones")

    if gpu_cuda:
        if gpu_vram_gb is not None and gpu_vram_gb < 4:
            warnings.append(
                f"VRAM GPU baja: **{gpu_vram_gb} GB** — algunos modelos no cabrán en GPU "
                "y usarán CPU como fallback"
            )
        # else: GPU CUDA con VRAM suficiente → ningún aviso
    else:
        # GPU sin CUDA (AMD/Intel) o sin GPU
        if gpu_name:
            warnings.append(
                f"GPU detectada (**{gpu_name}**) pero sin soporte CUDA — "
                "Ollama usará CPU para inferencia (más lento, funcional)"
            )
        else:
            warnings.append(
                "No se detectó GPU — Ollama usará CPU (funciona, pero es más lento)"
            )

    if disk_free_gb < 5:
        issues.append(
            f"Poco espacio en disco: **{disk_free_gb} GB** libres "
            "(se necesitan ~5 GB para los modelos base)"
        )

    # Determine verdict
    if issues:
        verdict      = "error"
        verdict_text = "Problemas que impiden el funcionamiento normal"
    elif warnings:
        verdict      = "warning"
        verdict_text = "Ollama puede ejecutarse — hay aspectos mejorables"
    else:
        verdict      = "ok"
        verdict_text = "Todo listo — Ollama tiene recursos suficientes"

    return jsonify({
        "ram_total_gb":       ram_total_gb,
        "ram_avail_gb":       ram_avail_gb,
        "cpu_count":          cpu_count,
        "cpu_mhz":            cpu_mhz,
        "disk_free_gb":       disk_free_gb,
        "disk_total_gb":      disk_total_gb,
        "gpu_name":           gpu_name,
        "gpu_vram_gb":        gpu_vram_gb,
        "gpu_cuda":           gpu_cuda,
        "ollama_running":     oll_status["running"],
        "models":             models_info,
        "ram_core_needed_gb": round(ram_core_need, 1),
        "issues":             issues,
        "warnings":           warnings,
        "verdict":            verdict,
        "verdict_text":       verdict_text,
    })


# ── Approve / move API ────────────────────────────────────────────────────────


@app.route("/api/approve", methods=["POST"])
def api_approve():
    data = request.get_json() or {}
    approved_paths: list[str] = data.get("approved_paths", [])
    target_base: str = (data.get("target_base") or "").strip()

    if not target_base:
        return jsonify({"error": "target_base no proporcionado"}), 400

    categorias = {c["id"]: c["nombre"] for c in database.get_categorias()}
    results = []

    for ruta_actual in approved_paths:
        conn = database.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM archivos WHERE ruta_actual = ?", (ruta_actual,))
        row = cur.fetchone()
        conn.close()

        if not row:
            results.append({"ruta": ruta_actual, "success": False, "error": "Archivo no encontrado"})
            continue

        row = dict(row)
        cat_name = categorias.get(row["categoria_id"], "Desconocido")
        dst = Path(target_base) / cat_name / row["nombre"]

        # Resolve name collision
        if dst.exists() and str(dst) != ruta_actual:
            stem, suffix, n = dst.stem, dst.suffix, 1
            while dst.exists():
                dst = dst.parent / f"{stem}_{n}{suffix}"
                n += 1

        ok, _msg = organizer.execute_move(row["id"], ruta_actual, str(dst))
        results.append({"ruta": ruta_actual, "success": ok, "destino": str(dst)})

    return jsonify({"results": results})


# ── Undo API ──────────────────────────────────────────────────────────────────


@app.route("/api/undo/<int:backup_id>", methods=["POST"])
def api_undo(backup_id):
    ok, msg = organizer.undo_operation(backup_id)
    return jsonify({"success": ok, "message": msg})


@app.route("/api/undo-all", methods=["POST"])
def api_undo_all():
    eid = database.create_ejecucion("deshacer", "Deshacer todas las operaciones pendientes")
    success, fail = organizer.undo_all_pending()
    database.log_entrada(eid, "ok" if success > 0 else "info",
                         f"Revertidas {success} operaciones · {fail} fallaron")
    database.finish_ejecucion(eid, "completado", json.dumps({"ok": success, "failed": fail}))
    return jsonify(
        {
            "success": success,
            "fail": fail,
            "message": f"Revertidas {success} operaciones. {fail} fallaron.",
        }
    )


# ── Duplicados ────────────────────────────────────────────────────────────────


@app.route("/duplicados")
def duplicados():
    grupos = database.get_grupos_duplicados()
    total_recuperable = sum(g["espacio_recuperable"] for g in grupos)
    return render_template(
        "duplicados.html",
        grupos=grupos,
        total_recuperable=total_recuperable,
        total_grupos=len(grupos),
    )


@app.route("/api/duplicados")
def api_duplicados():
    grupos = database.get_grupos_duplicados()
    total_recuperable = sum(g["espacio_recuperable"] for g in grupos)
    return jsonify(
        {
            "grupos": grupos,
            "total_recuperable": total_recuperable,
            "total_grupos": len(grupos),
        }
    )


@app.route("/api/duplicados/eliminar", methods=["POST"])
def api_eliminar_duplicados():
    data = request.get_json() or {}
    raw_ids = data.get("eliminar_ids", [])
    eliminar_ids = []
    for i in raw_ids:
        try:
            eliminar_ids.append(int(i))
        except (TypeError, ValueError):
            pass
    if not eliminar_ids:
        return jsonify({"error": "Sin archivos seleccionados"}), 400

    timestamp = time.strftime("%Y-%m-%d_%H%M%S")
    backup_dir = Path(__file__).parent.parent / "data" / "backup_dup" / timestamp

    ok_count = fail_count = 0
    errores: list[str] = []
    eid = database.create_ejecucion("duplicados", f"Eliminar duplicados: {len(eliminar_ids)} archivos")
    for aid in eliminar_ids:
        success, msg = organizer.execute_delete_duplicate(aid, backup_dir)
        if success:
            ok_count += 1
            database.log_entrada(eid, "ok", f"Duplicado eliminado: ID {aid}")
        else:
            fail_count += 1
            errores.append(msg)
            database.log_entrada(eid, "error", f"Error ID {aid}: {msg}")

    if ok_count:
        database.descartar_recomendaciones_por_archivo_ids(eliminar_ids)
    database.finish_ejecucion(eid, "completado", json.dumps({"ok": ok_count, "failed": fail_count}))

    return jsonify(
        {
            "ok": ok_count,
            "failed": fail_count,
            "errores": errores[:5],
            "message": f"{ok_count} archivo(s) movidos al backup. {fail_count} error(es).",
        }
    )


# ── Renombrado inteligente ────────────────────────────────────────────────────


@app.route("/renombrar")
def renombrar():
    candidatos = renamer.get_candidatos()
    return render_template("renombrar.html", candidatos=candidatos, total=len(candidatos))


@app.route("/api/renombrado/candidatos")
def api_candidatos_renombrado():
    return jsonify(renamer.get_candidatos())


@app.route("/api/renombrado/sugerir", methods=["POST"])
def api_sugerir_nombres():
    status = ollama_client.check_ollama([ANALYSIS_MODEL])
    if not status["running"]:
        return jsonify({"error": "Ollama no está disponible"}), 503
    if status["missing"]:
        return jsonify({"error": f"Modelo {ANALYSIS_MODEL} no instalado"}), 503

    data = request.get_json() or {}
    archivo_ids = []
    for i in data.get("archivo_ids", []):
        try:
            archivo_ids.append(int(i))
        except (TypeError, ValueError):
            pass
    if not archivo_ids:
        return jsonify({"error": "Sin archivos"}), 400

    results = []
    for aid in archivo_ids:
        archivo = database.get_archivo(aid)
        if not archivo:
            results.append({"archivo_id": aid, "error": "No encontrado"})
            continue
        archivo["etiquetas"] = database.get_etiquetas_by_archivo(aid)
        nombre_sugerido = renamer.sugerir_nombre(archivo)
        if nombre_sugerido:
            results.append({"archivo_id": aid, "nombre_sugerido": nombre_sugerido})
        else:
            results.append({"archivo_id": aid, "error": "Sin sugerencia"})
    return jsonify(results)


@app.route("/api/renombrado/aplicar", methods=["POST"])
def api_aplicar_renombrado():
    data = request.get_json() or {}
    items = data.get("items", [])

    ok_count = fail_count = 0
    errores: list[str] = []
    eid = database.create_ejecucion("renombrado", f"Renombrado masivo: {len(items)} archivos")

    for item in items:
        try:
            aid = int(item["archivo_id"])
        except (TypeError, ValueError, KeyError):
            continue
        raw_nombre = str(item.get("nuevo_nombre", "")).strip()
        if not raw_nombre:
            continue

        archivo = database.get_archivo(aid)
        if not archivo:
            fail_count += 1
            errores.append(f"ID {aid}: no encontrado")
            continue

        # Re-sanitize user input (may have been manually edited)
        ext = Path(raw_nombre).suffix or Path(archivo["nombre"]).suffix.lower()
        nuevo_nombre = renamer.sanitizar_nombre(Path(raw_nombre).stem, ext)

        # Collision resolution
        src = Path(archivo["ruta_actual"])
        dst = src.parent / nuevo_nombre
        if dst.exists() and dst.resolve() != src.resolve():
            stem, suf, n = Path(nuevo_nombre).stem, Path(nuevo_nombre).suffix, 2
            while dst.exists():
                dst = src.parent / f"{stem}-{n}{suf}"
                n += 1
            nuevo_nombre = dst.name

        success, msg = organizer.execute_rename(aid, nuevo_nombre)
        if success:
            ok_count += 1
            database.log_entrada(eid, "ok", f"Renombrado: {archivo['nombre']} → {nuevo_nombre}")
        else:
            fail_count += 1
            errores.append(msg)
            database.log_entrada(eid, "error", f"Error renombrando {archivo['nombre']}: {msg}")

    database.finish_ejecucion(
        eid,
        "completado" if ok_count > 0 or fail_count == 0 else "error",
        json.dumps({"ok": ok_count, "failed": fail_count}),
    )
    return jsonify(
        {
            "ok": ok_count,
            "failed": fail_count,
            "errores": errores[:5],
            "message": f"{ok_count} archivo(s) renombrado(s). {fail_count} error(es).",
        }
    )


# ── Plan de organización ─────────────────────────────────────────────────────

_plan_apply_states: dict[int, dict] = {}
_plan_lock = threading.Lock()


def _run_plan_apply(plan_id: int, ejecucion_id: int | None = None) -> None:
    """Background thread: apply approved plan items one by one."""

    def _log_plan(level: str, msg: str) -> None:
        if ejecucion_id:
            try:
                database.log_entrada(ejecucion_id, level, msg)
            except Exception:
                pass

    with _plan_lock:
        _plan_apply_states[plan_id] = {
            "running": True,
            "total": 0,
            "hechos": 0,
            "ok": 0,
            "errors": 0,
            "current": "",
            "results": [],
        }
    try:
        items = [i for i in database.get_plan_items(plan_id) if i["estado"] == "aprobado"]
        with _plan_lock:
            _plan_apply_states[plan_id]["total"] = len(items)
        database.update_plan_estado(plan_id, "en_progreso")
        _log_plan("info", f"Iniciando plan #{plan_id}: {len(items)} items aprobados")

        for item in items:
            if not _plan_apply_states.get(plan_id, {}).get("running"):
                break
            nombre = Path(item["origen"]).name
            with _plan_lock:
                _plan_apply_states[plan_id]["current"] = nombre

            src = Path(item["origen"])
            dst = Path(item["destino"])

            if not src.exists():
                err = f"Archivo no encontrado: {nombre}"
                database.update_plan_item_estado(item["id"], "error", err)
                _log_plan("error", f"{nombre}: {err}")
                with _plan_lock:
                    st = _plan_apply_states[plan_id]
                    st["errors"] += 1
                    st["hechos"] += 1
                    st["results"].append({"id": item["id"], "ok": False, "msg": err})
                continue

            # Collision resolution before moving
            if dst.exists() and dst.resolve() != src.resolve():
                stem, suffix, n = dst.stem, dst.suffix, 2
                while dst.exists():
                    dst = dst.parent / f"{stem}-{n}{suffix}"
                    n += 1
                database.update_plan_item_destino(item["id"], str(dst))

            ok, msg = organizer.execute_move(item["archivo_id"], str(src), str(dst))
            if ok:
                backup = database.get_latest_backup_for_archivo(item["archivo_id"])
                database.update_plan_item_estado(
                    item["id"],
                    "aplicado",
                    backup_id=backup["id"] if backup else None,
                )
                _log_plan("ok", f"Movido: {nombre} → {dst.parent.name}/")
                with _plan_lock:
                    st = _plan_apply_states[plan_id]
                    st["ok"] += 1
                    st["hechos"] += 1
                    st["results"].append({"id": item["id"], "ok": True, "msg": "Aplicado"})
            else:
                database.update_plan_item_estado(item["id"], "error", msg)
                _log_plan("error", f"Error moviendo {nombre}: {msg}")
                with _plan_lock:
                    st = _plan_apply_states[plan_id]
                    st["errors"] += 1
                    st["hechos"] += 1
                    st["results"].append({"id": item["id"], "ok": False, "msg": msg})

        database.update_plan_stats(plan_id)
        database.update_plan_estado(plan_id, "completado", time.strftime("%Y-%m-%dT%H:%M:%S"))
        st_final = _plan_apply_states.get(plan_id, {})
        _log_plan("ok", f"Plan completado: {st_final.get('ok', 0)} aplicados · {st_final.get('errors', 0)} errores")
        if ejecucion_id:
            try:
                database.finish_ejecucion(ejecucion_id, "completado",
                    json.dumps({"ok": st_final.get("ok", 0), "errors": st_final.get("errors", 0)}))
            except Exception:
                pass

    except Exception as exc:
        _wlog.error("plan_apply error plan_id=%d: %s", plan_id, exc)
        _log_plan("error", f"Error fatal: {exc}")
        if ejecucion_id:
            try:
                database.finish_ejecucion(ejecucion_id, "error", json.dumps({"error": str(exc)}))
            except Exception:
                pass
        with _plan_lock:
            if plan_id in _plan_apply_states:
                _plan_apply_states[plan_id]["error"] = str(exc)
    finally:
        with _plan_lock:
            if plan_id in _plan_apply_states:
                _plan_apply_states[plan_id]["running"] = False


@app.route("/plan")
def plan_list():
    planes = database.get_planes_recientes(limit=20)
    return render_template("plan.html", planes=planes)


@app.route("/plan/<int:plan_id>")
def plan_detail(plan_id):
    plan = database.get_plan(plan_id)
    if not plan:
        return "Plan no encontrado", 404

    from collections import defaultdict

    items = database.get_plan_items(plan_id)
    grupos: dict[str, list] = defaultdict(list)
    for item in items:
        item["destino_dir"] = str(Path(item["destino"]).parent)
        item["destino_nombre"] = Path(item["destino"]).name
        grupos[item["destino_dir"]].append(item)

    grupos_sorted = dict(sorted(grupos.items()))
    destinos_unicos = sorted(grupos_sorted.keys())

    total_aprobados = sum(1 for i in items if i["estado"] == "aprobado")
    total_rechazados = sum(1 for i in items if i["estado"] == "rechazado")
    total_aplicados = sum(1 for i in items if i["estado"] == "aplicado")
    total_errores = sum(1 for i in items if i["estado"] == "error")
    total_bytes = sum((i.get("tamaño_bytes") or 0) for i in items if i["estado"] == "aprobado")

    return render_template(
        "plan_detail.html",
        plan=plan,
        grupos=grupos_sorted,
        destinos_unicos=destinos_unicos,
        items=items,
        total_aprobados=total_aprobados,
        total_rechazados=total_rechazados,
        total_aplicados=total_aplicados,
        total_errores=total_errores,
        total_bytes=total_bytes,
    )


@app.route("/api/plan/generar", methods=["POST"])
def api_plan_generar():
    data = request.get_json() or {}
    carpeta_raiz = (data.get("carpeta_raiz") or "").strip()
    if not carpeta_raiz:
        return jsonify({"error": "Ruta raíz no proporcionada"}), 400
    if not Path(carpeta_raiz).is_dir():
        return jsonify({"error": f"La carpeta no existe: {carpeta_raiz}"}), 400
    archivo_ids_raw = data.get("archivo_ids") or []
    archivo_ids = [int(i) for i in archivo_ids_raw if str(i).lstrip("-").isdigit()] or None
    plan_id = planner.generar_plan(carpeta_raiz, archivo_ids)
    plan = database.get_plan(plan_id)
    return jsonify({"plan_id": plan_id, "total_items": plan["total_items"]})


@app.route("/api/plan/<int:plan_id>/items/<int:item_id>", methods=["PATCH"])
def api_plan_update_item(plan_id, item_id):
    item = database.get_plan_item(item_id)
    if not item or item["plan_id"] != plan_id:
        return jsonify({"error": "Item no encontrado"}), 404
    if item["estado"] in ("aplicado", "error"):
        return jsonify({"error": "Item ya ejecutado"}), 409

    data = request.get_json() or {}

    if "estado" in data:
        nuevo = data["estado"]
        if nuevo not in ("aprobado", "rechazado"):
            return jsonify({"error": "Estado inválido"}), 400
        database.update_plan_item_estado(item_id, nuevo)

    if "destino_dir" in data:
        nuevo_dir = data["destino_dir"].strip()
        if nuevo_dir:
            nombre = Path(item["origen"]).name
            nuevo_destino = str(Path(nuevo_dir) / nombre)
            database.update_plan_item_destino(item_id, nuevo_destino)

    return jsonify({"success": True})


@app.route("/api/plan/<int:plan_id>/items/bulk", methods=["POST"])
def api_plan_items_bulk(plan_id):
    data = request.get_json() or {}
    ids = [int(i) for i in data.get("item_ids", []) if str(i).lstrip("-").isdigit()]
    nuevo = data.get("estado", "")
    if nuevo not in ("aprobado", "rechazado"):
        return jsonify({"error": "Estado inválido"}), 400
    if not ids:
        return jsonify({"error": "Sin items"}), 400
    database.update_plan_items_estado_bulk(plan_id, ids, nuevo)
    return jsonify({"success": True, "updated": len(ids)})


@app.route("/api/plan/<int:plan_id>/aplicar", methods=["POST"])
def api_plan_aplicar(plan_id):
    plan = database.get_plan(plan_id)
    if not plan:
        return jsonify({"error": "Plan no encontrado"}), 404
    with _plan_lock:
        if _plan_apply_states.get(plan_id, {}).get("running"):
            return jsonify({"error": "Aplicación ya en curso"}), 409
    aprobados = sum(1 for i in database.get_plan_items(plan_id) if i["estado"] == "aprobado")
    carpeta = Path(plan.get("carpeta_raiz", "")).name or plan.get("carpeta_raiz", "")
    eid = database.create_ejecucion(
        "movimiento",
        f"Plan #{plan_id}: {aprobados} archivos → {carpeta}",
    )
    thread = threading.Thread(target=_run_plan_apply, args=(plan_id, eid), daemon=True)
    thread.start()
    return jsonify({"message": "Aplicación iniciada"})


@app.route("/api/plan/<int:plan_id>/progress")
def api_plan_progress(plan_id):
    def _gen():
        while True:
            state = _plan_apply_states.get(plan_id, {"running": False, "hechos": 0, "total": 0})
            yield f"data: {json.dumps(state)}\n\n"
            if not state.get("running"):
                break
            time.sleep(0.6)

    return Response(
        stream_with_context(_gen()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/plan/<int:plan_id>/deshacer", methods=["POST"])
def api_plan_deshacer(plan_id):
    items = [i for i in database.get_plan_items(plan_id) if i["estado"] == "aplicado"]
    items.reverse()  # undo in reverse order

    ok_count = fail_count = 0
    for item in items:
        if item["backup_id"]:
            ok, _msg = organizer.undo_operation(item["backup_id"])
            if ok:
                database.update_plan_item_estado(item["id"], "aprobado")
                ok_count += 1
            else:
                fail_count += 1
        else:
            fail_count += 1

    database.update_plan_stats(plan_id)
    if ok_count:
        database.update_plan_estado(plan_id, "borrador")

    return jsonify(
        {
            "ok": ok_count,
            "failed": fail_count,
            "message": f"Revertidos {ok_count} movimiento(s). {fail_count} error(es).",
        }
    )


# ── Analítica de disco ────────────────────────────────────────────────────────


@app.route("/dashboard")
def dashboard():
    categorias = database.get_categorias()
    return render_template("dashboard.html", categorias=categorias)


@app.route("/api/analytics")
def api_analytics():
    raw = request.args.get("categoria_id", "")
    categoria_id = int(raw) if raw.isdigit() else None
    return jsonify(database.get_analytics_stats(categoria_id))


# ── Stats & recommendations API ───────────────────────────────────────────────


@app.route("/api/stats")
def api_stats():
    return jsonify(database.get_stats())


@app.route("/api/recommendations")
def api_recommendations():
    return jsonify(database.get_recomendaciones(solo_activas=True))


@app.route("/api/recommendations/<int:rec_id>/dismiss", methods=["POST"])
def api_dismiss_rec(rec_id):
    database.descartar_recomendacion(rec_id)
    return jsonify({"success": True})


@app.route("/api/archivos")
def api_archivos():
    search = request.args.get("search", "").strip() or None
    raw_cat = request.args.get("categoria_id", "")
    categoria_id = int(raw_cat) if raw_cat.isdigit() else None
    archivos = database.get_all_archivos(search=search, categoria_id=categoria_id)
    return jsonify(archivos)


# ── Semantic search ───────────────────────────────────────────────────────────


@app.route("/api/search/semantic")
def api_search_semantic():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Parámetro q requerido"}), 400
    try:
        results = _embed_module.semantic_search(q)
        return jsonify({"query": q, "results": results, "total": len(results)})
    except Exception as exc:
        _wlog.warning("semantic_search | %s | %s", q[:60], exc)
        return jsonify({"error": str(exc)}), 500


# ── Vigilancia (watch) ────────────────────────────────────────────────────────


@app.route("/vigilancia")
def vigilancia():
    return render_template("vigilancia.html", watch_status=_watcher_module.manager.get_status())


@app.route("/api/watch/start", methods=["POST"])
def api_watch_start():
    data = request.get_json() or {}
    folder = (data.get("path") or "").strip()
    if not folder:
        return jsonify({"error": "Ruta no proporcionada"}), 400
    if not Path(folder).is_dir():
        return jsonify({"error": f"La ruta no existe o no es una carpeta: {folder}"}), 400
    try:
        _watcher_module.manager.start(folder)
        return jsonify({"status": "started", "folder": folder})
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/watch/stop", methods=["POST"])
def api_watch_stop():
    _watcher_module.manager.stop()
    return jsonify({"status": "stopped"})


@app.route("/api/watch/status")
def api_watch_status():
    return jsonify(_watcher_module.manager.get_status())


# ── Server entry point ────────────────────────────────────────────────────────


def start_server(open_browser: bool = True):
    database.create_tables()
    try:
        dias = int(database.get_config("logs_retencion_dias", "30"))
        database.purge_old_ejecuciones(dias)
    except Exception:
        pass
    atexit.register(_watcher_module.manager.stop)
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    start_server()
