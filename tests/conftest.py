"""Shared test fixtures for twingate-tray tests."""

from unittest.mock import MagicMock, patch

import pytest

from twingate_tray.client import CommandResult, TwingateClient


@pytest.fixture
def client() -> TwingateClient:
    """Return a TwingateClient instance."""
    return TwingateClient()


@pytest.fixture
def mock_subprocess() -> MagicMock:
    """Provide a mocked subprocess.run for CLI tests."""
    with patch("twingate_tray.client.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr=""
        )
        yield mock_run


@pytest.fixture
def success_result() -> CommandResult:
    """Return a successful CommandResult."""
    return CommandResult(success=True, stdout="", stderr="", returncode=0)


@pytest.fixture
def failure_result() -> CommandResult:
    """Return a failed CommandResult."""
    return CommandResult(success=False, stdout="", stderr="error", returncode=1)
