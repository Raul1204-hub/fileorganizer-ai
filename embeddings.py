"""Semantic embedding generation and cosine-similarity search for FileOrganizer AI.

Storage:  float32 vectors packed with struct into SQLite BLOB — no native extension required.
Search:   cosine similarity computed in Python — sufficient for tens of thousands of files
          (< 200 ms per query for 10 000 files on a modern CPU).

Typical workflow:
  1. After each Ollama analysis, call index_archivo_from_result().
  2. For backfill of existing files, run: python main.py reindex-embeddings.
  3. Call semantic_search(query) to return ranked results.
"""

import struct

import database
import ollama_client
from config import SEMANTIC_THRESHOLD, SEMANTIC_TOP_K
from log import get_logger

logger = get_logger("fileorganizer.embeddings")


# ── Vector serialisation ──────────────────────────────────────────────────────


def pack_vector(vec: list[float]) -> bytes:
    """Serialise a float32 list to little-endian bytes."""
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack_vector(blob: bytes) -> list[float]:
    """Deserialise bytes back to a float32 list."""
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


# ── Similarity ────────────────────────────────────────────────────────────────


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── Text composition ──────────────────────────────────────────────────────────


def build_embed_text(nombre: str, etiquetas: list[str], resumen_ia: str) -> str:
    """Compose the text that is embedded for a file.

    Combines the filename, tags, and AI summary so that the embedding captures
    both metadata and content signals.
    """
    parts: list[str] = [nombre]
    parts.extend(e for e in etiquetas if isinstance(e, str) and e.strip())
    if resumen_ia and resumen_ia.strip():
        parts.append(resumen_ia.strip())
    return " ".join(p.strip() for p in parts if p.strip())


# ── Indexing ──────────────────────────────────────────────────────────────────


def index_archivo(archivo_id: int, text: str) -> bool:
    """Embed text and persist the vector for archivo_id.  Returns True on success."""
    if not text.strip():
        return False
    vec = ollama_client.embed_text(text)
    if not vec:
        logger.warning("embed | empty vector returned | archivo_id=%d", archivo_id)
        return False
    blob = pack_vector(vec)
    database.upsert_embedding(archivo_id, blob, len(vec))
    logger.debug("embed | stored | archivo_id=%d | dim=%d", archivo_id, len(vec))
    return True


def index_archivo_from_result(
    archivo_id: int,
    nombre: str,
    etiquetas: list[str],
    resumen_ia: str,
) -> bool:
    """Convenience wrapper: called right after Ollama analysis stores its result."""
    text = build_embed_text(nombre, etiquetas, resumen_ia)
    return index_archivo(archivo_id, text)


# ── Semantic search ───────────────────────────────────────────────────────────


def semantic_search(
    query: str,
    top_k: int = SEMANTIC_TOP_K,
    threshold: float = SEMANTIC_THRESHOLD,
) -> list[dict]:
    """Embed the query then return the top-k most similar indexed files.

    Each result is the full archivo dict enriched with:
      score      float   cosine similarity (0–1)
      etiquetas  list    tag strings for that file

    Results are sorted descending by score, filtered at threshold.
    Only files still present on disk (existe=1) are returned.
    """
    if not query.strip():
        return []

    query_vec = ollama_client.embed_text(query)
    if not query_vec:
        logger.warning("embed | empty query vector | q=%s", query[:60])
        return []

    rows = database.get_all_embeddings()
    if not rows:
        return []

    scored: list[tuple[int, float]] = []
    for row in rows:
        try:
            vec = unpack_vector(row["vector"])
            score = cosine_similarity(query_vec, vec)
            if score >= threshold:
                scored.append((row["archivo_id"], score))
        except Exception:
            continue

    scored.sort(key=lambda x: x[1], reverse=True)
    scored = scored[:top_k]

    results: list[dict] = []
    for archivo_id, score in scored:
        archivo = database.get_archivo(archivo_id)
        if archivo and archivo.get("existe", 1):
            archivo["score"] = round(score, 4)
            archivo["etiquetas"] = database.get_etiquetas_by_archivo(archivo_id)
            results.append(archivo)

    logger.debug(
        "semantic_search | q=%s | candidates=%d | results=%d | threshold=%.2f",
        query[:40],
        len(rows),
        len(results),
        threshold,
    )
    return results
