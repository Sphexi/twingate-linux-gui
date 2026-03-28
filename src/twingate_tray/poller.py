"""StatusPoller — QTimer-based polling for Twingate connection state."""

import logging

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from twingate_tray.client import ConnectionState, TwingateClient, TwingateStatus

logger = logging.getLogger(__name__)


class StatusWorker(QObject):
    """Runs the blocking ``twingate status`` call in a background thread."""

    status_ready = pyqtSignal(object)  # emits TwingateStatus
    trigger = pyqtSignal()  # used to invoke check_status across threads

    def __init__(self, client: TwingateClient) -> None:
        super().__init__()
        self._client = client
        self.trigger.connect(self.check_status)

    def check_status(self) -> None:
        """Execute the status check and emit the result."""
        try:
            status = self._client.status()
        except Exception:
            logger.exception("Status check failed")
            status = TwingateStatus(state=ConnectionState.UNKNOWN)
        self.status_ready.emit(status)


class StatusPoller(QObject):
    """Polls ``twingate status`` at a configurable interval.

    Emits :pyqtSignal:`status_changed` whenever the connection state
    transitions to a new value.  The actual subprocess call runs in a
    ``QThread`` so the GUI event loop is never blocked.
    """

    status_changed = pyqtSignal(object)  # emits TwingateStatus

    def __init__(
        self,
        client: TwingateClient,
        interval_ms: int = 10_000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._last_state: ConnectionState | None = None
        self._interval_ms = interval_ms
        self._busy = False  # prevents overlapping polls

        # Worker lives on a dedicated thread
        self._worker = StatusWorker(client)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._worker.status_ready.connect(self._on_status_ready)

        # Timer fires on the main thread, triggering the worker via a queued call
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    @property
    def interval_ms(self) -> int:
        """Return the current poll interval in milliseconds."""
        return self._interval_ms

    @interval_ms.setter
    def interval_ms(self, value: int) -> None:
        """Update the poll interval. Takes effect on the next timer cycle."""
        self._interval_ms = value
        if self._timer.isActive():
            self._timer.setInterval(value)

    def start(self) -> None:
        """Start background polling."""
        self._thread.start()
        self._poll()  # immediate first check
        self._timer.start(self._interval_ms)
        logger.info("StatusPoller started (interval=%dms)", self._interval_ms)

    def stop(self) -> None:
        """Stop polling and clean up the worker thread."""
        self._timer.stop()
        self._thread.quit()
        self._thread.wait(5000)

    def force_poll(self) -> None:
        """Trigger an immediate status check (e.g. after a command).

        Adds a small delay to give the daemon time to update state.
        """
        QTimer.singleShot(500, self._poll)

    def _poll(self) -> None:
        """Schedule the worker's check on the background thread."""
        if self._busy:
            logger.debug("Poll skipped — previous poll still in flight")
            return
        if self._thread.isRunning():
            self._busy = True
            self._worker.trigger.emit()
            # Safety: clear _busy after timeout in case the signal is never delivered
            QTimer.singleShot(
                self._interval_ms, self._clear_busy_if_stuck,
            )
        else:
            logger.warning("Poll skipped — worker thread is not running")

    def _clear_busy_if_stuck(self) -> None:
        """Reset _busy flag if it was never cleared by _on_status_ready."""
        if self._busy:
            logger.warning("Busy flag stuck — clearing to unblock polling")
            self._busy = False

    def _on_status_ready(self, status: TwingateStatus) -> None:
        """Handle a fresh status from the worker thread."""
        self._busy = False
        logger.info(
            "Status polled: %s (previous: %s)",
            status.state.value,
            self._last_state.value if self._last_state else "None",
        )
        if self._last_state != status.state:
            self._last_state = status.state
            self.status_changed.emit(status)
