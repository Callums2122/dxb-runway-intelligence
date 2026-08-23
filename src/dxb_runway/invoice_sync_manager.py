from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from .database import Database
from .invoice_sync import configured_invoice_service


class _Signals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, db: Database):
        super().__init__(); self.db = db; self.signals = _Signals()
    def run(self) -> None:
        try:
            service = configured_invoice_service(self.db)
            if service is None: raise RuntimeError("Invoice sync is not connected")
            self.signals.finished.emit(service.sync())
        except Exception as error:
            self.signals.failed.emit(str(error))


class InvoiceSyncManager(QObject):
    status_changed = Signal(str, bool)
    data_changed = Signal()

    def __init__(self, db: Database, parent: QObject | None = None):
        super().__init__(parent); self.db = db; self._busy = False; self._job = None
        self.timer = QTimer(self); self.timer.setInterval(300_000); self.timer.timeout.connect(self.sync); self.timer.start()
        QTimer.singleShot(2500, self.sync)

    def sync(self) -> None:
        if self._busy or configured_invoice_service(self.db) is None: return
        self._busy = True; self.status_changed.emit("Checking sold invoices…", True)
        job = _Job(self.db); self._job = job
        job.signals.finished.connect(self._finished); job.signals.failed.connect(self._failed)
        QThreadPool.globalInstance().start(job)

    def _finished(self, result: object) -> None:
        self._busy = False
        sold = int(getattr(result, "sold", 0)); review = int(getattr(result, "review", 0))
        text = f"Invoice sync · {sold} sold"
        if review: text += f" · {review} review"
        self.status_changed.emit(text, True)
        if sold or review: self.data_changed.emit()

    def _failed(self, message: str) -> None:
        self._busy = False; self.db.set_setting("invoice_sync_last_error", message)
        self.status_changed.emit("Invoice sync unavailable", False)
