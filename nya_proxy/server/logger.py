"""
Logger setup and configuration for NyaProxy.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any, Dict


def setup_logger(log_config: Dict[str, Any], name: str = "nya_proxy") -> logging.Logger:
    """
    Set up and configure a logger instance.

    Args:
        log_config: Logging configuration dictionary
        name: Logger name

    Returns:
        Configured logger instance
    """
    # Extract configuration
    enabled = log_config.get("enabled", True)
    log_level_str = log_config.get("level", "INFO").upper()
    log_file = log_config.get("log_file", "app.log")

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

    # Remove existing handlers to avoid duplicate logging
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create console handler for all logs
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Create file handler if enabled
    if enabled and log_file:
        # Ensure directory exists
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
            except Exception as e:
                logger.warning(f"Could not create log directory {log_dir}: {str(e)}")
                # Continue without file logging
                return logger

        try:
            file_handler = RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=5  # 10 MB
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(log_level)
            logger.addHandler(file_handler)
        except Exception as e:
            logger.warning(f"Could not set up file logging to {log_file}: {str(e)}")
            # Continue with console logging only

    return logger
