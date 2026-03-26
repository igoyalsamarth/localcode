"""Tests for CLI entrypoint."""

from unittest.mock import patch

import pytest


@pytest.mark.unit
def test_main_invokes_uvicorn():
    with patch("main.uvicorn.run") as mock_run:
        from main import main

        main()
    mock_run.assert_called_once_with(
        "app:app",
        host="0.0.0.0",
        port=8000,
    )
