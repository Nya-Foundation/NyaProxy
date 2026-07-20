"""
One log format for the whole process.

Everything — NyaProxy, Uvicorn, Starlette, watchfiles — logs through the
standard library, so a single root handler covers all of it. These tests pin
the parts that are easy to regress: the shared format, the configured level
actually winning, and third-party loggers not smuggling in their own.
"""

import logging
import logging.handlers

import pytest

from nya.common.logging import DATE_FORMAT, LOG_FORMAT, Formatter, configure_logging


@pytest.fixture(autouse=True)
def restore_logging():
    """Leave global logging state as it was found."""
    yield
    configure_logging(level="INFO")


def capture() -> list:
    """
    Attach a capturing handler and return the list it fills.

    Must be called *after* configure_logging: that replaces the root
    handlers, which would otherwise drop this one.
    """
    lines: list = []

    class ListHandler(logging.Handler):
        def emit(self, record):
            lines.append(self.format(record))

    handler = ListHandler()
    handler.setFormatter(Formatter(color=False))
    logging.getLogger().addHandler(handler)
    return lines


def test_third_party_records_share_the_format():
    configure_logging(level="DEBUG")
    captured = capture()

    logging.getLogger("uvicorn.access").info('127.0.0.1 - "GET /health" 200')

    assert len(captured) == 1
    assert "| INFO     | uvicorn.access - " in captured[0]
    assert '"GET /health" 200' in captured[0]


def test_nyaproxy_records_share_the_same_format():
    configure_logging(level="DEBUG")
    captured = capture()

    logging.getLogger("nya.server.app").info("Setting up generic proxy routes")

    assert (
        "| INFO     | nya.server.app - Setting up generic proxy routes" in captured[0]
    )


def test_format_omits_function_and_line():
    """
    The logger name says which subsystem spoke; anything worth locating
    precisely arrives with a traceback that carries the exact position.
    """
    assert "%(name)s" in LOG_FORMAT
    assert "funcName" not in LOG_FORMAT
    assert "lineno" not in LOG_FORMAT
    assert "%(asctime)s" in LOG_FORMAT and "msecs" in LOG_FORMAT
    assert DATE_FORMAT == "%Y-%m-%d %H:%M:%S"


def test_levels_are_rendered_padded():
    configure_logging(level="DEBUG")
    captured = capture()
    std = logging.getLogger("uvicorn.error")

    std.warning("warned")
    std.error("failed")

    assert "| WARNING  |" in captured[0]
    assert "| ERROR    |" in captured[1]


def test_configured_level_also_quietens_third_party_loggers():
    configure_logging(level="WARNING")
    captured = capture()

    logging.getLogger("uvicorn.access").info("chatty access line")
    logging.getLogger("uvicorn.error").warning("real problem")

    assert len(captured) == 1
    assert "real problem" in captured[0]


def test_a_preset_level_on_a_third_party_logger_does_not_win():
    """
    Uvicorn sets an explicit level on its loggers (that is what --log-level
    does), and an explicit level beats the root's. Left in place it would
    silently override the level from the configuration file.
    """
    noisy = logging.getLogger("uvicorn.access")
    noisy.setLevel(logging.WARNING)

    configure_logging(level="DEBUG")
    captured = capture()
    noisy.info("access line that the preset WARNING would have swallowed")

    assert len(captured) == 1
    assert noisy.level == logging.NOTSET


def test_third_party_handlers_are_removed_so_records_are_not_doubled():
    noisy = logging.getLogger("uvicorn.access")
    noisy.addHandler(logging.StreamHandler())

    configure_logging(level="INFO")

    assert noisy.handlers == []
    assert noisy.propagate is True


def test_exception_info_is_rendered():
    configure_logging(level="DEBUG")
    captured = capture()

    try:
        raise ValueError("upstream exploded")
    except ValueError:
        logging.getLogger("nya.core.queue").exception("handler failed")

    assert "handler failed" in captured[0]
    assert "ValueError: upstream exploded" in captured[0]


def test_file_sink_rotates_and_is_not_coloured(tmp_path):
    log_file = tmp_path / "app.log"
    configure_logging(level="INFO", log_file=str(log_file))

    logging.getLogger("nya.server.app").info("written to file")

    handlers = [
        h
        for h in logging.getLogger().handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(handlers) == 1
    assert handlers[0].maxBytes == 10 * 1024 * 1024
    assert handlers[0].backupCount == 5

    contents = log_file.read_text()
    assert "| INFO     | nya.server.app - written to file" in contents
    assert "\033[" not in contents  # never colour a file


def test_repeated_configuration_does_not_duplicate_handlers():
    configure_logging(level="INFO")
    configure_logging(level="INFO")
    configure_logging(level="DEBUG")

    assert len(logging.getLogger().handlers) == 1


def test_disabled_logging_emits_nothing():
    configure_logging(enabled=False)
    captured = capture()

    logging.getLogger("uvicorn.access").info("should not appear")
    logging.getLogger("nya.server.app").error("nor should this")

    assert captured == []


def test_colour_is_applied_only_when_asked():
    record = logging.LogRecord(
        "nya.test", logging.WARNING, __file__, 1, "careful", None, None
    )

    assert "\033[33m" in Formatter(color=True).format(record)
    assert "\033[" not in Formatter(color=False).format(record)
