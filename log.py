"""Logging configuration for FileOrganizer AI.

Call setup_logging() once at application startup (web/app.py or main.py).
All other modules call get_logger("fileorganizer.<module>") at module level.
"""

import logging
import logging.handlers
from pathlib import Path

_LOG_DIR = Path(__file__).parent / "logs"
_LOG_FILE = _LOG_DIR / "fileorganizer.log"

_CONSOLE_FMT = "%(levelname)-8s %(name)s: %(message)s"
_FILE_FMT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FMT = "%Y-%m-%dT%H:%M:%S"


def setup_logging() -> logging.Logger:
    """Configure the 'fileorganizer' logger. Idempotent — safe to call twice."""
    root = logging.getLogger("fileorganizer")
    if root.handlers:
        return root
    root.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(_CONSOLE_FMT))
    root.addHandler(ch)

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_FILE_FMT, datefmt=_DATE_FMT))
    root.addHandler(fh)
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
