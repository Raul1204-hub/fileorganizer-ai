"""Central configuration for FileOrganizer AI.

All values can be overridden with environment variables (prefix FORG_).
Example:
    FORG_ANALYSIS_MODEL=qwen3:30b python main.py
"""

import os
from pathlib import Path

# ── Ollama connection ──────────────────────────────────────────────────────────
OLLAMA_BASE = os.environ.get("FORG_OLLAMA_BASE", "http://localhost:11434/api")
OLLAMA_TIMEOUT = int(os.environ.get("FORG_OLLAMA_TIMEOUT", "180"))

# ── AI models ─────────────────────────────────────────────────────────────────
ANALYSIS_MODEL = os.environ.get("FORG_ANALYSIS_MODEL", "qwen3:8b")  # document analysis
SQL_MODEL = os.environ.get("FORG_SQL_MODEL", "qwen2.5-coder:7b")  # Text-to-SQL
RESPONSE_MODEL = os.environ.get("FORG_RESPONSE_MODEL", "qwen3:8b")  # chat answers

# ── Paths ──────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent
DB_PATH = Path(os.environ.get("FORG_DB_PATH", str(_ROOT / "data" / "catalogo.db")))
