"""
One logging configuration for the whole process.

NyaProxy logs through loguru while Uvicorn, Starlette, and watchfiles log
through the standard library, so a running gateway emitted two different
formats interleaved:

    2026-07-18 19:10:01.938 | INFO     | nya.server.app:trigger_reload:536 - ...
    INFO:     172.17.0.1:44650 - "GET /api/novelai/... HTTP/1.0" 200 OK

The second form carries no timestamp and no logger name, which makes the two
impossible to correlate and awkward to parse. Routing the standard library
through loguru gives every line the same shape, timestamps included.
"""

import logging
import sys
from typing import Optional

from loguru import logger

#: Shared line format. Kept identical to loguru's default so NyaProxy's own
#: output is unchanged and only the standard-library loggers move to match it.
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

#: Third-party loggers that install handlers of their own. Their handlers are
#: removed so records reach the root interceptor exactly once.
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


class InterceptHandler(logging.Handler):
    """Forward standard-library records to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            # A numeric or custom level with no loguru equivalent.
            level = record.levelno

        # Take the origin from the record itself. Letting loguru infer it by
        # walking frames reports logging's own internals
        # ("logging:callHandlers:1736"), and the record already carries the
        # logger name — "uvicorn.access" is far more useful for correlation
        # than whichever Uvicorn module happened to emit the line.
        patched = logger.patch(
            lambda r: r.update(
                name=record.name,
                function=record.funcName,
                line=record.lineno,
            )
        )
        patched.opt(exception=record.exc_info).log(level, record.getMessage())


def configure_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    enabled: bool = True,
) -> None:
    """
    Install the shared configuration. Safe to call more than once.

    Called at import time so Uvicorn's own startup lines are formatted, and
    again once the configuration file has been read.
    """
    normalized = (level or "INFO").upper()

    logger.remove()

    if not enabled:
        # Silence loguru and keep the standard library from falling back to
        # its own basicConfig output.
        logging.basicConfig(handlers=[logging.NullHandler()], level=0, force=True)
        for name in _MANAGED_LOGGERS:
            logging.getLogger(name).handlers = []
        return

    logger.add(sys.stderr, level=normalized, format=LOG_FORMAT)
    if log_file:
        logger.add(
            log_file,
            level=normalized,
            format=LOG_FORMAT,
            rotation="10 MB",
            retention=5,
        )

    # Filter at the standard-library boundary too, so a quiet level also
    # quietens third-party libraries instead of forwarding everything and
    # dropping it at the sink.
    logging.basicConfig(
        handlers=[InterceptHandler()],
        level=logging.getLevelName(normalized),
        force=True,
    )

    for name in _MANAGED_LOGGERS:
        std_logger = logging.getLogger(name)
        std_logger.handlers = []
        std_logger.propagate = True
        # Reset to NOTSET so the level configured here is the one that
        # applies. Uvicorn sets an explicit level on these loggers (its
        # --log-level does exactly that), and an explicit level wins over the
        # root's — leaving it in place would silently override the
        # configuration file.
        std_logger.setLevel(logging.NOTSET)
