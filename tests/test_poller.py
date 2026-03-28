"""Unit tests for StatusPoller."""

from unittest.mock import MagicMock, patch

from twingate_tray.client import ConnectionState, TwingateClient, TwingateStatus
from twingate_tray.poller import StatusPoller


class TestStatusPoller:
    """Tests for StatusPoller."""

    def test_initial_interval(self) -> None:
        client = TwingateClient()
        poller = StatusPoller(client, interval_ms=5000)
        assert poller.interval_ms == 5000

    def test_default_interval_is_10000ms(self) -> None:
        client = TwingateClient()
        poller = StatusPoller(client)
        assert poller.interval_ms == 10_000

    def test_interval_setter_updates_stored_value(self) -> None:
        client = TwingateClient()
        poller = StatusPoller(client, interval_ms=5000)
        poller.interval_ms = 15000
        assert poller.interval_ms == 15000

    def test_interval_setter_when_timer_is_not_active_stores_value(self) -> None:
        client = TwingateClient()
        poller = StatusPoller(client, interval_ms=5000)
        poller.interval_ms = 20000
        assert poller.interval_ms == 20000
        assert not poller._timer.isActive()

    @patch.object(TwingateClient, "status")
    def test_poll_emits_status(self, mock_status: MagicMock) -> None:
        mock_status.return_value = TwingateStatus(state=ConnectionState.ONLINE)
        client = TwingateClient()
        poller = StatusPoller(client)

        received: list[TwingateStatus] = []
        poller.status_changed.connect(received.append)
        poller._poll()

        assert len(received) == 1
        assert received[0].state == ConnectionState.ONLINE

    @patch.object(TwingateClient, "status")
    def test_poll_emits_on_every_call(self, mock_status: MagicMock) -> None:
        """status_changed fires on every poll so the tray always refreshes."""
        mock_status.return_value = TwingateStatus(state=ConnectionState.ONLINE)
        client = TwingateClient()
        poller = StatusPoller(client)

        received: list[TwingateStatus] = []
        poller.status_changed.connect(received.append)

        poller._poll()
        poller._poll()
        poller._poll()

        assert len(received) == 3

    @patch.object(TwingateClient, "status")
    def test_poll_tracks_state_changes(self, mock_status: MagicMock) -> None:
        mock_status.return_value = TwingateStatus(state=ConnectionState.ONLINE)
        client = TwingateClient()
        poller = StatusPoller(client)

        poller._poll()
        assert poller._last_state == ConnectionState.ONLINE

        mock_status.return_value = TwingateStatus(state=ConnectionState.OFFLINE)
        poller._poll()
        assert poller._last_state == ConnectionState.OFFLINE

    @patch.object(TwingateClient, "status")
    def test_poll_emits_offline_state(self, mock_status: MagicMock) -> None:
        mock_status.return_value = TwingateStatus(state=ConnectionState.OFFLINE)
        client = TwingateClient()
        poller = StatusPoller(client)

        received: list[TwingateStatus] = []
        poller.status_changed.connect(received.append)
        poller._poll()

        assert received[0].state == ConnectionState.OFFLINE

    @patch.object(TwingateClient, "status")
    def test_poll_emits_unknown_on_exception(self, mock_status: MagicMock) -> None:
        mock_status.side_effect = RuntimeError("broken")
        client = TwingateClient()
        poller = StatusPoller(client)

        received: list[TwingateStatus] = []
        poller.status_changed.connect(received.append)
        poller._poll()

        assert len(received) == 1
        assert received[0].state == ConnectionState.UNKNOWN

    @patch.object(TwingateClient, "status")
    def test_multiple_transitions(self, mock_status: MagicMock) -> None:
        """Test UNKNOWN -> ONLINE -> OFFLINE produces correct state tracking."""
        client = TwingateClient()
        poller = StatusPoller(client)

        received: list[TwingateStatus] = []
        poller.status_changed.connect(received.append)

        mock_status.return_value = TwingateStatus(state=ConnectionState.UNKNOWN)
        poller._poll()
        mock_status.return_value = TwingateStatus(state=ConnectionState.ONLINE)
        poller._poll()
        mock_status.return_value = TwingateStatus(state=ConnectionState.OFFLINE)
        poller._poll()

        assert len(received) == 3
        assert received[0].state == ConnectionState.UNKNOWN
        assert received[1].state == ConnectionState.ONLINE
        assert received[2].state == ConnectionState.OFFLINE

    @patch.object(TwingateClient, "status")
    def test_first_status_always_emits(self, mock_status: MagicMock) -> None:
        """First poll always emits regardless of state (None -> any)."""
        for state in ConnectionState:
            mock_status.return_value = TwingateStatus(state=state)
            client = TwingateClient()
            poller = StatusPoller(client)

            received: list[TwingateStatus] = []
            poller.status_changed.connect(received.append)
            poller._poll()

            assert len(received) == 1, f"Failed for state {state}"

    def test_force_poll_calls_single_shot_with_500ms(self) -> None:
        """force_poll schedules _poll via QTimer.singleShot with a 500ms delay."""
        client = TwingateClient()
        poller = StatusPoller(client)

        with patch("twingate_tray.poller.QTimer.singleShot") as mock_single_shot:
            poller.force_poll()

        mock_single_shot.assert_called_once_with(500, poller._poll)
