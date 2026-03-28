"""Unit tests for IconManager."""

from pathlib import Path
from unittest.mock import patch

import pytest

from twingate_tray.client import ConnectionState
from twingate_tray.icons import IconManager


@pytest.fixture
def icons_dir(tmp_path: Path) -> Path:
    """Create a temp directory with dummy SVG files."""
    for name in ("connected.svg", "disconnected.svg", "connecting.svg", "paused.svg"):
        (tmp_path / name).write_text("<svg></svg>", encoding="utf-8")
    return tmp_path


class TestIconManager:
    """Tests for IconManager."""

    @patch("twingate_tray.icons.QIcon")
    def test_get_icon_for_each_state(self, mock_qicon: object, icons_dir: Path) -> None:
        mgr = IconManager(icons_dir=icons_dir)
        for state in ConnectionState:
            icon = mgr.get_icon(state)
            assert icon is not None

    @patch("twingate_tray.icons.QIcon")
    def test_caches_icons(self, mock_qicon: object, icons_dir: Path) -> None:
        mgr = IconManager(icons_dir=icons_dir)
        icon1 = mgr.get_icon(ConnectionState.ONLINE)
        icon2 = mgr.get_icon(ConnectionState.ONLINE)
        assert icon1 is icon2

    @patch("twingate_tray.icons.QIcon")
    def test_missing_icon_file(self, mock_qicon: object, tmp_path: Path) -> None:
        """Empty directory — should log warning and return a fallback QIcon."""
        mgr = IconManager(icons_dir=tmp_path)
        icon = mgr.get_icon(ConnectionState.ONLINE)
        assert icon is not None
