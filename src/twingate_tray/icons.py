"""Icon loading and state management for tray icons."""

import logging
from pathlib import Path

from PyQt6.QtGui import QIcon

from twingate_tray.client import ConnectionState

logger = logging.getLogger(__name__)

ICONS_DIR = Path(__file__).parent / "resources" / "icons"

# Map connection states to SVG filenames
_STATE_ICON_MAP: dict[ConnectionState, str] = {
    ConnectionState.ONLINE: "connected.svg",
    ConnectionState.OFFLINE: "disconnected.svg",
    ConnectionState.CONNECTING: "connecting.svg",
    ConnectionState.PAUSED: "paused.svg",
    ConnectionState.UNKNOWN: "disconnected.svg",
}


class IconManager:
    """Loads and caches SVG tray icons for each connection state."""

    def __init__(self, icons_dir: Path = ICONS_DIR) -> None:
        self._icons_dir = icons_dir
        self._cache: dict[ConnectionState, QIcon] = {}

    def get_icon(self, state: ConnectionState) -> QIcon:
        """Return the QIcon for the given connection state."""
        if state not in self._cache:
            filename = _STATE_ICON_MAP.get(state, "disconnected.svg")
            icon_path = self._icons_dir / filename
            if icon_path.exists():
                self._cache[state] = QIcon(str(icon_path))
            else:
                logger.warning("Icon file not found: %s", icon_path)
                self._cache[state] = QIcon()
        return self._cache[state]
