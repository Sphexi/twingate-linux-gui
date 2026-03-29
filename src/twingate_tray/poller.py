"""StatusPoller — QTimer-based polling for Twingate connection state."""

import logging

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from twingate_tray.client import ConnectionState, TwingateClient, TwingateStatus

logger = logging.getLogger(__name__)


class StatusPoller(QObject):
    """Polls ``twingate status`` at a configurable interval.

    Emits :pyqtSignal:`status_changed` on every successful poll so the
    tray can rebuild its menu.  The status check runs synchronously on the
    main thread — ``twingate status`` typically completes in under 1 second,
    which is acceptable for a tray application.
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
        """Start polling."""
        self._timer.start(self._interval_ms)
        logger.info("StatusPoller started (interval=%dms)", self._interval_ms)
        self._poll()  # immediate first check

    def stop(self) -> None:
        """Stop polling."""
        self._timer.stop()

    def force_poll(self) -> None:
        """Trigger an immediate status check (e.g. after a command).

        Adds a small delay to give the daemon time to update state.
        """
        QTimer.singleShot(500, self._poll)

    def _poll(self) -> None:
        """Run the status check and emit the result."""
        try:
            status = self._client.status()
        except Exception:
            logger.exception("Status check failed")
            status = TwingateStatus(state=ConnectionState.UNKNOWN)

        changed = self._last_state != status.state
        if changed:
            logger.info(
                "Status changed: %s -> %s",
                self._last_state.value if self._last_state else "None",
                status.state.value,
            )
            self._last_state = status.state
        self.status_changed.emit(status)
