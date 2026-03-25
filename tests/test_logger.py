"""Tests for logger module."""

import logging
import pytest
from unittest.mock import patch

from logger import get_logger, configure_logging, _configured


@pytest.mark.unit
class TestLogger:
    """Test logging configuration."""

    def test_get_logger_returns_logger(self):
        """Test get_logger returns a logger instance."""
        logger = get_logger("test")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test"

    def test_get_logger_configures_automatically(self):
        """Test get_logger configures logging automatically."""
        logger = get_logger("test_auto")
        assert isinstance(logger, logging.Logger)

    def test_configure_logging_default_level(self):
        """Test configure_logging with default level."""
        import logger as logger_module
        logger_module._configured = False
        with patch.dict("os.environ", {"LOG_LEVEL": "WARNING"}, clear=False):
            configure_logging()
            root_logger = logging.getLogger()
            assert root_logger.level == logging.WARNING

    def test_configure_logging_custom_level(self):
        """Test configure_logging with custom level."""
        import logger as logger_module
        logger_module._configured = False
        configure_logging(level="ERROR")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.ERROR

    def test_logger_has_handlers(self):
        """Test logger has configured handlers."""
        logger = get_logger("test_handlers")
        root_logger = logging.getLogger()
        assert len(root_logger.handlers) > 0

    def test_logger_format(self):
        """Test logger uses correct format."""
        logger = get_logger("test_format")
        root_logger = logging.getLogger()
        handler = root_logger.handlers[0]
        formatter = handler.formatter
        assert formatter is not None
        assert "%(asctime)s" in formatter._fmt
        assert "%(name)s" in formatter._fmt
        assert "%(levelname)s" in formatter._fmt
        assert "%(message)s" in formatter._fmt
