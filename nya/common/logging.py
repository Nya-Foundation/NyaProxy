"""
One logging configuration for the whole process.

Everything logs through the standard library — NyaProxy, Uvicorn, Starlette,
watchfiles, httpx, and nacho — so a single root handler gives every line the
same shape without any bridging between logging frameworks.

The format deliberately stops at the logger name:

    2026-07-19 23:08:44.076 | INFO     | nya.server.app - Setting up routes
    2026-07-19 23:08:50.770 | INFO     | uvicorn.access - 127.0.0.1 - "GET /health" 200

The emitting module, function, and line are omitted: the name already says
which subsystem spoke, and anything worth locating precisely arrives with a
traceback that carries the exact position.
"""

import logging
import logging.handlers
import os
import sys
from typing import Optional

#: Shared line format. ``levelcolor`` is filled in by the formatter so the
#: level can be padded before any escape codes are added.
LOG_FORMAT = "%(asctime)s.%(msecs)03d | %(levelcolor)s | %(name)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Size-based rotation, matching what the configuration documents.
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5

_RESET = "\033[0m"
_LEVEL_COLORS = {
    "DEBUG": "\033[36m",  # cyan
    "INFO": "\033[32m",  # green
    "WARNING": "\033[33m",  # yellow
    "ERROR": "\033[31m",  # red
    "CRITICAL": "\033[1;31m",  # bold red
}

#: Third-party loggers that install handlers or pin levels of their own.
_MANAGED_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "uvicorn.asgi",
    "fastapi",
    "starlette",
    "watchfiles",
    "watchfiles.main",
    "httpx",
    "httpcore",
    "nacho",
)


class Formatter(logging.Formatter):
    """Shared formatter, optionally colouring the level for a terminal."""

    def __init__(self, *, color: bool = False) -> None:
        super().__init__(LOG_FORMAT, datefmt=DATE_FORMAT)
        self.color = color

    def format(self, record: logging.LogRecord) -> str:
        # Pad first, then colour: escape codes count towards a %-width and
        # would otherwise break the column alignment.
        level = f"{record.levelname:<8}"
        if self.color:
            level = f"{_LEVEL_COLORS.get(record.levelname, '')}{level}{_RESET}"
        record.levelcolor = level
        return super().format(record)


def _supports_color(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def configure_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    enabled: bool = True,
) -> None:
    """
    Install the shared configuration. Safe to call more than once.

    Called at import so Uvicorn's startup lines are covered, and again once
    the configuration file has been read.
    """
    normalized = (level or "INFO").upper()
    root = logging.getLogger()

    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()

    if not enabled:
        root.addHandler(logging.NullHandler())
        root.setLevel(logging.CRITICAL + 1)
        _reset_managed_loggers()
        return

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(Formatter(color=_supports_color(sys.stderr)))
    root.addHandler(stream)

    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(Formatter(color=False))
        root.addHandler(file_handler)

    root.setLevel(logging.getLevelName(normalized))
    _reset_managed_loggers()


def _reset_managed_loggers() -> None:
    """
    Hand the managed loggers back to the root configuration.

    Uvicorn attaches its own handlers and pins an explicit level (that is what
    --log-level does). An explicit level beats the root's, so leaving one in
    place would silently override the level from the configuration file.
    """
    for name in _MANAGED_LOGGERS:
        std_logger = logging.getLogger(name)
        for handler in std_logger.handlers[:]:
            std_logger.removeHandler(handler)
        std_logger.propagate = True
        std_logger.setLevel(logging.NOTSET)
