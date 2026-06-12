"""FileOrganizer AI — filesystem watcher.

Thread model:
  watchdog observer thread
      → _FileHandler.on_*()
          deleted / moved  → immediate DB update (fast SQLite write)
          created / modify → add to _debounce_map (3 s debounce)
  _debounce_thread (polls every 0.5 s)
      → pushes ready paths to _work_queue
  _worker_thread  (single, serialises all Ollama calls)
      → hash + DB upsert + Ollama analysis
"""

import fnmatch
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import analyzer
import database
import embeddings as _embed_module
import scanner
from log import get_logger

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    FileSystemEventHandler = object  # type: ignore[assignment,misc]
    Observer = None  # type: ignore[assignment,misc]

logger = get_logger("fileorganizer.watcher")

_DEBOUNCE_SECONDS = 3.0

# Filename / component patterns to ignore (fnmatch-style)
_IGNORE_PATTERNS: frozenset[str] = frozenset(
    {
        "~$*",  # MS Office temp files
        "*.tmp",
        "*.crdownload",  # Chrome partial downloads
        "*.part",  # Firefox partial downloads
        ".git",
        "__pycache__",
        "*.pyc",
        "*.swp",
        "*.swo",
        ".DS_Store",
        "Thumbs.db",
        "desktop.ini",
    }
)

# Project-owned directories (never watch our own DB / logs)
_APP_ROOT = Path(__file__).parent.resolve()
_APP_IGNORE_ROOTS: list[str] = [
    str(_APP_ROOT / "data"),
    str(_APP_ROOT / "logs"),
    str(_APP_ROOT / ".git"),
    str(_APP_ROOT / "__pycache__"),
]


def _should_ignore(path: str, extra_roots: list[str] | None = None) -> bool:
    p = Path(path)
    for part in p.parts:
        for pat in _IGNORE_PATTERNS:
            if fnmatch.fnmatch(part, pat):
                return True
    for root in _APP_IGNORE_ROOTS + (extra_roots or []):
        try:
            p.relative_to(root)
            return True
        except ValueError:
            pass
    return False


# ── Watcher state ─────────────────────────────────────────────────────────────


class _WatchState:
    def __init__(self) -> None:
        self.running: bool = False
        self.folder: str = ""
        self.last_event: str = ""
        self.last_event_time: str = ""
        self.events_processed: int = 0


# ── Watchdog event handler ────────────────────────────────────────────────────


class _FileHandler(FileSystemEventHandler):
    def __init__(self, manager: "WatcherManager") -> None:
        super().__init__()
        self._mgr = manager

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        if not self._mgr._should_ignore(event.src_path):
            self._mgr._debounce_add(event.src_path, "create")

    def on_modified(self, event) -> None:
        if event.is_directory:
            return
        if not self._mgr._should_ignore(event.src_path):
            self._mgr._debounce_add(event.src_path, "modify")

    def on_moved(self, event) -> None:
        if event.is_directory:
            self._mgr._handle_dir_moved(event.src_path, event.dest_path)
            return
        if self._mgr._should_ignore(event.dest_path):
            return
        self._mgr._handle_file_moved(event.src_path, event.dest_path)

    def on_deleted(self, event) -> None:
        if event.is_directory:
            self._mgr._handle_dir_deleted(event.src_path)
            return
        self._mgr._handle_file_deleted(event.src_path)


# ── Manager ───────────────────────────────────────────────────────────────────


class WatcherManager:
    def __init__(self) -> None:
        self._observer = None
        self._debounce_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._work_queue: queue.Queue = queue.Queue()
        self._debounce_map: dict[str, tuple[str, float]] = {}  # path → (evt_type, ts)
        self._debounce_lock = threading.Lock()
        self._state = _WatchState()
        self._state_lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self, folder: str) -> None:
        if not WATCHDOG_AVAILABLE:
            raise RuntimeError("watchdog no está instalado — ejecuta: pip install watchdog")
        with self._state_lock:
            if self._state.running:
                raise RuntimeError("El observador ya está activo")

        folder = str(Path(folder).resolve())
        self._stop_event.clear()

        handler = _FileHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, folder, recursive=True)
        self._observer.start()

        self._debounce_thread = threading.Thread(
            target=self._debounce_worker, daemon=True, name="watcher-debounce"
        )
        self._debounce_thread.start()

        self._worker_thread = threading.Thread(target=self._ollama_worker, daemon=True, name="watcher-ollama")
        self._worker_thread.start()

        with self._state_lock:
            self._state.running = True
            self._state.folder = folder
            self._state.events_processed = 0
            self._state.last_event = ""
            self._state.last_event_time = ""

        logger.info("watcher | start | %s", folder)

    def stop(self) -> None:
        with self._state_lock:
            if not self._state.running:
                return

        self._stop_event.set()

        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None

        if self._debounce_thread:
            self._debounce_thread.join(timeout=5)
            self._debounce_thread = None

        # Sentinel unblocks the worker
        self._work_queue.put(None)
        if self._worker_thread:
            self._worker_thread.join(timeout=10)
            self._worker_thread = None

        with self._debounce_lock:
            self._debounce_map.clear()

        with self._state_lock:
            self._state.running = False

        logger.info("watcher | stopped")

    def get_status(self) -> dict:
        with self._state_lock:
            return {
                "running": self._state.running,
                "folder": self._state.folder,
                "last_event": self._state.last_event,
                "last_event_time": self._state.last_event_time,
                "events_processed": self._state.events_processed,
                "queue_depth": self._work_queue.qsize(),
                "pending_debounce": len(self._debounce_map),
            }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _should_ignore(self, path: str) -> bool:
        return _should_ignore(path)

    def _debounce_add(self, path: str, event_type: str) -> None:
        with self._debounce_lock:
            self._debounce_map[path] = (event_type, time.monotonic())

    def _record_event(self, description: str) -> None:
        with self._state_lock:
            self._state.last_event = description
            self._state.last_event_time = datetime.now().isoformat(timespec="seconds")
            self._state.events_processed += 1

    # ── Immediate event handlers (run in watchdog thread) ─────────────────────

    def _handle_file_moved(self, src: str, dst: str) -> None:
        try:
            existing = database.get_archivo_by_ruta(src)
            if existing:
                database.update_archivo_ruta(existing["id"], dst)
                database.insert_historial(existing["id"], src, dst, "mover")
                logger.info("watcher | moved | %s → %s", Path(src).name, Path(dst).name)
                self._record_event(f"Movido: {Path(dst).name}")
            else:
                # Source not indexed — treat destination as new creation
                if not self._should_ignore(dst):
                    self._debounce_add(dst, "create")
        except Exception as exc:
            logger.warning("watcher | moved_error | %s | %s", src, exc)

    def _handle_file_deleted(self, path: str) -> None:
        try:
            existing = database.get_archivo_by_ruta(path)
            if existing:
                database.mark_archivo_desaparecido(existing["id"])
                logger.info("watcher | deleted | %s", Path(path).name)
                self._record_event(f"Borrado: {Path(path).name}")
        except Exception as exc:
            logger.warning("watcher | deleted_error | %s | %s", path, exc)

    def _handle_dir_moved(self, src: str, dst: str) -> None:
        try:
            count = database.move_directory_archivos(src, dst)
            if count:
                logger.info("watcher | dir_moved | %s → %s (%d archivos)", src, dst, count)
                self._record_event(f"Dir movido: {Path(dst).name} ({count} archivos)")
        except Exception as exc:
            logger.warning("watcher | dir_moved_error | %s | %s", src, exc)

    def _handle_dir_deleted(self, path: str) -> None:
        try:
            count = database.mark_archivos_bajo_ruta_desaparecidos(path)
            if count:
                logger.info("watcher | dir_deleted | %s (%d archivos)", path, count)
                self._record_event(f"Dir borrado: {Path(path).name} ({count} archivos)")
        except Exception as exc:
            logger.warning("watcher | dir_deleted_error | %s | %s", path, exc)

    # ── Debounce worker ───────────────────────────────────────────────────────

    def _debounce_worker(self) -> None:
        while not self._stop_event.is_set():
            now = time.monotonic()
            ready: list[str] = []
            with self._debounce_lock:
                for path, (_evt, ts) in list(self._debounce_map.items()):
                    if now - ts >= _DEBOUNCE_SECONDS:
                        ready.append(path)
                        del self._debounce_map[path]
            for path in ready:
                self._work_queue.put(("index", path))
            time.sleep(0.5)

    # ── Ollama worker ─────────────────────────────────────────────────────────

    def _ollama_worker(self) -> None:
        while True:
            try:
                item = self._work_queue.get(timeout=1)
            except queue.Empty:
                if self._stop_event.is_set():
                    break
                continue
            if item is None:  # sentinel
                break
            kind, path = item
            try:
                if kind == "index":
                    self._process_index(path)
            except Exception as exc:
                logger.warning("watcher | worker_error | %s | %s", path, exc)
            finally:
                self._work_queue.task_done()

    def _process_index(self, path: str) -> None:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return

        try:
            meta = scanner.get_file_metadata(p)
        except (PermissionError, OSError) as exc:
            logger.warning("watcher | stat | %s | %s", path, exc)
            return

        ext = meta["extension"]
        is_doc = ext in scanner.DOC_EXTS

        hash_blake2 = scanner.compute_blake2b(p) if is_doc else ""

        existing = database.get_archivo_by_ruta(path)

        if existing:
            # Skip re-processing if hash matches (content unchanged)
            if hash_blake2 and existing.get("hash_blake2") == hash_blake2:
                database.mark_archivo_existe(existing["id"])
                return
            database.update_archivo_full(
                archivo_id=existing["id"],
                nombre=meta["nombre"],
                extension=ext,
                ruta_actual=path,
                tamaño_bytes=meta["tamaño_bytes"],
                fecha_modificacion=meta["fecha_modificacion"],
                hash_blake2=hash_blake2,
                categoria_id=meta["categoria_id"],
            )
            database.clear_etiquetas_archivo(existing["id"])
            database.update_archivo_resumen(existing["id"], None)
            database.insert_historial(existing["id"], path, path, "actualizar")
            archivo_id = existing["id"]
        else:
            archivo_id = database.insert_archivo(
                nombre=meta["nombre"],
                extension=ext,
                ruta_actual=path,
                tamaño_bytes=meta["tamaño_bytes"],
                fecha_modificacion=meta["fecha_modificacion"],
                hash_blake2=hash_blake2,
                categoria_id=meta["categoria_id"],
            )
            database.insert_historial(archivo_id, None, path, "indexar")

        logger.info("watcher | indexed | %s", p.name)
        self._record_event(f"Indexado: {p.name}")

        if not is_doc:
            return

        # Check analysis cache by BLAKE2b hash
        if hash_blake2:
            cached = database.get_resumen_by_hash(hash_blake2)
            if cached and cached.get("resumen_ia"):
                database.update_archivo_resumen(archivo_id, cached["resumen_ia"])
                if cached["id"] != archivo_id:
                    database.copy_etiquetas(cached["id"], archivo_id)
                return

        result = analyzer.analyze_file(p, ext)
        if result:
            result.pop("_text_len", None)
            cat_id = scanner.CATEGORIA_IDS.get(result.get("categoria", ""), None)
            database.update_archivo_resumen(archivo_id, result.get("resumen", ""), cat_id)
            etiquetas_result: list[str] = []
            for tag in result.get("etiquetas", []):
                if tag:
                    database.insert_etiqueta(archivo_id, str(tag))
                    etiquetas_result.append(str(tag))
            # Generate embedding (non-fatal)
            try:
                _embed_module.index_archivo_from_result(
                    archivo_id, p.name, etiquetas_result, result.get("resumen", "")
                )
            except Exception as _exc:
                logger.warning("watcher | embed_failed | %s | %s", p.name, _exc)
            logger.info("watcher | analyzed | %s", p.name)
            self._record_event(f"Analizado: {p.name}")


# ── Module-level singleton ────────────────────────────────────────────────────

manager = WatcherManager()
