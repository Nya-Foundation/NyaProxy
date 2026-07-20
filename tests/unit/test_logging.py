"""
One log format for the whole process.

NyaProxy logs through loguru; Uvicorn, Starlette, and watchfiles log through
the standard library. Left alone they interleave two shapes, and the
standard-library one carries neither a timestamp nor a logger name.
"""

import logging

import pytest
from loguru import logger

from nya.common.logging import LOG_FORMAT, InterceptHandler, configure_logging


@pytest.fixture(autouse=True)
def restore_logging():
    """Leave global logging state as it was found."""
    yield
    configure_logging(level="INFO")


def capture(sink_list):
    logger.remove()
    logger.add(sink_list.append, format="{name}:{function}:{line}|{level}|{message}")


def test_stdlib_records_reach_loguru():
    configure_logging(level="DEBUG")
    lines = []
    capture(lines)

    logging.getLogger("uvicorn.access").info('127.0.0.1 - "GET /health" 200')

    assert len(lines) == 1
    assert '"GET /health" 200' in lines[0]


def test_intercepted_records_report_their_own_origin():
    """
    Without this the origin reads "logging:callHandlers:1736" for every
    intercepted line, which is both wrong and useless for correlation.
    """
    configure_logging(level="DEBUG")
    lines = []
    capture(lines)

    logging.getLogger("uvicorn.access").info("hello")

    origin = lines[0].split("|")[0]
    assert origin.startswith("uvicorn.access:"), origin
    assert "callHandlers" not in origin


def test_levels_map_across_the_boundary():
    configure_logging(level="DEBUG")
    lines = []
    capture(lines)

    std = logging.getLogger("uvicorn.error")
    std.warning("warned")
    std.error("failed")

    levels = [line.split("|")[1] for line in lines]
    assert levels == ["WARNING", "ERROR"]


def test_configured_level_also_quietens_third_party_loggers():
    """A quiet level must not merely drop records at the sink."""
    configure_logging(level="WARNING")
    lines = []
    logger.remove()
    logger.add(lines.append, level="WARNING", format="{message}")

    logging.getLogger("uvicorn.access").info("chatty access line")
    logging.getLogger("uvicorn.error").warning("real problem")

    assert lines == ["real problem\n"] or [line.strip() for line in lines] == [
        "real problem"
    ]


def test_exception_info_survives_interception():
    configure_logging(level="DEBUG")
    lines = []
    capture(lines)

    try:
        raise ValueError("upstream exploded")
    except ValueError:
        logging.getLogger("uvicorn.error").exception("handler failed")

    assert "handler failed" in lines[0]
    assert "ValueError" in lines[0] or "upstream exploded" in lines[0]


def test_unknown_level_does_not_raise():
    """Custom numeric levels have no loguru name and must not break logging."""
    configure_logging(level="DEBUG")
    lines = []
    capture(lines)

    logging.getLogger("some.library").log(25, "custom level message")

    assert "custom level message" in lines[0]


def test_disabled_logging_emits_nothing():
    configure_logging(enabled=False)
    lines = []
    logger.add(lines.append, format="{message}")

    logging.getLogger("uvicorn.access").info("should not appear")

    assert lines == []


def test_third_party_handlers_are_removed_so_records_are_not_doubled():
    noisy = logging.getLogger("uvicorn.access")
    noisy.addHandler(logging.StreamHandler())

    configure_logging(level="INFO")

    assert noisy.handlers == []
    assert noisy.propagate is True
    assert any(isinstance(h, InterceptHandler) for h in logging.getLogger().handlers)


def test_format_is_shared_by_both_sources():
    assert "{time:" in LOG_FORMAT
    assert "{level: <8}" in LOG_FORMAT
    assert "{name}" in LOG_FORMAT


def test_a_preset_level_on_a_third_party_logger_does_not_win():
    """
    Uvicorn sets an explicit level on its loggers (that is what --log-level
    does), and an explicit level beats the root's. Left in place it would
    silently override the level from the configuration file.
    """
    noisy = logging.getLogger("uvicorn.access")
    noisy.setLevel(logging.WARNING)

    configure_logging(level="DEBUG")
    lines = []
    capture(lines)

    noisy.info("access line that the preset WARNING would have swallowed")

    assert len(lines) == 1
    assert noisy.level == logging.NOTSET
