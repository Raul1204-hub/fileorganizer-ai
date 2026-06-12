"""FileOrganizer AI — entry point.

Usage:
  python main.py           → start web UI (default)
  python main.py web       → start web UI
  python main.py scan PATH → scan directory via CLI (no web server)
"""

import argparse
import sys
from pathlib import Path

import database


def cli_scan(target_path: str) -> None:
    """Incremental scan: only processes new/modified files, preserves history."""
    import scanner
    import analyzer
    import recommendations

    print(f"[+] Target: {target_path}")
    database.create_tables()

    # ── Fast disk scan (stat only, no MD5) ────────────────────────────────────
    print("[+] Scanning filesystem…")

    def _progress(done, total, filename):
        print(f"\r  [{done}/{total}] {filename[:60]}", end="", flush=True)

    disk_files = scanner.scan_directory_fast(target_path, progress_callback=_progress)
    disk_paths = {f["ruta_actual"] for f in disk_files}
    print(f"\n[+] Found {len(disk_files)} file(s) on disk")

    # ── Reconcile against DB ───────────────────────────────────────────────────
    print("[+] Reconciling with database…")
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
        elif (f["tamaño_bytes"] == db_row["tamaño_bytes"]
              and f["fecha_modificacion"] == db_row["fecha_modificacion"]):
            if not db_row.get("existe", 1):
                database.mark_archivo_existe(db_row["id"])
            unchanged.append(f)
        else:
            modified.append({**f, "db_id": db_row["id"]})

    for ruta, db_row in db_index.items():
        if ruta not in disk_paths:
            disappeared_ids.append(db_row["id"])

    print(f"    Sin cambios: {len(unchanged)}  |  Nuevos: {len(new_files)}"
          f"  |  Modificados: {len(modified)}  |  Desaparecidos: {len(disappeared_ids)}")

    # ── Mark disappeared ──────────────────────────────────────────────────────
    for aid in disappeared_ids:
        database.mark_archivo_desaparecido(aid)

    # ── Smart BLAKE2b hashing (selective) ────────────────────────────────────
    candidates = [*new_files, *modified]
    n_hashed = [0]
    _hash_count = [0]

    def _hash_progress(ruta: str, hashed: bool):
        _hash_count[0] += 1
        if hashed:
            n_hashed[0] += 1
        print(f"\r  [{_hash_count[0]}/{len(candidates)}] {Path(ruta).name[:60]}", end="", flush=True)

    print(f"[+] Hashing {len(candidates)} candidate(s) (BLAKE2b, selective)…")
    hash_map = scanner.smart_hash_files(candidates, disk_files, on_progress=_hash_progress)
    if candidates:
        print()

    savings_pct = round(100 * (1 - n_hashed[0] / max(len(candidates), 1)))
    print(f"    Hasheados: {n_hashed[0]} de {len(candidates)} ({savings_pct}% ahorro)")

    # ── Insert new files ──────────────────────────────────────────────────────
    print(f"[+] Inserting {len(new_files)} new file(s) into DB…")
    cache_hits = 0
    to_analyze: dict[str, int] = {}

    for f in new_files:
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

    # ── Update modified files ─────────────────────────────────────────────────
    print(f"[+] Updating {len(modified)} modified file(s) in DB…")
    for f in modified:
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

    # ── Analyse only new/modified documents without a cached resumen ──────────
    doc_exts = {".pdf", ".docx", ".doc", ".txt", ".odt", ".xlsx", ".csv"}
    docs_to_analyze = {
        ruta: aid for ruta, aid in to_analyze.items()
        if Path(ruta).suffix.lower() in doc_exts
    }
    print(f"[+] Analysing {len(docs_to_analyze)} document(s) with Ollama…")

    for i, (ruta, aid) in enumerate(docs_to_analyze.items(), 1):
        print(f"\r  [{i}/{len(docs_to_analyze)}] {Path(ruta).name[:60]}", end="", flush=True)
        result = analyzer.analyze_file(Path(ruta), Path(ruta).suffix.lower())
        if result:
            cat_id = scanner.CATEGORIA_IDS.get(result.get("categoria", ""), None)
            database.update_archivo_resumen(aid, result.get("resumen", ""), cat_id)
            for tag in result.get("etiquetas", []):
                if tag:
                    database.insert_etiqueta(aid, str(tag))

    if docs_to_analyze:
        print()
    print("[+] Analysis complete")

    # ── Recommendations ───────────────────────────────────────────────────────
    print("[+] Running recommendation rules…")
    database.clear_recomendaciones()
    recommendations.run_all_rules()
    recs = database.get_recomendaciones(solo_activas=True)
    print(f"[+] Generated {len(recs)} recommendation(s)")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"""
── Scan summary ──────────────────────────────────────
  Sin cambios       : {len(unchanged)}
  Nuevos            : {len(new_files)}
  Modificados       : {len(modified)}
  Desaparecidos     : {len(disappeared_ids)}
  Hasheados         : {n_hashed[0]} de {len(candidates)} ({savings_pct}% ahorro)
  Análisis evitados : {cache_hits}  (caché BLAKE2b)
──────────────────────────────────────────────────────
Done. Start the web UI with: python main.py
""")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FileOrganizer AI — offline AI-powered file organizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("web", help="Start the Flask web UI (default)")

    scan_p = subparsers.add_parser("scan", help="Scan a directory from CLI")
    scan_p.add_argument("path", help="Path to the directory to scan")

    args = parser.parse_args()

    if args.command == "scan":
        if not Path(args.path).exists():
            print(f"[!] Path does not exist: {args.path}", file=sys.stderr)
            sys.exit(1)
        cli_scan(args.path)
    else:
        # Default: launch web server
        database.create_tables()
        from web.app import start_server
        print("[+] FileOrganizer AI starting…")
        print("[+] Web UI -> http://localhost:5000")
        print("[+] Press Ctrl+C to stop\n")
        start_server(open_browser=True)


if __name__ == "__main__":
    main()
