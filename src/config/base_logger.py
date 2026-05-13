"""Base logger configuration for the application."""

import inspect
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Rotate when app.log reaches this size (10 MB)
LOG_MAX_BYTES = 10 * 1024 * 1024
# Keep this many rotated backup files
LOG_BACKUP_COUNT = 5

# Dictionary to track which loggers have been configured
configured_loggers = set()


def get_logger():
    """Get a logger instance for the current file.

    Returns:
        logging.Logger: Configured logger instance
    """
    frame = inspect.currentframe().f_back
    module = inspect.getmodule(frame)
    file_name = os.path.basename(module.__file__).replace(".py", "")

    # Create logger with the caller's file name
    logger = logging.getLogger(file_name)
    logger.setLevel(logging.DEBUG)

    # Only configure if not already done
    if file_name not in configured_loggers:
        # Create logs directory if it doesn't exist
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # Clear any existing handlers (prevent duplicate handlers in reload scenarios)
        logger.handlers.clear()

        # Create console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # Create rotating file handler to prevent unbounded growth
        file_handler = RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)

        # Create formatter
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)

        # Add handlers to logger
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

        # Mark this logger as configured
        configured_loggers.add(file_name)

    return logger
