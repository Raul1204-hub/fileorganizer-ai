"""Unified Ollama HTTP client for FileOrganizer AI.

Single source of truth for all Ollama communication:
  call_ollama()  — generate text from a model
  check_ollama() — pre-flight: is Ollama running? are required models installed?
  pull_commands() — format 'ollama pull …' lines for user display
"""

import re
import time

import requests

from config import OLLAMA_BASE, OLLAMA_TIMEOUT, ANALYSIS_MODEL, SQL_MODEL, RESPONSE_MODEL
from log import get_logger

logger = get_logger("fileorganizer.ollama")

# All models the application uses, in priority order (de-duplicated)
REQUIRED_MODELS: list[str] = list(dict.fromkeys([SQL_MODEL, RESPONSE_MODEL, ANALYSIS_MODEL]))


def call_ollama(
    model: str,
    prompt: str,
    timeout: int | None = None,
    fmt: str | dict | None = None,
) -> str:
    """POST to /generate and return the model response.

    Parameters
    ----------
    fmt : str | dict | None
        Passed as ``"format"`` in the Ollama payload.
        Use ``"json"`` to force valid JSON output, or a JSON Schema dict to
        constrain the output structure (Ollama ≥ Dec-2024).
        When None (default) the response is treated as plain text and
        <think>…</think> blocks are stripped (qwen3 models in chat mode).

    Raises RuntimeError("ollama_not_running") if the server is unreachable.
    Raises RuntimeError("model_not_found") if the model isn't installed.
    Returns '' on all other soft errors.
    """
    if timeout is None:
        timeout = OLLAMA_TIMEOUT
    payload: dict = {"model": model, "prompt": prompt, "stream": False}
    if fmt is not None:
        payload["format"] = fmt
    t0 = time.monotonic()
    try:
        resp = requests.post(f"{OLLAMA_BASE}/generate", json=payload, timeout=timeout)
        resp.raise_for_status()
        elapsed = time.monotonic() - t0
        raw = resp.json().get("response", "").strip()
        if fmt is None:
            # Strip reasoning blocks emitted by some qwen3 models (text mode only;
            # format=json prevents them and stripping would corrupt the JSON).
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        logger.debug("ollama_call | model=%s | %.2fs | resp=%s", model, elapsed, raw[:200])
        return raw
    except requests.exceptions.ConnectionError:
        raise RuntimeError("ollama_not_running")
    except Exception as exc:
        msg = str(exc).lower()
        if "model" in msg and ("not found" in msg or "pull" in msg):
            raise RuntimeError("model_not_found")
        logger.warning("ollama_call | model=%s | %.2fs | %s", model, time.monotonic() - t0, exc)
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
