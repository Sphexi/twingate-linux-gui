"""QApplication setup with single-instance guard for twingate-tray."""

import argparse
import logging
import signal
import subprocess
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QLocalServer
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from twingate_tray import __version__
from twingate_tray.client import TwingateClient
from twingate_tray.config import ConfigManager
from twingate_tray.icons import IconManager
from twingate_tray.poller import StatusPoller
from twingate_tray.tray import TwingateSystemTray

logger = logging.getLogger(__name__)

LOCK_NAME = "twingate-tray-single-instance"
APP_NAME = "twingate-tray"


class SingleInstanceGuard:
    """Prevents multiple instances using QLocalServer (works cross-platform)."""

    def __init__(self, name: str = LOCK_NAME) -> None:
        self._name = name
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        """Try to acquire the single-instance lock. Returns True if successful."""
        self._server = QLocalServer()
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if self._server.listen(self._name):
            return True
        # Previous instance may have crashed — remove stale socket and retry
        QLocalServer.removeServer(self._name)
        if self._server.listen(self._name):
            return True
        logger.warning("Another instance of %s is already running.", APP_NAME)
        self._server = None
        return False

    def release(self) -> None:
        """Release the single-instance lock."""
        if self._server is not None:
            self._server.close()
            self._server = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="System tray application for the Twingate Linux CLI",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser.parse_args(argv)


def _start_desktop_notifications() -> None:
    """Launch ``twingate desktop-start`` in the background (non-blocking)."""
    try:
        subprocess.Popen(
            ["/usr/bin/twingate", "desktop-start", "-d"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        logger.warning("twingate binary not found — desktop notifications unavailable")
    except OSError as exc:
        logger.warning("Failed to start desktop notifications: %s", exc)


def run(argv: list[str] | None = None) -> int:
    """Initialize and run the twingate-tray application."""
    parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)

    # Allow Ctrl+C to terminate the app.
    # The periodic timer gives Python a chance to process signals
    # while the Qt event loop is running.
    signal.signal(signal.SIGINT, lambda *_args: QApplication.quit())
    signal.signal(signal.SIGTERM, lambda *_args: QApplication.quit())
    signal_timer = QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(200)

    guard = SingleInstanceGuard()
    if not guard.acquire():
        logger.error("Another instance is already running. Exiting.")
        return 1

    tray: TwingateSystemTray | None = None
    poller: StatusPoller | None = None

    try:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.error("System tray is not available on this desktop environment.")
            return 1

        # Core components
        client = TwingateClient()
        config_manager = ConfigManager()
        icon_manager = IconManager()
        poller = StatusPoller(
            client=client,
            interval_ms=config_manager.config.poll_interval * 1000,
        )

        # Start desktop notification feed (non-blocking)
        _start_desktop_notifications()

        # System tray
        tray = TwingateSystemTray(
            client=client,
            poller=poller,
            config_manager=config_manager,
            icon_manager=icon_manager,
        )
        tray.show()

        # Begin polling
        poller.start()

        logger.info("twingate-tray %s started.", __version__)
        return app.exec()
    finally:
        if tray is not None:
            tray.cleanup()
        if poller is not None:
            poller.stop()
        guard.release()
