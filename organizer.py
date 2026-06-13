import shutil
from pathlib import Path

import database


def propose_organization(files: list[dict]) -> list[dict]:
    """Return annotated proposals (adds is_duplicate flag) from raw scan results."""
    proposals: list[dict] = []
    seen_hashes: dict[str, str] = {}

    for f in files:
        h = f.get("hash_blake2", "")
        is_dup = False
        dup_of = None
        if h:
            if h in seen_hashes:
                is_dup = True
                dup_of = seen_hashes[h]
            else:
                seen_hashes[h] = f["ruta_actual"]

        proposals.append(
            {
                "nombre": f["nombre"],
                "ruta_actual": f["ruta_actual"],
                "categoria_nombre": f["categoria_nombre"],
                "tamaño_bytes": f.get("tamaño_bytes", 0),
                "hash_blake2": h,
                "is_duplicate": is_dup,
                "duplicate_of": dup_of,
            }
        )

    return proposals


def execute_move(archivo_id: int, ruta_origen: str, ruta_destino: str) -> bool:
    """Write backup record then move the file. Returns True on success."""
    src = Path(ruta_origen)
    dst = Path(ruta_destino)

    if not src.exists():
        return False

    archivo = database.get_archivo(archivo_id)
    if not archivo:
        return False

    # Backup MUST be written before any filesystem change
    database.insert_backup_operacion(
        archivo_id=archivo_id,
        nombre_original=archivo["nombre"],
        ruta_original=ruta_origen,
        ruta_nueva=ruta_destino,
        operacion="mover",
    )

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        database.update_archivo_ruta(archivo_id, ruta_destino)
        database.insert_historial(archivo_id, ruta_origen, ruta_destino, "mover")
        return True
    except (PermissionError, OSError):
        return False


def undo_operation(backup_id: int) -> tuple[bool, str]:
    """Revert one backup operation. Returns (success, message)."""
    backup = database.get_backup_operacion(backup_id)
    if not backup:
        return False, "Operación no encontrada"
    if backup["revertido"]:
        return False, "Esta operación ya fue revertida"

    ruta_nueva = backup["ruta_nueva"]
    ruta_original = backup["ruta_original"]

    src = Path(ruta_nueva) if ruta_nueva else None
    dst = Path(ruta_original)

    if src and not src.exists():
        return False, f"Archivo no encontrado en: {src}"

    try:
        if src:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        database.update_archivo_ruta(backup["archivo_id"], ruta_original)
        database.mark_archivo_existe(backup["archivo_id"])
        database.mark_backup_revertido(backup_id)
        database.insert_historial(
            backup["archivo_id"],
            ruta_nueva,
            ruta_original,
            "reversion",
        )
        return True, "Operación revertida correctamente"
    except (PermissionError, OSError) as e:
        return False, f"Error al revertir: {e}"


def execute_delete_duplicate(archivo_id: int, backup_dir: Path) -> tuple[bool, str]:
    """Move a duplicate file to the backup folder and mark it as deleted.

    Writes the backup record before any filesystem change so that
    undo_operation() can later restore the file.  Returns (success, message).
    """
    archivo = database.get_archivo(archivo_id)
    if not archivo:
        return False, f"Archivo {archivo_id} no encontrado en la base de datos"

    src = Path(archivo["ruta_actual"])
    if not src.exists():
        return False, f"Archivo no encontrado en disco: {src}"

    dst = backup_dir / src.name
    if dst.exists():
        dst = backup_dir / f"{src.stem}_{archivo_id}{src.suffix}"

    # Write backup record before any filesystem change
    database.insert_backup_operacion(
        archivo_id=archivo_id,
        nombre_original=archivo["nombre"],
        ruta_original=str(src),
        ruta_nueva=str(dst),
        operacion="eliminar_dup",
    )

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        database.mark_archivo_desaparecido(archivo_id)
        database.insert_historial(archivo_id, str(src), str(dst), "eliminar_dup")
        return True, f"Movido a backup: {dst.name}"
    except (PermissionError, OSError) as exc:
        return False, f"Error al mover: {exc}"


def undo_all_pending() -> tuple[int, int]:
    """Revert every pending operation. Returns (success_count, fail_count)."""
    pending = database.get_backup_operaciones(solo_pendientes=True)
    success = fail = 0
    for op in pending:
        ok, _ = undo_operation(op["id"])
        if ok:
            success += 1
        else:
            fail += 1
    return success, fail
