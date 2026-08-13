from __future__ import annotations

import json
import os
import subprocess
import threading
import urllib.error
import urllib.request
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from .database import Database


SYNC_ENDPOINT = "https://dxb-runway-mobile.randomsteen1.chatgpt.site/api/sync"
KEYCHAIN_SERVICE = "DXB RUNWAY Mobile Sync"


def _keychain_value(account: str, environment_name: str) -> str:
    override = os.environ.get(environment_name, "").strip()
    if override:
        return override
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def sync_credentials() -> tuple[str, str]:
    return (
        _keychain_value("site-access-token", "DXB_RUNWAY_SYNC_TOKEN"),
        _keychain_value("sync-secret", "DXB_RUNWAY_SYNC_SECRET"),
    )


def upload_snapshot(snapshot: dict[str, object], token: str, secret: str, timeout: int = 20) -> str:
    if not token or not secret:
        raise RuntimeError("Private phone sync has not been connected yet")
    request = urllib.request.Request(
        SYNC_ENDPOINT,
        data=json.dumps(snapshot, separators=(",", ":")).encode("utf-8"),
        headers={
            "oai-sites-authorization": f"Bearer {token}",
            "content-type": "application/json",
            "user-agent": "DXB-RUNWAY-Mac/2.2",
            "x-dxb-sync-key": secret,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Phone sync rejected ({error.code}): {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Phone sync unavailable: {error.reason}") from error
    if not body.get("ok"):
        raise RuntimeError(str(body.get("error") or "Phone sync did not complete"))
    return str(body.get("syncedAt") or datetime.now().isoformat(timespec="seconds"))


class MobileSyncManager(QObject):
    status_changed = Signal(str, bool)
    _finished = Signal()

    def __init__(self, db: Database, parent: QObject | None = None):
        super().__init__(parent)
        self.db = db
        self._running = False
        self._pending = False
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self.sync_now)
        self._periodic = QTimer(self)
        self._periodic.setInterval(120_000)
        self._periodic.timeout.connect(self.schedule)
        self._periodic.start()
        self._finished.connect(self._complete)

    def configured(self) -> bool:
        return all(sync_credentials())

    def schedule(self) -> None:
        if not self.configured():
            self.status_changed.emit("Phone sync not connected", False)
            return
        self._debounce.start(900)

    def sync_now(self) -> None:
        if self._running:
            self._pending = True
            return
        token, secret = sync_credentials()
        if not token or not secret:
            self.status_changed.emit("Phone sync not connected", False)
            return
        snapshot = self.db.mobile_sync_snapshot()
        self._running = True
        self.status_changed.emit("Syncing phone…", True)

        def work() -> None:
            try:
                synced_at = upload_snapshot(snapshot, token, secret)
                self.status_changed.emit(f"Phone synced · {synced_at[11:16]}", True)
            except Exception:
                self.status_changed.emit("Phone sync will retry", False)
            finally:
                self._finished.emit()

        threading.Thread(target=work, name="dxb-mobile-sync", daemon=True).start()

    def _complete(self) -> None:
        self._running = False
        if self._pending:
            self._pending = False
            self._debounce.start(500)
