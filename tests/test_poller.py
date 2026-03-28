"""Unit tests for StatusPoller and StatusWorker."""

from unittest.mock import MagicMock, patch

from twingate_tray.client import ConnectionState, TwingateClient, TwingateStatus
from twingate_tray.poller import StatusPoller, StatusWorker


class TestStatusWorker:
    """Tests for StatusWorker."""

    @patch.object(TwingateClient, "status")
    def test_check_status_emits_signal(self, mock_status: MagicMock) -> None:
        mock_status.return_value = TwingateStatus(state=ConnectionState.ONLINE)
        client = TwingateClient()
        worker = StatusWorker(client)

        received: list[TwingateStatus] = []
        worker.status_ready.connect(received.append)
        worker.check_status()

        assert len(received) == 1
        assert received[0].state == ConnectionState.ONLINE

    @patch.object(TwingateClient, "status")
    def test_check_status_emits_offline_state(self, mock_status: MagicMock) -> None:
        """check_status emits a status with OFFLINE state when CLI reports offline."""
        mock_status.return_value = TwingateStatus(state=ConnectionState.OFFLINE)
        client = TwingateClient()
        worker = StatusWorker(client)

        received: list[TwingateStatus] = []
        worker.status_ready.connect(received.append)
        worker.check_status()

        assert len(received) == 1
        assert received[0].state == ConnectionState.OFFLINE

    @patch.object(TwingateClient, "status")
    def test_check_status_emits_unknown_state(self, mock_status: MagicMock) -> None:
        """check_status emits a status with UNKNOWN state when CLI output is unparseable."""
        mock_status.return_value = TwingateStatus(state=ConnectionState.UNKNOWN)
        client = TwingateClient()
        worker = StatusWorker(client)

        received: list[TwingateStatus] = []
        worker.status_ready.connect(received.append)
        worker.check_status()

        assert len(received) == 1
        assert received[0].state == ConnectionState.UNKNOWN


class TestStatusPoller:
    """Tests for StatusPoller (timer and state-change detection)."""

    def test_initial_interval(self) -> None:
        client = TwingateClient()
        poller = StatusPoller(client, interval_ms=5000)
        assert poller.interval_ms == 5000

    def test_default_interval_is_10000ms(self) -> None:
        """StatusPoller uses a 10-second poll interval when none is specified."""
        client = TwingateClient()
        poller = StatusPoller(client)
        assert poller.interval_ms == 10_000

    def test_interval_setter_updates_stored_value(self) -> None:
        """interval_ms setter stores the new value when timer is active."""
        client = TwingateClient()
        poller = StatusPoller(client, interval_ms=5000)
        poller.interval_ms = 15000
        assert poller.interval_ms == 15000

    def test_interval_setter_when_timer_is_not_active_stores_value(self) -> None:
        """interval_ms setter stores the value without calling setInterval when timer is idle."""
        client = TwingateClient()
        poller = StatusPoller(client, interval_ms=5000)
        # Timer is not started, so isActive() returns False
        assert not poller._timer.isActive()
        poller.interval_ms = 20000
        assert poller.interval_ms == 20000
        # Timer should still not be active — setter must not start it
        assert not poller._timer.isActive()

    def test_on_status_ready_emits_on_change(self) -> None:
        client = TwingateClient()
        poller = StatusPoller(client)

        received: list[TwingateStatus] = []
        poller.status_changed.connect(received.append)

        # First status — should emit (None -> ONLINE)
        status1 = TwingateStatus(state=ConnectionState.ONLINE)
        poller._on_status_ready(status1)
        assert len(received) == 1

        # Same status — should NOT emit
        poller._on_status_ready(status1)
        assert len(received) == 1

        # Different status — should emit
        status2 = TwingateStatus(state=ConnectionState.OFFLINE)
        poller._on_status_ready(status2)
        assert len(received) == 2

    def test_on_status_ready_emits_on_transition_online_to_paused(self) -> None:
        """_on_status_ready emits when state transitions from ONLINE to PAUSED."""
        client = TwingateClient()
        poller = StatusPoller(client)
        poller._last_state = ConnectionState.ONLINE

        received: list[TwingateStatus] = []
        poller.status_changed.connect(received.append)

        status = TwingateStatus(state=ConnectionState.PAUSED)
        poller._on_status_ready(status)

        assert len(received) == 1
        assert received[0].state == ConnectionState.PAUSED

    def test_on_status_ready_emits_on_transition_online_to_unknown(self) -> None:
        """_on_status_ready emits when state transitions from ONLINE to UNKNOWN."""
        client = TwingateClient()
        poller = StatusPoller(client)
        poller._last_state = ConnectionState.ONLINE

        received: list[TwingateStatus] = []
        poller.status_changed.connect(received.append)

        status = TwingateStatus(state=ConnectionState.UNKNOWN)
        poller._on_status_ready(status)

        assert len(received) == 1
        assert received[0].state == ConnectionState.UNKNOWN

    def test_on_status_ready_emits_for_multiple_rapid_transitions(self) -> None:
        """_on_status_ready fires once per distinct state in UNKNOWN→ONLINE→OFFLINE sequence."""
        client = TwingateClient()
        poller = StatusPoller(client)

        received: list[TwingateStatus] = []
        poller.status_changed.connect(received.append)

        # Start from None — first status always emits
        poller._on_status_ready(TwingateStatus(state=ConnectionState.UNKNOWN))
        poller._on_status_ready(TwingateStatus(state=ConnectionState.ONLINE))
        poller._on_status_ready(TwingateStatus(state=ConnectionState.OFFLINE))

        assert len(received) == 3
        assert received[0].state == ConnectionState.UNKNOWN
        assert received[1].state == ConnectionState.ONLINE
        assert received[2].state == ConnectionState.OFFLINE

    def test_on_status_ready_first_status_always_emits(self) -> None:
        """The very first status received always emits regardless of its value."""
        for state in (
            ConnectionState.ONLINE,
            ConnectionState.OFFLINE,
            ConnectionState.PAUSED,
            ConnectionState.UNKNOWN,
        ):
            client = TwingateClient()
            poller = StatusPoller(client)
            assert poller._last_state is None

            received: list[TwingateStatus] = []
            poller.status_changed.connect(received.append)

            poller._on_status_ready(TwingateStatus(state=state))

            assert len(received) == 1, f"Expected emission for first status {state}"
            assert received[0].state == state

    def test_busy_guard_clears_on_status_ready(self) -> None:
        """_busy flag is cleared when status arrives from the worker."""
        client = TwingateClient()
        poller = StatusPoller(client)
        poller._busy = True

        status = TwingateStatus(state=ConnectionState.ONLINE)
        poller._on_status_ready(status)
        assert poller._busy is False

    def test_poll_skips_when_busy(self) -> None:
        """_poll does nothing when _busy is True."""
        client = TwingateClient()
        poller = StatusPoller(client)
        poller._busy = True

        # _poll should be a no-op when busy
        poller._poll()
        # busy should still be True (no new poll dispatched)
        assert poller._busy is True

    def test_poll_sets_busy_true_when_thread_is_running(self) -> None:
        """_poll sets _busy to True after dispatching work to a running thread."""
        client = TwingateClient()
        poller = StatusPoller(client)
        poller._busy = False

        # Simulate a running thread
        mock_thread = MagicMock()
        mock_thread.isRunning.return_value = True
        poller._thread = mock_thread

        # Mock the worker trigger signal so emit doesn't actually run
        poller._worker.trigger = MagicMock()
        poller._poll()

        assert poller._busy is True
        poller._worker.trigger.emit.assert_called_once()

    def test_poll_is_noop_when_thread_is_not_running(self) -> None:
        """_poll does not set _busy or dispatch work when the thread is not running."""
        client = TwingateClient()
        poller = StatusPoller(client)
        poller._busy = False

        mock_thread = MagicMock()
        mock_thread.isRunning.return_value = False
        poller._thread = mock_thread

        poller._worker.trigger = MagicMock()
        poller._poll()

        assert poller._busy is False
        poller._worker.trigger.emit.assert_not_called()

    def test_force_poll_calls_single_shot_with_500ms(self) -> None:
        """force_poll schedules _poll via QTimer.singleShot with a 500ms delay."""
        client = TwingateClient()
        poller = StatusPoller(client)

        with patch("twingate_tray.poller.QTimer.singleShot") as mock_single_shot:
            poller.force_poll()

        mock_single_shot.assert_called_once_with(500, poller._poll)
