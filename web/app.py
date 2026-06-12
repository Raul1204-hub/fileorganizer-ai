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
import recommendations
import scanner
import watcher as _watcher_module
from config import EMBED_MODEL

app = Flask(__name__, template_folder="templates")
app.secret_key = "fileorganizer-ai-secret-2024"

# ── Global scan state ─────────────────────────────────────────────────────────

_EMA_ALPHA = 0.2


class _ScanState:
    def __init__(self):
        self.running = False
        self.cancelled = False
        self.fase = "idle"  # idle|escaneando|analizando|recomendaciones|completado|error
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
            # Legacy fields kept for backwards compat
            "status": _ss.fase,
            "progress": _ss.hechos,
            "current_file": _ss.archivo_actual,
            "error": _ss.errores[-1] if _ss.errores else None,
        }


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
    historial = database.get_chat_historial(limit=10)
    historial.reverse()
    return render_template("chat.html", historial=historial)


# ── Chat API ──────────────────────────────────────────────────────────────────


@app.route("/chat/query", methods=["POST"])
def chat_query():
    data = request.get_json() or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Pregunta vacía"}), 400
    result = chat_module.chat_query(question)
    return jsonify(result)


# ── Scan API ──────────────────────────────────────────────────────────────────


def _run_scan(target_path: str):
    # ── Reset state ───────────────────────────────────────────────────────────
    with _lock:
        _ss.running = True
        _ss.cancelled = False
        _ss.fase = "escaneando"
        _ss.hechos = 0
        _ss.total = 0
        _ss.archivo_actual = ""
        _ss.t_inicio_fase = time.monotonic()
        _ss.eta_segundos = -1.0
        _ss.errores.clear()
        _ss.summary.clear()
        _ss.ema_anal_spc = 0.0
        _ss.ema_anal_n = 0
        _ss.avg_chars = 0.0
        _ss.analizados = 0
        _ss.fallos_extraccion = 0
        _ss.fallos_ollama = 0

    try:
        # ── Phase 1: fast stat-only disk scan ─────────────────────────────────
        def _cb_fast(done, total, filename):
            with _lock:
                _ss.hechos = done
                _ss.total = total
                _ss.archivo_actual = filename

        disk_files = scanner.scan_directory_fast(target_path, progress_callback=_cb_fast)
        disk_paths = {f["ruta_actual"] for f in disk_files}

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

        # ── Smart BLAKE2b hashing (selective: docs always; non-docs only if
        #    size-duplicate exists; 8 KB prefix compare before full hash) ──────
        candidates = [*new_files, *modified]
        n_candidates = len(candidates)
        n_hashed = 0

        with _lock:
            _ss.hechos = 0
            _ss.total = n_candidates
            _ss.archivo_actual = ""
            _ss.eta_segundos = -1.0

        def _on_hash_progress(ruta: str, hashed: bool):
            nonlocal n_hashed
            with _lock:
                _ss.hechos += 1
                _ss.archivo_actual = Path(ruta).name
            if hashed:
                n_hashed += 1

        hash_map = scanner.smart_hash_files(
            candidates,
            disk_files,
            on_progress=_on_hash_progress,
            is_cancelled=lambda: _ss.cancelled,
        )

        # ── Insert new files ──────────────────────────────────────────────────
        cache_hits = 0
        to_analyze: dict[str, int] = {}

        for f in new_files:
            if _ss.cancelled:
                break
            h = hash_map[f["ruta_actual"]]
            aid = database.insert_archivo(
                nombre=f["nombre"],
                extension=f["extension"],
                ruta_actual=f["ruta_actual"],
                tamaño_bytes=f["tamaño_bytes"],
                fecha_modificacion=f["fecha_modificacion"],
                hash_blake2=h,
                categoria_id=f["categoria_id"],
            )
            database.insert_historial(aid, None, f["ruta_actual"], "indexar")
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

        # ── Update modified files ─────────────────────────────────────────────
        for f in modified:
            if _ss.cancelled:
                break
            h = hash_map[f["ruta_actual"]]
            database.update_archivo_full(
                archivo_id=f["db_id"],
                nombre=f["nombre"],
                extension=f["extension"],
                ruta_actual=f["ruta_actual"],
                tamaño_bytes=f["tamaño_bytes"],
                fecha_modificacion=f["fecha_modificacion"],
                hash_blake2=h,
                categoria_id=f["categoria_id"],
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

        # ── Analysis phase (Ollama, weighted EMA) ─────────────────────────────
        # Check embed model once before the loop; missing it is non-fatal
        _embed_check = ollama_client.check_ollama([EMBED_MODEL])
        _embed_available = _embed_check["running"] and not _embed_check["missing"]
        if not _embed_available:
            _wlog.warning("embed model '%s' not available — embeddings skipped this scan", EMBED_MODEL)

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

            if result:
                cat_id = scanner.CATEGORIA_IDS.get(result.get("categoria", ""), None)
                database.update_archivo_resumen(aid, result.get("resumen", ""), cat_id)
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
            with _lock:
                _ss.fase = "recomendaciones"
                _ss.hechos = 0
                _ss.total = 0
                _ss.archivo_actual = ""
                _ss.eta_segundos = -1.0
            database.clear_recomendaciones()
            recommendations.run_all_rules()

        # ── Complete ──────────────────────────────────────────────────────────
        with _lock:
            _ss.fase = "completado"
            _ss.eta_segundos = 0.0
            savings_pct = round(100 * (1 - n_hashed / max(n_candidates, 1)))
            total_fallos = _ss.fallos_extraccion + _ss.fallos_ollama
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
            _wlog.info(
                "Scan complete — analizados=%d, fallidos=%d (extracción=%d, Ollama=%d)"
                " — detalle en logs/fileorganizer.log",
                _ss.analizados,
                total_fallos,
                _ss.fallos_extraccion,
                _ss.fallos_ollama,
            )

    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        with _lock:
            _ss.errores.append(err)
            _ss.fase = "error"

    finally:
        with _lock:
            _ss.running = False


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

        ok = organizer.execute_move(row["id"], ruta_actual, str(dst))
        results.append({"ruta": ruta_actual, "success": ok, "destino": str(dst)})

    return jsonify({"results": results})


# ── Undo API ──────────────────────────────────────────────────────────────────


@app.route("/api/undo/<int:backup_id>", methods=["POST"])
def api_undo(backup_id):
    ok, msg = organizer.undo_operation(backup_id)
    return jsonify({"success": ok, "message": msg})


@app.route("/api/undo-all", methods=["POST"])
def api_undo_all():
    success, fail = organizer.undo_all_pending()
    return jsonify(
        {
            "success": success,
            "fail": fail,
            "message": f"Revertidas {success} operaciones. {fail} fallaron.",
        }
    )


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
    atexit.register(_watcher_module.manager.stop)
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    start_server()
