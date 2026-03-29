"""TwingateSystemTray — QSystemTrayIcon with context menu and signals."""

import html
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

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

# Terminal emulators to try, in preference order.
# Each entry is (binary, args-to-run-a-command).
_TERMINAL_EMULATORS: list[tuple[str, list[str]]] = [
    ("x-terminal-emulator", ["-e"]),  # Debian/Ubuntu default
    ("xfce4-terminal", ["-e"]),
    ("gnome-terminal", ["--"]),
    ("konsole", ["-e"]),
    ("mate-terminal", ["-e"]),
    ("xterm", ["-e"]),
]


def _find_terminal() -> tuple[str, list[str]] | None:
    """Find an available terminal emulator on the system."""
    for binary, args in _TERMINAL_EMULATORS:
        if shutil.which(binary):
            return binary, args
    return None


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
    "start", "stop", "connect", "disconnect", "auth",
    "account_logout", "exit_node_start", "exit_node_stop",
    "exit_node_switch", "exit_node_list", "desktop_start", "version",
})


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

        # Menu references (prevent Python GC from destroying Qt objects)
        self._menu: QMenu | None = None
        self._resources_menu: QMenu | None = None
        self._accounts_menu: QMenu | None = None
        self._exit_nodes_menu: QMenu | None = None

        # Current state (used to drive menu layout)
        self._current_status = TwingateStatus(state=ConnectionState.UNKNOWN)
        self._is_first_poll = True

        # Set initial icon
        self.setIcon(self._icons.get_icon(ConnectionState.UNKNOWN))
        self.setToolTip("twingate-tray \u2014 Unknown")

        # Build menu & wire signals
        self._build_menu()
        self._poller.status_changed.connect(self._on_status_changed)

    def cleanup(self) -> None:
        """No-op — no background threads to clean up."""

    # ------------------------------------------------------------------
    # Async command dispatch
    # ------------------------------------------------------------------

    def _run_command(
        self,
        name: str,
        method_name: str,
        args: tuple[Any, ...] = (),
    ) -> None:
        """Run a client command, update the menu, and trigger a poll."""
        if method_name not in _ALLOWED_METHODS:
            logger.error("Blocked disallowed method: %s", method_name)
            return
        logger.info("Running command: %s (method=%s, args=%s)", name, method_name, args)

        try:
            method = getattr(self._client, method_name)
            result = method(*args)
        except Exception:
            logger.exception("Command exception in %s", name)
            result = CommandResult(False, "", "internal error", -1)

        logger.info("Command result: %s -> %s", name, result)
        if isinstance(result, CommandResult) and not result.success:
            stderr = result.stderr[:MAX_NOTIFICATION_LEN]
            self._warn(f"{name} failed: {stderr}")

        logger.info("Rebuilding menu after command: %s", name)
        self._build_menu()
        logger.info("Menu rebuilt, forcing poll")
        self._poller.force_poll()

    # ------------------------------------------------------------------
    # Menu construction
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        """Rebuild the context menu by clearing and repopulating in place."""
        logger.info("_build_menu called (state=%s)", self._current_status.state)
        state = self._current_status.state

        # Reuse existing menu or create one on first call
        if self._menu is None:
            self._menu = QMenu()
            self.setContextMenu(self._menu)
            logger.info("_build_menu: created new QMenu (id=%s)", id(self._menu))
        else:
            self._menu.clear()
            logger.info("_build_menu: cleared existing QMenu (id=%s)", id(self._menu))

        menu = self._menu

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
            logger.info("_build_menu: wired Connect action")
        elif state == ConnectionState.ONLINE:
            act = _add_action(menu, "Disconnect")
            act.triggered.connect(self._on_stop)
            logger.info("_build_menu: wired Disconnect action")
        elif state == ConnectionState.CONNECTING:
            act = _add_action(menu, "Cancel (Disconnect)")
            act.triggered.connect(self._on_stop)
            logger.info("_build_menu: wired Cancel action")

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

        # --- Settings submenu ---
        settings_menu = _add_submenu(menu, "Settings")
        self._build_settings_menu(settings_menu)

        # --- About ---
        about = _add_action(menu, "About")
        about.triggered.connect(self._on_about)

        # --- Quit ---
        quit_act = _add_action(menu, "Quit")
        quit_act.triggered.connect(self._on_quit)

        actions = [a.text() for a in menu.actions() if not a.isSeparator()]
        logger.info("_build_menu complete: actions=%s (menu id=%s)", actions, id(menu))

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
        logger.info("Populating resources menu")

        resources = self._client.resources(
            include_hidden=self._config.config.show_hidden_resources
        )
        logger.info("Resources fetched: %d items", len(resources))
        if not resources:
            act = _add_action(self._resources_menu, "No resources available")
            act.setEnabled(False)
        else:
            for res in resources:
                label = f"{res.name} ({res.address})"
                if res.needs_auth:
                    # Resource needs authentication — submenu with copy + auth
                    res_menu = _add_submenu(self._resources_menu, label)
                    copy_act = _add_action(res_menu, "Copy address")
                    copy_act.triggered.connect(
                        lambda _c, a=res.address: self._copy_to_clipboard(a)
                    )
                    auth_act = _add_action(res_menu, "Re-authenticate")
                    auth_act.triggered.connect(
                        lambda _c, r=res.name: self._on_resource_auth(r)
                    )
                else:
                    act = _add_action(self._resources_menu, label)
                    act.triggered.connect(
                        lambda _c, a=res.address: self._copy_to_clipboard(a)
                    )

        self._resources_menu.addSeparator()
        refresh = _add_action(self._resources_menu, "Refresh")
        refresh.triggered.connect(self._populate_resources_menu)

    def _populate_accounts_menu(self) -> None:
        """Populate the Accounts submenu with live data."""
        if self._accounts_menu is None:
            return
        self._accounts_menu.clear()
        logger.info("Populating accounts menu")

        accounts = self._client.account_list()
        logger.info("Accounts fetched: %d items", len(accounts))
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
                        lambda _c, a=acct.switch_id: self._switch_account(a)
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
        logger.info("Populating exit nodes menu")

        nodes = self._client.exit_node_list()
        logger.info("Exit nodes fetched: %d items", len(nodes))
        for node in nodes:
            logger.info("  node: name=%r cli=%r active=%s",
                        node.name, node.cli_name, node.is_active)
        if not nodes:
            act = _add_action(self._exit_nodes_menu, "No exit nodes available")
            act.setEnabled(False)
        else:
            has_active = any(n.is_active for n in nodes)
            for node in nodes:
                act = _add_action(self._exit_nodes_menu, node.name)
                act.setCheckable(True)
                act.setChecked(node.is_active)
                if node.is_active:
                    # Clicking active node disables routing
                    act.triggered.connect(self._on_exit_node_stop)
                elif has_active:
                    # Another node is active — switch to this one
                    act.triggered.connect(
                        lambda _c, n=node.cli_name: self._switch_exit_node(n)
                    )
                else:
                    # No node active — start this one
                    act.triggered.connect(
                        lambda _c, n=node.cli_name: self._start_exit_node(n)
                    )

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_status_changed(self, status: TwingateStatus) -> None:
        """React to a status update from the poller (fires on every poll)."""
        old_state = self._current_status.state
        state_changed = old_state != status.state
        self._current_status = status

        # Always update icon + tooltip
        self.setIcon(self._icons.get_icon(status.state))
        label = _STATE_LABELS.get(status.state, "Unknown")
        self.setToolTip(f"twingate-tray \u2014 {label}")

        # Only rebuild the full menu on state changes
        if state_changed:
            logger.info("State changed: %s -> %s, rebuilding menu", old_state, status.state)
            self._build_menu()

            # Suppress notification on first poll (app startup)
            if self._is_first_poll:
                self._is_first_poll = False
                return

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
    # Connection actions
    # ------------------------------------------------------------------

    def _on_connect(self) -> None:
        """Handle Connect / Start."""
        logger.info("Action triggered: Connect")
        self._run_command("Connect", "start")

    def _on_stop(self) -> None:
        """Handle full Disconnect (stop)."""
        logger.info("Action triggered: Disconnect")
        self._run_command("Disconnect", "stop")

    def _on_resource_auth(self, resource_name: str) -> None:
        """Trigger browser-based re-authentication for a specific resource."""
        logger.info("Action triggered: Re-authenticate resource %r", resource_name)
        self._run_command("Re-authenticate", "auth", (resource_name,))

    # ------------------------------------------------------------------
    # Account actions
    # ------------------------------------------------------------------

    def _on_account_add(self) -> None:
        """Open a terminal to run the interactive account add flow.

        ``twingate account add`` is interactive (prompts for network name,
        opens browser for auth, restarts the service), so it must run in a
        visible terminal rather than a background subprocess.
        """
        terminal = _find_terminal()
        if terminal is None:
            self._warn(
                "No terminal emulator found. Run manually:\n"
                "pkexec /usr/bin/twingate account add"
            )
            return
        binary, args = terminal
        cmd = [binary, *args, "pkexec", "/usr/bin/twingate", "account", "add"]
        try:
            subprocess.Popen(cmd)
        except OSError as exc:
            logger.error("Failed to open terminal for account add: %s", exc)
            self._warn(
                "Failed to open terminal. Run manually:\n"
                "pkexec /usr/bin/twingate account add"
            )

    def _on_account_logout(self) -> None:
        """Log out of current account."""
        self._run_command("Logout", "account_logout")

    def _switch_account(self, switch_id: str) -> None:
        """Open a terminal to run the interactive account switch flow.

        ``twingate account switch`` prompts for confirmation and restarts
        the service, so it must run in a visible terminal.
        """
        terminal = _find_terminal()
        if terminal is None:
            self._warn(
                "No terminal emulator found. Run manually:\n"
                f"pkexec /usr/bin/twingate account switch {switch_id}"
            )
            return
        binary, args = terminal
        cmd = [binary, *args, "pkexec", "/usr/bin/twingate", "account", "switch", switch_id]
        try:
            subprocess.Popen(cmd)
        except OSError as exc:
            logger.error("Failed to open terminal for account switch: %s", exc)
            self._warn(
                "Failed to open terminal. Run manually:\n"
                f"pkexec /usr/bin/twingate account switch {switch_id}"
            )

    # ------------------------------------------------------------------
    # Exit node actions
    # ------------------------------------------------------------------

    def _on_exit_node_stop(self) -> None:
        """Disable exit node routing."""
        logger.info("Action triggered: Disable exit node routing")
        self._run_command("Disable routing", "exit_node_stop")

    def _start_exit_node(self, name: str) -> None:
        """Start routing through a specific exit node."""
        logger.info("Action triggered: Start exit node %r", name)
        self._run_command("Start exit node", "exit_node_start", (name,))

    def _switch_exit_node(self, name: str) -> None:
        """Switch to a different exit node."""
        logger.info("Action triggered: Switch exit node %r", name)
        self._run_command("Switch exit node", "exit_node_switch", (name,))

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
