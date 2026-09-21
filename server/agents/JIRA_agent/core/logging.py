"""Logging utilities for the application."""
import logging
from datetime import datetime
from typing import Optional


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_info(message: str, module: str = "app") -> None:
    logger = get_logger(module)
    logger.info(message)


def log_error(message: str, module: str = "app", exc: Optional[Exception] = None) -> None:
    logger = get_logger(module)
    if exc:
        logger.error(f"{message}: {exc}", exc_info=True)
    else:
        logger.error(message)


def log_debug(message: str, module: str = "app") -> None:
    logger = get_logger(module)
    logger.debug(message)


def log_warning(message: str, module: str = "app") -> None:
    logger = get_logger(module)
    logger.warning(message)
