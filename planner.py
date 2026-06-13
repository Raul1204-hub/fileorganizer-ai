"""Plan de organización: genera en dry-run la lista de movimientos propuestos.

Strategy: carpeta_raiz / Categoria / [subcarpeta_etiqueta] / nombre_archivo
  - Subcarpeta: primera etiqueta del archivo (más reciente por id), sanitizada.
  - Archivos ya en la carpeta correcta se excluyen automáticamente.
All items are created with estado='aprobado' (checked by default).
"""

import re
from pathlib import Path

import database


def _sanitize_folder(name: str) -> str:
    """Strip Windows-illegal chars; keep accented letters (valid on NTFS)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    return name[:50] or "General"


def generar_plan(carpeta_raiz: str, archivo_ids: list[int] | None = None) -> int:
    """Build and persist a move plan. Returns plan_id.

    Fetches all tags in one query to avoid N+1 DB calls.
    Files already sitting in their target folder are silently excluded.
    """
    raiz = Path(carpeta_raiz)

    archivos = database.get_all_archivos()
    if archivo_ids:
        id_set = set(archivo_ids)
        archivos = [a for a in archivos if a["id"] in id_set]

    # One query for all tags
    all_tags = database.get_all_etiquetas_grouped()

    plan_id = database.insert_plan(carpeta_raiz)

    orden = 0
    for archivo in archivos:
        cat_nombre = _sanitize_folder(archivo.get("categoria_nombre") or "Desconocido")

        tags = all_tags.get(archivo["id"], [])
        subcarpeta = _sanitize_folder(tags[0]) if tags else None

        destino_dir = raiz / cat_nombre / subcarpeta if subcarpeta else raiz / cat_nombre
        destino = destino_dir / archivo["nombre"]

        # Skip files that are already in the right place
        try:
            if Path(archivo["ruta_actual"]).parent.resolve() == destino_dir.resolve():
                continue
        except OSError:
            pass  # Path might not exist yet; include the item

        motivo = cat_nombre + ("/" + subcarpeta if subcarpeta else "")

        database.insert_plan_item(
            plan_id=plan_id,
            archivo_id=archivo["id"],
            origen=archivo["ruta_actual"],
            destino=str(destino),
            motivo=motivo,
            orden=orden,
        )
        orden += 1

    database.update_plan_stats(plan_id)
    return plan_id


def get_destinos_unicos(plan_id: int) -> list[str]:
    """Sorted list of unique destination folder paths in the plan."""
    items = database.get_plan_items(plan_id)
    return sorted({str(Path(i["destino"]).parent) for i in items})
