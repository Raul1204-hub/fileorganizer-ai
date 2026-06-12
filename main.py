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
    """Scan, index, analyse and recommend — all from the CLI."""
    import scanner
    import analyzer
    import recommendations

    print(f"[+] Target: {target_path}")
    database.create_tables()

    # ── Scan ──────────────────────────────────────────────────────────────────
    print("[+] Scanning filesystem…")

    def _progress(done, total, filename):
        print(f"\r  [{done}/{total}] {filename[:60]}", end="", flush=True)

    files = scanner.scan_directory(target_path, progress_callback=_progress)
    print(f"\n[+] Found {len(files)} file(s)")

    # ── Index ─────────────────────────────────────────────────────────────────
    print("[+] Indexing into database…")
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

    print(f"[+] Indexed {len(files)} file(s)")

    # ── Analyse documents ─────────────────────────────────────────────────────
    doc_exts = {".pdf", ".docx", ".doc", ".txt", ".odt", ".xlsx", ".csv"}
    doc_files = [f for f in files if f["extension"].lower() in doc_exts]
    print(f"[+] Analysing {len(doc_files)} document(s) with Ollama (qwen3:30b)…")

    for i, f in enumerate(doc_files, 1):
        print(f"\r  [{i}/{len(doc_files)}] {f['nombre'][:60]}", end="", flush=True)
        result = analyzer.analyze_file(Path(f["ruta_actual"]), f["extension"])
        if result:
            aid = archivo_ids.get(f["ruta_actual"])
            if aid:
                cat_id = scanner.CATEGORIA_IDS.get(result.get("categoria", ""), None)
                database.update_archivo_resumen(aid, result.get("resumen", ""), cat_id)
                for tag in result.get("etiquetas", []):
                    if tag:
                        database.insert_etiqueta(aid, str(tag))

    print("\n[+] Analysis complete")

    # ── Recommendations ───────────────────────────────────────────────────────
    print("[+] Running recommendation rules…")
    recommendations.run_all_rules()
    recs = database.get_recomendaciones(solo_activas=True)
    print(f"[+] Generated {len(recs)} recommendation(s)")
    print("\nDone. Start the web UI with: python main.py")


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
        print("[+] Web UI → http://localhost:5000")
        print("[+] Press Ctrl+C to stop\n")
        start_server(open_browser=True)


if __name__ == "__main__":
    main()
