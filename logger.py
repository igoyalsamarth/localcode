"""
Centralized logging configuration for LocalCode.

Usage:
    from logger import get_logger
    
    logger = get_logger(__name__)
    logger.info("Message here")
"""

import logging
import sys
from typing import Optional

from constants import get_log_level as _get_log_level


_configured = False


def configure_logging(level: Optional[str] = None) -> None:
    """
    Configure the root logger with consistent formatting.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
               Defaults to LOG_LEVEL env var or INFO.
    """
    global _configured
    
    if _configured:
        return
    
    log_level = level or _get_log_level()
    
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ],
        force=True,
    )
    
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.
    
    Automatically configures logging on first call.
    
    Args:
        name: Logger name (typically __name__ of the module)
    
    Returns:
        Configured logger instance
    """
    if not _configured:
        configure_logging()
    
    return logging.getLogger(name)


__all__ = ["get_logger", "configure_logging"]
