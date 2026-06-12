"""Unified Ollama HTTP client for FileOrganizer AI.

Single source of truth for all Ollama communication:
  call_ollama()  — generate text from a model
  check_ollama() — pre-flight: is Ollama running? are required models installed?
  pull_commands() — format 'ollama pull …' lines for user display
"""

import re

import requests

from config import OLLAMA_BASE, OLLAMA_TIMEOUT, ANALYSIS_MODEL, SQL_MODEL, RESPONSE_MODEL

# All models the application uses, in priority order (de-duplicated)
REQUIRED_MODELS: list[str] = list(dict.fromkeys([SQL_MODEL, RESPONSE_MODEL, ANALYSIS_MODEL]))


def call_ollama(model: str, prompt: str, timeout: int | None = None) -> str:
    """POST to /generate and return the model response.

    - Strips <think>…</think> blocks emitted by some qwen3 models.
    - Returns '' on soft errors (bad JSON, HTTP 5xx, etc.).
    - Raises RuntimeError("ollama_not_running") if the server is unreachable.
    - Raises RuntimeError("model_not_found") if the model isn't installed.
    """
    if timeout is None:
        timeout = OLLAMA_TIMEOUT
    try:
        resp = requests.post(
            f"{OLLAMA_BASE}/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    except requests.exceptions.ConnectionError:
        raise RuntimeError("ollama_not_running")
    except Exception as exc:
        msg = str(exc).lower()
        if "model" in msg and ("not found" in msg or "pull" in msg):
            raise RuntimeError("model_not_found")
        return ""


def check_ollama(required: list[str] | None = None) -> dict:
    """Return {"running": bool, "installed": [str], "missing": [str]}.

    `required` defaults to all models declared in config (REQUIRED_MODELS).
    A model is considered present when its full name appears as a substring
    of any installed model name (e.g. "qwen3:8b" matches "qwen3:8b").
    """
    if required is None:
        required = REQUIRED_MODELS

    try:
        resp = requests.get(f"{OLLAMA_BASE}/tags", timeout=5)
        installed = [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        return {"running": False, "installed": [], "missing": list(required)}

    missing = [m for m in required if not any(m in im for im in installed)]
    return {"running": True, "installed": installed, "missing": missing}


def pull_commands(missing: list[str]) -> str:
    """Return formatted 'ollama pull …' lines ready to print."""
    return "\n".join(f"  ollama pull {m}" for m in missing)
