"""
Logger setup and configuration for NyaProxy.
Provides colored logging output and follows industry best practices.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional

# Import colorlog for colored console output
import colorlog

__all__ = ["get_logger", "setup_console_handler", "setup_file_handler", "getLogger"]

# Dictionary to store logger instances (singleton pattern)
_loggers = {}


def get_logger(
    name: str = "nya_proxy",
    log_config: Dict[str, Any] = {
        "enable": True,
        "level": "INFO",
        "log_file": "app.log",
        "use_colors": True,
        "format": None,
    },
) -> logging.Logger:
    """
    Set up and configure a logger instance using the singleton pattern.

    Args:
        name: Logger name
        log_config: Logging configuration dictionary with the following keys:
            - enabled (bool): Whether file logging is enabled
            - level (str): Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            - log_file (str): Path to the log file
            - use_colors (bool): Whether to use colored output in console (default: True)
            - format (str): Custom log format (optional)


    Returns:
        Configured logger instance
    """
    # Check if logger instance already exists
    if name in _loggers:
        return _loggers[name]

    # Extract configuration with sensible defaults
    enabled = log_config.get("enabled", True)
    log_level_str = log_config.get("level", "INFO").upper()
    log_file = log_config.get("log_file", "app.log")
    use_colors = log_config.get("use_colors", True)
    custom_format = log_config.get("format")

    # Map string log level to logging constant
    log_level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    log_level = log_level_map.get(log_level_str, logging.INFO)

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Prevent log propagation to the root logger
    logger.propagate = False

    # Remove existing handlers to avoid duplicate logging
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Set up console handler with colored output
    setup_console_handler(logger, log_level, use_colors, custom_format)

    # Set up file handler if enabled
    if enabled and log_file:
        setup_file_handler(logger, log_file, log_level, custom_format)

    # Store logger instance in dictionary
    _loggers[name] = logger
    return logger


def setup_console_handler(
    logger: logging.Logger,
    log_level: int,
    use_colors: bool = True,
    custom_format: Optional[str] = None,
) -> None:
    """Set up a console handler with optional colored output."""
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    if use_colors:
        # Colored formatter for console
        log_format = (
            custom_format
            or "%(log_color)s[%(asctime)s] [%(name)s] [%(levelname)s]%(reset)s %(message_log_color)s%(message)s%(reset)s"
        )
        color_formatter = colorlog.ColoredFormatter(
            log_format,
            datefmt="%Y-%m-%d %H:%M:%S",
            reset=True,
            log_colors={
                "DEBUG": "blue",
                "INFO": "green",
                "WARNING": "bold_yellow",
                "ERROR": "bold_red",
                "CRITICAL": "bold_white,bg_red",
            },
            secondary_log_colors={
                "message": {
                    "DEBUG": "cyan",
                    "INFO": "reset",
                    "WARNING": "yellow",
                    "ERROR": "red",
                    "CRITICAL": "bold_red",
                }
            },
            style="%",
        )
        console_handler.setFormatter(color_formatter)
    else:
        # Standard formatter without colors
        log_format = (
            custom_format or "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")
        console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)


def setup_file_handler(
    logger: logging.Logger,
    log_file: str,
    log_level: int,
    custom_format: Optional[str] = None,
) -> None:
    """Set up a rotating file handler for persistent logging."""
    # Ensure directory exists
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create log directory {log_dir}: {str(e)}")
            return

    try:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5  # 10 MB
        )
        log_format = (
            custom_format or "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not set up file logging to {log_file}: {str(e)}")


# For backward compatibility
getLogger = get_logger
