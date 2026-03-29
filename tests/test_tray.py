"""Unit tests for TwingateSystemTray menu construction and actions."""

from unittest.mock import MagicMock, patch

from twingate_tray.client import (
    ConnectionState,
    TwingateStatus,
)
from twingate_tray.tray import _ALLOWED_METHODS, _STATE_LABELS, TwingateSystemTray


class TestStateLabels:
    """Tests for the state label mapping."""

    def test_all_states_have_labels(self) -> None:
        for state in ConnectionState:
            assert state in _STATE_LABELS

    def test_online_label_is_connected(self) -> None:
        assert _STATE_LABELS[ConnectionState.ONLINE] == "Connected"

    def test_offline_label_is_disconnected(self) -> None:
        assert _STATE_LABELS[ConnectionState.OFFLINE] == "Disconnected"

    def test_paused_label_is_paused(self) -> None:
        assert _STATE_LABELS[ConnectionState.PAUSED] == "Paused"

    def test_unknown_label_is_unknown(self) -> None:
        assert _STATE_LABELS[ConnectionState.UNKNOWN] == "Unknown"

    def test_connecting_label_contains_connecting(self) -> None:
        assert "Connecting" in _STATE_LABELS[ConnectionState.CONNECTING]


class TestAllowedMethods:
    """Tests for the command allowlist."""

    def test_allowed_methods_covers_all_dispatched_commands(self) -> None:
        """Verify the allowlist includes every method used by tray actions."""
        expected = {
            "start", "stop", "connect", "disconnect", "auth",
            "account_logout",
            "exit_node_start", "exit_node_stop", "exit_node_switch",
        }
        assert expected.issubset(_ALLOWED_METHODS)

    def test_disallowed_method_is_rejected(self) -> None:
        """Methods not in the allowlist are not executed."""
        assert "_run" not in _ALLOWED_METHODS
        assert "__init__" not in _ALLOWED_METHODS


class TestTrayActions:
    """Tests for tray action handlers (mocked, no Qt event loop)."""

    def test_on_connect_calls_run_command(self) -> None:
        tray = MagicMock(spec=TwingateSystemTray)
        tray._run_command = MagicMock()
        TwingateSystemTray._on_connect(tray)
        tray._run_command.assert_called_once_with("Connect", "start")

    def test_on_stop_calls_run_command(self) -> None:
        tray = MagicMock(spec=TwingateSystemTray)
        tray._run_command = MagicMock()
        TwingateSystemTray._on_stop(tray)
        tray._run_command.assert_called_once_with("Disconnect", "stop")

    def test_on_resource_auth_calls_run_command(self) -> None:
        tray = MagicMock(spec=TwingateSystemTray)
        tray._run_command = MagicMock()
        TwingateSystemTray._on_resource_auth(tray, "my-resource")
        tray._run_command.assert_called_once_with(
            "Re-authenticate", "auth", ("my-resource",)
        )

    @patch("twingate_tray.tray._find_terminal", return_value=("xterm", ["-e"]))
    @patch("twingate_tray.tray.subprocess.Popen")
    def test_on_account_add_opens_terminal(
        self, mock_popen: MagicMock, mock_find: MagicMock
    ) -> None:
        tray = MagicMock(spec=TwingateSystemTray)
        TwingateSystemTray._on_account_add(tray)
        mock_popen.assert_called_once_with(
            ["xterm", "-e", "pkexec", "/usr/bin/twingate", "account", "add"]
        )

    @patch("twingate_tray.tray._find_terminal", return_value=None)
    def test_on_account_add_warns_when_no_terminal(
        self, mock_find: MagicMock
    ) -> None:
        tray = MagicMock(spec=TwingateSystemTray)
        tray._warn = MagicMock()
        TwingateSystemTray._on_account_add(tray)
        tray._warn.assert_called_once()

    def test_on_account_logout_calls_run_command(self) -> None:
        tray = MagicMock(spec=TwingateSystemTray)
        tray._run_command = MagicMock()
        TwingateSystemTray._on_account_logout(tray)
        tray._run_command.assert_called_once_with("Logout", "account_logout")

    @patch("twingate_tray.tray._find_terminal", return_value=("xterm", ["-e"]))
    @patch("twingate_tray.tray.subprocess.Popen")
    def test_switch_account_opens_terminal(
        self, mock_popen: MagicMock, mock_find: MagicMock
    ) -> None:
        tray = MagicMock(spec=TwingateSystemTray)
        TwingateSystemTray._switch_account(tray, "user@example.com:acme")
        mock_popen.assert_called_once_with([
            "xterm", "-e", "pkexec", "/usr/bin/twingate",
            "account", "switch", "user@example.com:acme",
        ])

    def test_start_exit_node_calls_run_command(self) -> None:
        tray = MagicMock(spec=TwingateSystemTray)
        tray._run_command = MagicMock()
        TwingateSystemTray._start_exit_node(tray, "us-east-1")
        tray._run_command.assert_called_once_with(
            "Start exit node", "exit_node_start", ("us-east-1",)
        )

    def test_on_exit_node_stop_calls_run_command(self) -> None:
        tray = MagicMock(spec=TwingateSystemTray)
        tray._run_command = MagicMock()
        TwingateSystemTray._on_exit_node_stop(tray)
        tray._run_command.assert_called_once_with("Disable routing", "exit_node_stop")

    def test_switch_exit_node_calls_run_command(self) -> None:
        tray = MagicMock(spec=TwingateSystemTray)
        tray._run_command = MagicMock()
        TwingateSystemTray._switch_exit_node(tray, "us-west")
        tray._run_command.assert_called_once_with(
            "Switch exit node", "exit_node_switch", ("us-west",)
        )


class TestOnStatusChanged:
    """Tests for _on_status_changed — icon, tooltip, menu, and notifications."""

    def _make_tray(self, is_first_poll: bool = False) -> MagicMock:
        tray = MagicMock(spec=TwingateSystemTray)
        tray._current_status = TwingateStatus(state=ConnectionState.UNKNOWN)
        tray._is_first_poll = is_first_poll
        tray._icons = MagicMock()
        tray._icons.get_icon.return_value = MagicMock()
        return tray

    def test_updates_icon_on_state_change(self) -> None:
        """setIcon is called with the icon for the new state."""
        tray = self._make_tray()
        new_status = TwingateStatus(state=ConnectionState.ONLINE)
        TwingateSystemTray._on_status_changed(tray, new_status)
        tray.setIcon.assert_called_once_with(
            tray._icons.get_icon.return_value
        )
        tray._icons.get_icon.assert_called_once_with(ConnectionState.ONLINE)

    def test_updates_tooltip_on_state_change(self) -> None:
        """setToolTip is called and contains the human-readable state label."""
        tray = self._make_tray()
        new_status = TwingateStatus(state=ConnectionState.ONLINE)
        TwingateSystemTray._on_status_changed(tray, new_status)
        tray.setToolTip.assert_called_once()
        tooltip: str = tray.setToolTip.call_args[0][0]
        assert "Connected" in tooltip

    def test_rebuilds_menu_on_state_change(self) -> None:
        """_build_menu is called each time status changes."""
        tray = self._make_tray()
        new_status = TwingateStatus(state=ConnectionState.ONLINE)
        TwingateSystemTray._on_status_changed(tray, new_status)
        tray._build_menu.assert_called_once()

    def test_suppresses_notification_on_first_poll(self) -> None:
        """No notification is shown when _is_first_poll is True."""
        tray = self._make_tray(is_first_poll=True)
        new_status = TwingateStatus(state=ConnectionState.ONLINE)
        TwingateSystemTray._on_status_changed(tray, new_status)
        tray._notify_state_change.assert_not_called()
        # Flag must be cleared so subsequent polls can notify
        assert tray._is_first_poll is False

    def test_emits_notification_on_subsequent_state_change(self) -> None:
        """A notification is shown when state changes after the first poll."""
        tray = self._make_tray(is_first_poll=False)
        tray._current_status = TwingateStatus(state=ConnectionState.OFFLINE)
        new_status = TwingateStatus(state=ConnectionState.ONLINE)
        TwingateSystemTray._on_status_changed(tray, new_status)
        tray._notify_state_change.assert_called_once_with(
            ConnectionState.OFFLINE, new_status
        )

    def test_no_notification_when_state_unchanged(self) -> None:
        """No notification is shown when the state does not actually change."""
        tray = self._make_tray(is_first_poll=False)
        tray._current_status = TwingateStatus(state=ConnectionState.ONLINE)
        new_status = TwingateStatus(state=ConnectionState.ONLINE)
        TwingateSystemTray._on_status_changed(tray, new_status)
        tray._notify_state_change.assert_not_called()


class TestNotifyStateChange:
    """Tests for _notify_state_change notification content."""

    def _make_tray(self) -> MagicMock:
        tray = MagicMock(spec=TwingateSystemTray)
        tray.showMessage = MagicMock()
        return tray

    def test_online_shows_connected_message(self) -> None:
        """ONLINE state shows an Information notification containing 'Connected'."""
        tray = self._make_tray()
        status = TwingateStatus(state=ConnectionState.ONLINE)
        TwingateSystemTray._notify_state_change(
            tray, ConnectionState.OFFLINE, status
        )
        tray.showMessage.assert_called_once()
        _title, body, *_rest = tray.showMessage.call_args[0]
        assert "Connected" in body

    def test_online_with_network_includes_network_name(self) -> None:
        """ONLINE with a network name includes that name in the notification."""
        tray = self._make_tray()
        status = TwingateStatus(state=ConnectionState.ONLINE, network="acme-corp")
        TwingateSystemTray._notify_state_change(
            tray, ConnectionState.OFFLINE, status
        )
        _title, body, *_rest = tray.showMessage.call_args[0]
        assert "acme-corp" in body

    def test_offline_shows_disconnected_message(self) -> None:
        """OFFLINE state shows an Information notification containing 'Disconnected'."""
        tray = self._make_tray()
        status = TwingateStatus(state=ConnectionState.OFFLINE)
        TwingateSystemTray._notify_state_change(
            tray, ConnectionState.ONLINE, status
        )
        tray.showMessage.assert_called_once()
        _title, body, *_rest = tray.showMessage.call_args[0]
        assert "Disconnected" in body

    def test_paused_shows_paused_message(self) -> None:
        """PAUSED state shows an Information notification containing 'paused'."""
        tray = self._make_tray()
        status = TwingateStatus(state=ConnectionState.PAUSED)
        TwingateSystemTray._notify_state_change(
            tray, ConnectionState.ONLINE, status
        )
        tray.showMessage.assert_called_once()
        _title, body, *_rest = tray.showMessage.call_args[0]
        assert "paused" in body.lower()

    def test_unknown_shows_warning_notification(self) -> None:
        """UNKNOWN state shows a Warning-level notification."""
        from PyQt6.QtWidgets import QSystemTrayIcon

        tray = self._make_tray()
        status = TwingateStatus(state=ConnectionState.UNKNOWN)
        TwingateSystemTray._notify_state_change(
            tray, ConnectionState.ONLINE, status
        )
        tray.showMessage.assert_called_once()
        _title, _body, icon, *_rest = tray.showMessage.call_args[0]
        assert icon == QSystemTrayIcon.MessageIcon.Warning

    def test_connecting_does_not_show_notification(self) -> None:
        """CONNECTING state does not trigger a showMessage call."""
        tray = self._make_tray()
        status = TwingateStatus(state=ConnectionState.CONNECTING)
        TwingateSystemTray._notify_state_change(
            tray, ConnectionState.OFFLINE, status
        )
        tray.showMessage.assert_not_called()


class TestOnQuit:
    """Tests for the quit action."""

    @patch("twingate_tray.tray.QApplication")
    def test_on_quit_calls_application_quit(self, mock_app: MagicMock) -> None:
        """_on_quit must delegate to QApplication.quit()."""
        TwingateSystemTray._on_quit()
        mock_app.quit.assert_called_once()


class TestCopyToClipboard:
    """Test clipboard helper."""

    @patch("twingate_tray.tray.QApplication")
    def test_copy_to_clipboard(self, mock_app: MagicMock) -> None:
        mock_clipboard = MagicMock()
        mock_app.clipboard.return_value = mock_clipboard
        TwingateSystemTray._copy_to_clipboard("10.0.0.1")
        mock_clipboard.setText.assert_called_once_with("10.0.0.1")
