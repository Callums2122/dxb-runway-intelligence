from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, QTimer, Signal

from .database import Database
from .whatsapp_import import file_sha256, parse_whatsapp_zip, route_download_exports


class WhatsAppImportMonitor(QObject):
    imported = Signal(int)
    scan_finished = Signal(int, int)

    def __init__(self, db: Database, downloads: Path | None = None, parent: QObject | None = None):
        super().__init__(parent)
        default_downloads = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation))
        self.db = db
        self.downloads = Path(downloads or default_downloads)
        self.root = db.path.parent / "whatsapp_imports"
        self.inbox = self.root / "inbox"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.timer = QTimer(self)
        self.timer.setInterval(10_000)
        self.timer.timeout.connect(self.scan)
        self._scanning = False

    def start(self) -> None:
        self.scan()
        self.timer.start()

    def scan(self) -> tuple[int, int]:
        if self._scanning:
            return 0, 0
        self._scanning = True
        imported_count = failed_count = 0
        try:
            route_download_exports(self.downloads, self.inbox)
            for path in sorted(self.inbox.glob("*.zip"), key=lambda item: item.stat().st_mtime):
                digest = file_sha256(path)
                if self.db.whatsapp_import_known(digest):
                    continue
                try:
                    import_id = self.db.import_whatsapp_chat(parse_whatsapp_zip(path))
                    imported_count += 1
                    self.imported.emit(import_id)
                except Exception as error:
                    self.db.record_failed_whatsapp_import(path.name, digest, str(error))
                    failed_count += 1
            self.scan_finished.emit(imported_count, failed_count)
            return imported_count, failed_count
        finally:
            self._scanning = False
