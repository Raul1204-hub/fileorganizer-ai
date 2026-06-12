"""Shared pytest fixtures and markers."""

import pytest
import requests


def _ollama_available() -> bool:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


# Apply this marker to any test that requires a running Ollama server.
# Tests decorated with @requires_ollama skip automatically in CI.
requires_ollama = pytest.mark.skipif(
    not _ollama_available(),
    reason="Ollama server not available at localhost:11434",
)
