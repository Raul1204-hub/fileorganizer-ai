import sys
import threading
import webbrowser
from pathlib import Path

# Ensure project root is importable regardless of how this module is loaded
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, jsonify, render_template, request

import chat as chat_module
import database
import organizer
import recommendations
import scanner
import analyzer

app = Flask(__name__, template_folder="templates")
app.secret_key = "fileorganizer-ai-secret-2024"

# ── Global scan state ─────────────────────────────────────────────────────────

_scan_state: dict = {
    "running": False,
    "status": "idle",   # idle | scanning | indexing | analyzing | recommending | done | error
    "progress": 0,
    "total": 0,
    "current_file": "",
    "error": None,
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
        scan_state=_scan_state,
    )


@app.route("/explorar")
def explorar():
    search     = request.args.get("search", "").strip() or None
    raw_cat    = request.args.get("categoria_id", "")
    categoria_id = int(raw_cat) if raw_cat.isdigit() else None
    sort       = request.args.get("sort", "fecha")   # fecha | nombre | tamaño
    page       = max(1, int(request.args.get("page", 1)))
    per_page   = 50
    offset     = (page - 1) * per_page

    all_files  = database.get_all_archivos(search=search, categoria_id=categoria_id)

    # Sort in Python (avoids changing DB layer)
    sort_keys  = {"nombre": lambda f: (f["nombre"] or "").lower(),
                  "tamaño": lambda f: f["tamaño_bytes"] or 0,
                  "fecha":  lambda f: f["fecha_modificacion"] or ""}
    all_files.sort(key=sort_keys.get(sort, sort_keys["fecha"]), reverse=(sort != "nombre"))

    total      = len(all_files)
    pages      = max(1, (total + per_page - 1) // per_page)
    archivos   = all_files[offset : offset + per_page]
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
    _scan_state["running"] = True
    _scan_state["status"] = "scanning"
    _scan_state["error"] = None
    _scan_state["progress"] = 0
    _scan_state["total"] = 0
    _scan_state["current_file"] = ""

    try:
        def _progress(done, total, filename):
            _scan_state["progress"] = done
            _scan_state["total"] = total
            _scan_state["current_file"] = filename

        # Scan filesystem
        files = scanner.scan_directory(target_path, progress_callback=_progress)
        _scan_state["status"] = "indexing"

        # Clear + re-index
        database.delete_all_archivos()
        database.clear_recomendaciones()
        archivo_ids: dict[str, int] = {}

        for f in files:
            aid = database.insert_archivo(
                nombre=f["nombre"],
                extension=f["extension"],
                ruta_actual=f["ruta_actual"],
                tamaño_bytes=f["tamaño_bytes"],
                fecha_modificacion=f["fecha_modificacion"],
                hash_md5=f["hash_md5"],
                categoria_id=f["categoria_id"],
            )
            archivo_ids[f["ruta_actual"]] = aid
            database.insert_historial(aid, None, f["ruta_actual"], "indexar")

        # Analyze Documentos with Ollama
        _scan_state["status"] = "analyzing"
        doc_exts = {".pdf", ".docx", ".doc", ".txt", ".odt", ".xlsx", ".csv"}
        doc_files = [f for f in files if f["extension"].lower() in doc_exts]
        _scan_state["total"] = len(doc_files)

        for i, f in enumerate(doc_files, 1):
            _scan_state["progress"] = i
            _scan_state["current_file"] = f["nombre"]
            result = analyzer.analyze_file(Path(f["ruta_actual"]), f["extension"])
            if result:
                aid = archivo_ids.get(f["ruta_actual"])
                if aid:
                    cat_id = scanner.CATEGORIA_IDS.get(result.get("categoria", ""), None)
                    database.update_archivo_resumen(aid, result.get("resumen", ""), cat_id)
                    for tag in result.get("etiquetas", []):
                        if tag:
                            database.insert_etiqueta(aid, str(tag))

        # Recommendations
        _scan_state["status"] = "recommending"
        recommendations.run_all_rules()

        _scan_state["status"] = "done"

    except Exception as exc:
        _scan_state["error"] = str(exc)
        _scan_state["status"] = "error"
    finally:
        _scan_state["running"] = False


@app.route("/api/scan", methods=["POST"])
def api_scan():
    data = request.get_json() or {}
    target_path = (data.get("path") or "").strip()
    if not target_path:
        return jsonify({"error": "Ruta no proporcionada"}), 400
    if not Path(target_path).exists():
        return jsonify({"error": f"La ruta no existe: {target_path}"}), 400
    if _scan_state["running"]:
        return jsonify({"error": "Ya hay un escaneo en curso"}), 409

    thread = threading.Thread(target=_run_scan, args=(target_path,), daemon=True)
    thread.start()
    return jsonify({"message": "Escaneo iniciado", "status": "started"})


@app.route("/api/scan/status")
def api_scan_status():
    return jsonify(_scan_state)


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


@app.route("/api/ollama-status")
def api_ollama_status():
    """Check Ollama availability and installed models."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        return jsonify({"running": True, "models": models})
    except Exception:
        return jsonify({"running": False, "models": []})


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
    return jsonify({
        "success": success,
        "fail": fail,
        "message": f"Revertidas {success} operaciones. {fail} fallaron.",
    })


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


# ── Server entry point ────────────────────────────────────────────────────────

def start_server(open_browser: bool = True):
    database.create_tables()
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    start_server()
