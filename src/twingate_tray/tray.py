"""TwingateSystemTray — QSystemTrayIcon with context menu and signals."""

import html
import logging
import shutil
from functools import partial
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from twingate_tray import __version__
from twingate_tray.client import (
    CommandResult,
    ConnectionState,
    TwingateClient,
    TwingateStatus,
)
from twingate_tray.config import ConfigManager
from twingate_tray.icons import IconManager
from twingate_tray.poller import StatusPoller

logger = logging.getLogger(__name__)

MAX_NOTIFICATION_LEN = 200

_STATE_LABELS: dict[ConnectionState, str] = {
    ConnectionState.ONLINE: "Connected",
    ConnectionState.OFFLINE: "Disconnected",
    ConnectionState.CONNECTING: "Connecting\u2026",
    ConnectionState.PAUSED: "Paused",
    ConnectionState.UNKNOWN: "Unknown",
}

AUTOSTART_DIR = Path.home() / ".config" / "autostart"
DESKTOP_FILE_NAME = "twingate-tray.desktop"


def _add_action(menu: QMenu, label: str) -> QAction:
    """Add an action to a menu, raising on failure."""
    action = menu.addAction(label)
    if action is None:
        raise RuntimeError(f"Failed to create QAction: {label}")
    return action


def _add_submenu(menu: QMenu, label: str) -> QMenu:
    """Add a submenu to a menu, raising on failure."""
    submenu = menu.addMenu(label)
    if submenu is None:
        raise RuntimeError(f"Failed to create submenu: {label}")
    return submenu


# ------------------------------------------------------------------
# Background command worker
# ------------------------------------------------------------------


_ALLOWED_METHODS = frozenset({
    "start", "stop", "connect", "disconnect", "auth", "account_add",
    "account_switch", "account_logout", "exit_node_start", "exit_node_stop",
    "exit_node_switch", "exit_node_list", "desktop_start", "version",
})


class CommandWorker(QObject):
    """Runs blocking TwingateClient commands off the main thread."""

    finished = pyqtSignal(str, object)  # (command_name, result)

    def __init__(self, client: TwingateClient) -> None:
        super().__init__()
        self._client = client

    def run_command(
        self, name: str, method_name: str, args: tuple[Any, ...] = ()
    ) -> None:
        """Execute a client method and emit the result."""
        if method_name not in _ALLOWED_METHODS:
            logger.error("Blocked disallowed method: %s", method_name)
            return
        method = getattr(self._client, method_name)
        result = method(*args)
        self.finished.emit(name, result)


class TwingateSystemTray(QSystemTrayIcon):
    """System tray icon with a dynamic context menu for Twingate management."""

    def __init__(
        self,
        client: TwingateClient,
        poller: StatusPoller,
        config_manager: ConfigManager,
        icon_manager: IconManager,
        parent: QApplication | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._poller = poller
        self._config = config_manager
        self._icons = icon_manager

        # Submenu references (set in _build_menu)
        self._resources_menu: QMenu | None = None
        self._accounts_menu: QMenu | None = None
        self._exit_nodes_menu: QMenu | None = None

        # Current state (used to drive menu layout)
        self._current_status = TwingateStatus(state=ConnectionState.UNKNOWN)
        self._is_first_poll = True

        # Background command thread
        self._cmd_worker = CommandWorker(client)
        self._cmd_thread = QThread()
        self._cmd_worker.moveToThread(self._cmd_thread)
        self._cmd_worker.finished.connect(self._on_command_finished)
        self._cmd_thread.start()

        # Set initial icon
        self.setIcon(self._icons.get_icon(ConnectionState.UNKNOWN))
        self.setToolTip("twingate-tray \u2014 Unknown")

        # Build menu & wire signals
        self._build_menu()
        self._poller.status_changed.connect(self._on_status_changed)

    def cleanup(self) -> None:
        """Stop the background command thread."""
        self._cmd_thread.quit()
        self._cmd_thread.wait(5000)

    # ------------------------------------------------------------------
    # Async command dispatch
    # ------------------------------------------------------------------

    def _run_async(
        self,
        name: str,
        method_name: str,
        args: tuple[Any, ...] = (),
    ) -> None:
        """Dispatch a client command to the background thread."""
        QTimer.singleShot(
            0,
            partial(self._cmd_worker.run_command, name, method_name, args),
        )

    def _on_command_finished(self, name: str, result: object) -> None:
        """Handle command completion on the main thread."""
        if isinstance(result, CommandResult) and not result.success:
            # Truncate stderr to prevent excessively long notifications
            stderr = result.stderr[:MAX_NOTIFICATION_LEN]
            self._warn(f"{name} failed: {stderr}")
        self._poller.force_poll()

    # ------------------------------------------------------------------
    # Menu construction
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        """Rebuild the entire context menu based on current state."""
        old_menu = self.contextMenu()
        menu = QMenu()
        state = self._current_status.state

        # --- Status line ---
        status_label = _STATE_LABELS.get(state, "Unknown")
        if self._current_status.network:
            status_label += f" \u2014 {self._current_status.network}"
        status_action = _add_action(menu, status_label)
        status_action.setEnabled(False)
        menu.addSeparator()

        # --- Connection actions (vary by state) ---
        if state in (ConnectionState.OFFLINE, ConnectionState.UNKNOWN):
            act = _add_action(menu, "Connect")
            act.triggered.connect(self._on_connect)
        elif state == ConnectionState.ONLINE:
            act = _add_action(menu, "Disconnect")
            act.triggered.connect(self._on_stop)
            act2 = _add_action(menu, "Pause")
            act2.triggered.connect(self._on_disconnect)
        elif state == ConnectionState.PAUSED:
            act = _add_action(menu, "Resume")
            act.triggered.connect(self._on_resume)
            act2 = _add_action(menu, "Disconnect")
            act2.triggered.connect(self._on_stop)
        elif state == ConnectionState.CONNECTING:
            act = _add_action(menu, "Cancel (Disconnect)")
            act.triggered.connect(self._on_stop)

        menu.addSeparator()

        # --- Resources submenu ---
        self._resources_menu = _add_submenu(menu, "Resources")
        self._resources_menu.aboutToShow.connect(
            self._populate_resources_menu
        )

        # --- Accounts submenu ---
        self._accounts_menu = _add_submenu(menu, "Accounts")
        self._accounts_menu.aboutToShow.connect(
            self._populate_accounts_menu
        )

        # --- Exit Nodes submenu ---
        self._exit_nodes_menu = _add_submenu(menu, "Exit Nodes")
        self._exit_nodes_menu.aboutToShow.connect(
            self._populate_exit_nodes_menu
        )

        menu.addSeparator()

        # --- Re-authenticate ---
        reauth = _add_action(menu, "Re-authenticate")
        reauth.triggered.connect(self._on_reauth)

        menu.addSeparator()

        # --- Settings submenu ---
        settings_menu = _add_submenu(menu, "Settings")
        self._build_settings_menu(settings_menu)

        # --- About ---
        about = _add_action(menu, "About")
        about.triggered.connect(self._on_about)

        # --- Quit ---
        quit_act = _add_action(menu, "Quit")
        quit_act.triggered.connect(self._on_quit)

        self.setContextMenu(menu)

        # Clean up old menu to prevent memory leak
        if old_menu is not None:
            old_menu.deleteLater()

    def _build_settings_menu(self, menu: QMenu) -> None:
        """Build the Settings submenu."""
        cfg = self._config.config

        # Poll interval sub-submenu
        poll_menu = _add_submenu(menu, f"Poll interval: {cfg.poll_interval}s")
        for interval in (5, 10, 30, 60):
            action = _add_action(poll_menu, f"{interval}s")
            action.setCheckable(True)
            action.setChecked(cfg.poll_interval == interval)
            action.triggered.connect(
                lambda _checked, i=interval: self._set_poll_interval(i)
            )

        # Autostart toggle
        autostart_action = _add_action(menu, "Autostart")
        autostart_action.setCheckable(True)
        autostart_action.setChecked(cfg.autostart)
        autostart_action.triggered.connect(self._toggle_autostart)

        # Show hidden resources toggle
        hidden_action = _add_action(menu, "Show hidden resources")
        hidden_action.setCheckable(True)
        hidden_action.setChecked(cfg.show_hidden_resources)
        hidden_action.triggered.connect(self._toggle_hidden_resources)

    # ------------------------------------------------------------------
    # Dynamic submenus (populated on open)
    # ------------------------------------------------------------------

    def _populate_resources_menu(self) -> None:
        """Populate the Resources submenu with live data."""
        if self._resources_menu is None:
            return
        self._resources_menu.clear()

        resources = self._client.resources(
            include_hidden=self._config.config.show_hidden_resources
        )
        if not resources:
            act = _add_action(self._resources_menu, "No resources available")
            act.setEnabled(False)
        else:
            for res in resources:
                label = f"{res.name}  ({res.address})"
                act = _add_action(self._resources_menu, label)
                act.triggered.connect(
                    lambda _c, addr=res.address: self._copy_to_clipboard(addr)
                )

        self._resources_menu.addSeparator()
        refresh = _add_action(self._resources_menu, "Refresh")
        refresh.triggered.connect(self._populate_resources_menu)

    def _populate_accounts_menu(self) -> None:
        """Populate the Accounts submenu with live data."""
        if self._accounts_menu is None:
            return
        self._accounts_menu.clear()

        accounts = self._client.account_list()
        if not accounts:
            act = _add_action(self._accounts_menu, "No accounts configured")
            act.setEnabled(False)
        else:
            for acct in accounts:
                act = _add_action(self._accounts_menu, acct.name)
                act.setCheckable(True)
                act.setChecked(acct.is_active)
                if not acct.is_active:
                    act.triggered.connect(
                        lambda _c, a=acct.name: self._switch_account(a)
                    )

        self._accounts_menu.addSeparator()
        add_act = _add_action(self._accounts_menu, "Add Account\u2026")
        add_act.triggered.connect(self._on_account_add)
        logout_act = _add_action(self._accounts_menu, "Logout")
        logout_act.triggered.connect(self._on_account_logout)

    def _populate_exit_nodes_menu(self) -> None:
        """Populate the Exit Nodes submenu with live data."""
        if self._exit_nodes_menu is None:
            return
        self._exit_nodes_menu.clear()

        nodes = self._client.exit_node_list()
        if not nodes:
            act = _add_action(self._exit_nodes_menu, "No exit nodes available")
            act.setEnabled(False)
        else:
            for node in nodes:
                act = _add_action(self._exit_nodes_menu, node.name)
                act.setCheckable(True)
                act.setChecked(node.is_active)
                if not node.is_active:
                    act.triggered.connect(
                        lambda _c, n=node.name: self._switch_exit_node(n)
                    )

            self._exit_nodes_menu.addSeparator()
            enable = _add_action(self._exit_nodes_menu, "Enable Routing")
            enable.triggered.connect(self._on_exit_node_start)
            disable = _add_action(self._exit_nodes_menu, "Disable Routing")
            disable.triggered.connect(self._on_exit_node_stop)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_status_changed(self, status: TwingateStatus) -> None:
        """React to a connection state change from the poller."""
        old_state = self._current_status.state
        self._current_status = status

        # Update icon + tooltip
        self.setIcon(self._icons.get_icon(status.state))
        label = _STATE_LABELS.get(status.state, "Unknown")
        self.setToolTip(f"twingate-tray \u2014 {label}")

        # Rebuild the menu to reflect new connection actions
        self._build_menu()

        # Suppress notification on first poll (app startup)
        if self._is_first_poll:
            self._is_first_poll = False
            return

        # Desktop notification on meaningful transitions
        if old_state != status.state:
            self._notify_state_change(old_state, status)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _warn(self, message: str) -> None:
        """Show a warning notification."""
        self.showMessage(
            "Twingate", message, QSystemTrayIcon.MessageIcon.Warning
        )

    # ------------------------------------------------------------------
    # Connection actions (all async via CommandWorker)
    # ------------------------------------------------------------------

    def _on_connect(self) -> None:
        """Handle Connect / Start."""
        self._run_async("Connect", "start")

    def _on_stop(self) -> None:
        """Handle full Disconnect (stop)."""
        self._run_async("Disconnect", "stop")

    def _on_disconnect(self) -> None:
        """Handle Pause (soft disconnect)."""
        self._run_async("Pause", "disconnect")

    def _on_resume(self) -> None:
        """Handle Resume from paused state."""
        self._run_async("Resume", "connect")

    def _on_reauth(self) -> None:
        """Open browser for re-authentication."""
        self._run_async("Re-authenticate", "auth")

    # ------------------------------------------------------------------
    # Account actions
    # ------------------------------------------------------------------

    def _on_account_add(self) -> None:
        """Trigger account add via pkexec."""
        self._run_async("Add account", "account_add")

    def _on_account_logout(self) -> None:
        """Log out of current account."""
        self._run_async("Logout", "account_logout")

    def _switch_account(self, name: str) -> None:
        """Switch to a different account."""
        self._run_async("Switch account", "account_switch", (name,))

    # ------------------------------------------------------------------
    # Exit node actions
    # ------------------------------------------------------------------

    def _on_exit_node_start(self) -> None:
        """Enable exit node routing."""
        self._run_async("Enable routing", "exit_node_start")

    def _on_exit_node_stop(self) -> None:
        """Disable exit node routing."""
        self._run_async("Disable routing", "exit_node_stop")

    def _switch_exit_node(self, name: str) -> None:
        """Switch to a different exit node."""
        self._run_async("Switch exit node", "exit_node_switch", (name,))

    # ------------------------------------------------------------------
    # Settings actions
    # ------------------------------------------------------------------

    def _set_poll_interval(self, seconds: int) -> None:
        """Update the poll interval in config and live poller."""
        self._config.update(poll_interval=seconds)
        self._poller.interval_ms = seconds * 1000
        self._build_menu()

    def _toggle_autostart(self, checked: bool) -> None:
        """Toggle autostart by managing the .desktop file in autostart dir."""
        self._config.update(autostart=checked)
        autostart_file = AUTOSTART_DIR / DESKTOP_FILE_NAME

        if checked:
            source = Path("/usr/share/applications") / DESKTOP_FILE_NAME
            if not source.exists():
                source = (
                    Path(__file__).parent.parent.parent
                    / "packaging"
                    / DESKTOP_FILE_NAME
                )
            AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
            if source.exists():
                shutil.copy2(str(source), str(autostart_file))
            else:
                logger.warning(
                    "Cannot find %s to enable autostart", DESKTOP_FILE_NAME
                )
                self._warn("Could not find .desktop file for autostart")
        else:
            if autostart_file.exists():
                autostart_file.unlink()

    def _toggle_hidden_resources(self, checked: bool) -> None:
        """Toggle visibility of hidden resources."""
        self._config.update(show_hidden_resources=checked)

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        """Copy text to the system clipboard."""
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _notify_state_change(
        self, old_state: ConnectionState, status: TwingateStatus
    ) -> None:
        """Show a desktop notification for meaningful state transitions."""
        new_label = _STATE_LABELS.get(status.state, "Unknown")
        network_info = f" ({status.network})" if status.network else ""

        if status.state == ConnectionState.ONLINE:
            self.showMessage(
                "Twingate",
                f"Connected{network_info}",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
        elif status.state == ConnectionState.OFFLINE:
            self.showMessage(
                "Twingate",
                "Disconnected",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
        elif status.state == ConnectionState.PAUSED:
            self.showMessage(
                "Twingate",
                "Connection paused",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
        elif status.state == ConnectionState.UNKNOWN:
            self.showMessage(
                "Twingate",
                f"Status: {new_label}",
                QSystemTrayIcon.MessageIcon.Warning,
                3000,
            )

    # ------------------------------------------------------------------
    # About & Quit
    # ------------------------------------------------------------------

    def _on_about(self) -> None:
        """Show the About dialog."""
        tg_version = html.escape(self._client.version())
        QMessageBox.about(
            None,
            "About twingate-tray",
            f"<b>twingate-tray</b> v{html.escape(__version__)}<br><br>"
            f"Twingate CLI: {tg_version}<br><br>"
            "System tray application for the Twingate Linux CLI.<br>"
            '<a href="https://github.com/benyanke/twingate-linux-gui">'
            "GitHub Repository</a><br><br>"
            "License: MIT",
        )

    @staticmethod
    def _on_quit() -> None:
        """Quit the application."""
        QApplication.quit()
