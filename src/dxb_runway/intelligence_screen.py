from __future__ import annotations

import base64
import json
import shlex
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QRectF, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from .database import Database
from .deal_drive import DealDriveClient, DealDriveError, KeychainCredentials, comparison_summary, save_market_snapshot, sync_status, velocity_rankings
from .dialogs import MoneyBox
from .intelligence import (
    analyse_opportunity, chat_conversation, chat_evidence, forget_intelligence_memory,
    import_history, import_vehicle_history, intelligence_memories, learning_directive,
    recent_vehicle_grades, save_chat_attachments, save_chat_message, save_intelligence_memory, write_intelligence_snapshot,
)
from .market_watchlist import (
    delete_watchlist_item, ignore_suggestion, matching_market_snapshot, nightly_watchlist_sync, radar_rows, record_market_interest, save_watchlist_item, set_watchlist_active,
    watchlist_items, watchlist_suggestions, watchlist_sync_due,
)
from .screens import Page, page_scroll, table_item
from .style import COLORS
from .widgets import Card, MetricCard, SectionHeader


def _money(value: object) -> str:
    return f"AED {float(value or 0):,.0f}"


def market_pace_bucket(median_days: object) -> str:
    """The owner-defined 45-day market-speed line; unknown data is never labelled fast."""
    try:return "fast" if float(median_days) < 45 else "slow"
    except (TypeError,ValueError):return "slow"


def _agent_avatar_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "assets" / "runway_agent_profile.png"


class AgentAvatar(QWidget):
    def __init__(self, size: int = 36):
        super().__init__(); self.setObjectName("agentAvatar"); self.setFixedSize(size, size); self.pixmap = QPixmap(str(_agent_avatar_path()))

    def paintEvent(self, event) -> None:
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing); painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath(); path.addEllipse(QRectF(self.rect())); painter.setClipPath(path)
        if not self.pixmap.isNull(): painter.drawPixmap(self.rect(), self.pixmap)
        else: painter.fillPath(path, COLORS["cyan"])


class WatchlistDialog(QDialog):
    def __init__(self, parent: QWidget, item: dict[str, object] | None = None):
        super().__init__(parent); self.item = item or {}; self.setWindowTitle("Edit watched vehicle" if item else "Add watched vehicle"); self.setMinimumWidth(480)
        root = QVBoxLayout(self); form = QFormLayout(); form.setSpacing(10)
        self.make = QLineEdit(str(self.item.get("make", ""))); self.model = QLineEdit(str(self.item.get("model", ""))); self.trim = QLineEdit(str(self.item.get("trim", "")))
        self.year_from = QSpinBox(); self.year_from.setRange(2000, 2035); self.year_from.setValue(int(self.item.get("year_from", 2021)))
        self.year_to = QSpinBox(); self.year_to.setRange(2000, 2035); self.year_to.setValue(int(self.item.get("year_to", 2022)))
        self.mileage_min = QSpinBox(); self.mileage_min.setRange(0, 1000000); self.mileage_min.setSingleStep(5000); self.mileage_min.setSpecialValueText("Any")
        self.mileage_max = QSpinBox(); self.mileage_max.setRange(0, 1000000); self.mileage_max.setSingleStep(5000); self.mileage_max.setSpecialValueText("Any")
        self.mileage_min.setValue(int(self.item.get("mileage_min") or 0)); self.mileage_max.setValue(int(self.item.get("mileage_max") or 0))
        self.gcc = QCheckBox("GCC only"); self.gcc.setChecked(bool(self.item.get("gcc_only", 1)))
        self.dealer = QCheckBox("Dealer / commercial only"); self.dealer.setChecked(bool(self.item.get("dealer_only", 1)))
        self.exclude = QCheckBox("Exclude Sharjah and Ajman"); self.exclude.setChecked(bool(self.item.get("exclude_sharjah_ajman", 1)))
        for label, widget in (("Make",self.make),("Model",self.model),("Exact trim",self.trim),("Year from",self.year_from),("Year to",self.year_to),("Mileage min · optional",self.mileage_min),("Mileage max · optional",self.mileage_max)):
            form.addRow(label, widget)
        form.addRow("", self.gcc); form.addRow("", self.dealer); form.addRow("", self.exclude); root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save); buttons.accepted.connect(self._accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def _accept(self) -> None:
        if not self.make.text().strip() or not self.model.text().strip() or not self.trim.text().strip():
            QMessageBox.information(self,"Vehicle required","Enter the make, model and exact trim."); return
        if self.year_from.value() > self.year_to.value():
            QMessageBox.information(self,"Check years","Year from cannot be later than year to."); return
        self.accept()

    def payload(self) -> dict[str, object]:
        return {"make":self.make.text().strip(),"model":self.model.text().strip(),"trim":self.trim.text().strip(),
                "year_from":self.year_from.value(),"year_to":self.year_to.value(),"gcc_only":self.gcc.isChecked(),
                "mileage_min":self.mileage_min.value() or None,"mileage_max":self.mileage_max.value() or None,
                "dealer_only":self.dealer.isChecked(),"exclude_sharjah_ajman":self.exclude.isChecked(),
                "active":bool(self.item.get("active",1))}


def openclaw_answer(payload: object) -> str:
    """Extract visible assistant text from OpenClaw's stable JSON envelope."""
    if not isinstance(payload, dict):
        return str(payload)
    output = payload.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") in {"output_text", "text"} and content.get("text"):
                    parts.append(str(content["text"]).strip())
        if parts:
            return "\n\n".join(parts)
    result = payload.get("result")
    if isinstance(result, dict):
        payloads = result.get("payloads")
        if isinstance(payloads, list):
            parts = [str(item.get("text", "")).strip() for item in payloads if isinstance(item, dict) and item.get("text")]
            if parts:
                return "\n\n".join(parts)
        meta = result.get("meta")
        if isinstance(meta, dict) and meta.get("finalAssistantVisibleText"):
            return str(meta["finalAssistantVisibleText"])
    for key in ("response", "text", "result"):
        if isinstance(payload.get(key), str):
            return str(payload[key])
    return json.dumps(payload, ensure_ascii=False)


class WorkerSignals(QObject):
    finished = Signal(str)
    failed = Signal(str)


class DealDriveSignals(QObject):
    progress = Signal(str)
    finished = Signal(str)
    failed = Signal(str)


class DealDriveJob(QRunnable):
    def __init__(self, db: Database, email: str, password: str, workspace_id: str, limit: int, sync: bool, subject: dict[str, object] | None = None):
        super().__init__(); self.db = db; self.email = email; self.password = password; self.workspace_id = workspace_id; self.limit = limit; self.sync = sync; self.subject = subject
        self.signals = DealDriveSignals()

    def run(self) -> None:
        try:
            self.signals.progress.emit("Signing in securely…")
            client = DealDriveClient(workspace_id=self.workspace_id); client.login(self.email, self.password)
            if not self.sync:
                count=client.verify_market_access()
                self.signals.finished.emit(f"Connected. Market-offer access verified · {count:,} UAE offers available."); return
            self.signals.progress.emit("Connected. Reading UAE market-offer IDs…")
            if self.subject:
                offers, _ = client.evaluate_subject(**self.subject, progress=self.signals.progress.emit)
            else:
                offers = client.fetch_market(limit=self.limit, progress=self.signals.progress.emit)
            self.signals.progress.emit("Saving a retained local snapshot…")
            save_market_snapshot(self.db, offers, "AE", self.limit)
            self.signals.finished.emit(f"Sync complete · {len(offers):,} market offers retained locally.")
        except Exception as error:
            self.signals.failed.emit(str(error))


class WatchlistSyncJob(QRunnable):
    def __init__(self, db: Database):
        super().__init__(); self.db=db; self.signals=DealDriveSignals()

    def run(self) -> None:
        try:
            count=nightly_watchlist_sync(self.db,self.signals.progress.emit)
            message=(f"Sync complete · {count} due watchlist vehicle{'s' if count!=1 else ''} refreshed." if count else
                     "Everything is current · all active vehicles are inside the 72-hour cooldown. No Deal Drive fetches used.")
            self.signals.finished.emit(message)
        except Exception as error:
            self.signals.failed.emit(str(error))


class OpenClawChatJob(QRunnable):
    """Runs only the fixed, owner-controlled OpenClaw agent over the dedicated SSH key."""

    def __init__(self, prompt: str, attachments: list[dict[str, object]] | None = None):
        super().__init__()
        self.prompt = prompt
        self.attachments = attachments or []
        self.signals = WorkerSignals()

    def run(self) -> None:
        key = Path.home() / ".ssh" / "dxb_runway_openclaw"
        if not key.exists():
            self.signals.failed.emit("AI connection is not configured on this computer. Offline grading still works.")
            return
        try:
            ssh = ["ssh", "-i", str(key), "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", "callumadmin@157.180.75.235"]
            if self.attachments:
                content: list[dict[str, object]] = [{"type": "input_text", "text": self.prompt}]
                for attachment in self.attachments:
                    path = Path(str(attachment["stored_path"]))
                    content.append({"type": "input_image", "source": {"type": "base64", "media_type": attachment["mime_type"], "data": base64.b64encode(path.read_bytes()).decode("ascii")}})
                request = json.dumps({
                    "model": "openclaw/dxb-runway",
                    "input": [{"type": "message", "role": "user", "content": content}],
                    "reasoning": {"effort": "medium"},
                    "max_output_tokens": 1800,
                })
                remote = "set -a; . ~/.openclaw/gateway.systemd.env >/dev/null 2>&1; set +a; curl -sS --fail-with-body --max-time 150 -H \"Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN\" -H \"Content-Type: application/json\" -H \"x-openclaw-agent-id: dxb-runway\" http://127.0.0.1:18789/v1/responses --data-binary @-"
                result = subprocess.run(ssh + [remote], input=request, capture_output=True, text=True, timeout=165, check=False)
            else:
                remote = "set -a; . ~/.openclaw/gateway.systemd.env >/dev/null 2>&1; set +a; openclaw agent --agent dxb-runway --thinking medium --json --message " + shlex.quote(self.prompt)
                result = subprocess.run(ssh + [remote], capture_output=True, text=True, timeout=150, check=False)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "OpenClaw did not answer")
            answer = result.stdout.strip()
            try:
                answer = openclaw_answer(json.loads(answer))
            except json.JSONDecodeError:
                pass
            self.signals.finished.emit(str(answer))
        except Exception as error:
            self.signals.failed.emit(str(error))


class IntelligenceSyncJob(QRunnable):
    def __init__(self, files: tuple[Path, Path, Path]):
        super().__init__(); self.files = files; self.signals = WorkerSignals()

    def run(self) -> None:
        key = Path.home() / ".ssh" / "dxb_runway_openclaw"
        if not key.exists():
            self.signals.failed.emit("Saved locally; VPS sync key is not installed on this computer."); return
        try:
            result = subprocess.run(
                ["scp", "-i", str(key), "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
                 *(str(path) for path in self.files[:2]),
                 "callumadmin@157.180.75.235:/home/callumadmin/.openclaw/workspace-dxb-runway/data/"],
                capture_output=True, text=True, timeout=300, check=False,
            )
            if result.returncode: raise RuntimeError(result.stderr.strip() or "Secure sync failed")
            context_result = subprocess.run(
                ["scp", "-i", str(key), "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", str(self.files[2]),
                 "callumadmin@157.180.75.235:/home/callumadmin/.openclaw/workspace-dxb-runway/USER.md"],
                capture_output=True, text=True, timeout=120, check=False,
            )
            if context_result.returncode: raise RuntimeError(context_result.stderr.strip() or "AI context sync failed")
            self.signals.finished.emit("Historical data securely synced to Runway AI.")
        except Exception as error:
            self.signals.failed.emit(f"Saved locally; AI sync failed: {error}")


class ChatComposer(QTextEdit):
    send_requested = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter} and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.send_requested.emit(); event.accept(); return
        super().keyPressEvent(event)


class AskRunwayPage(Page):
    """Dedicated conversational surface; the remote adviser still receives no callable tools."""

    def __init__(self, db: Database):
        super().__init__(db)
        self._busy = False; self._thinking_phase = 0; self._thinking_widget = None; self._pending_images: list[Path] = []
        self._typing_answer = ""; self._typing_index = 0; self._typing_label = None
        self.thinking_timer = QTimer(self); self.thinking_timer.setInterval(360); self.thinking_timer.timeout.connect(self._animate_thinking)
        self.typing_timer = QTimer(self); self.typing_timer.setInterval(12); self.typing_timer.timeout.connect(self._typing_step)
        outer = QVBoxLayout(self); outer.setContentsMargins(22,18,22,20); outer.setSpacing(12)
        head = QHBoxLayout(); head.addWidget(AgentAvatar(46), 0, Qt.AlignmentFlag.AlignTop); head.addWidget(SectionHeader("Ask Runway", "Your sharp, evidence-led buying adviser. Conversation and explicit owner instructions are remembered."), 1)
        self.state = QLabel("●  Ready"); self.state.setStyleSheet(f"color:{COLORS['green']};font-weight:800"); head.addWidget(self.state, 0, Qt.AlignmentFlag.AlignTop); outer.addLayout(head)
        safety = QLabel("PRIVATE · READ-ONLY · NO CRM OR EXTERNAL ACTIONS")
        safety.setStyleSheet(f"color:{COLORS['green']};background:#0d211c;border:1px solid #234a3c;border-radius:10px;padding:8px 12px;font-size:10px;font-weight:800;letter-spacing:1px")
        outer.addWidget(safety, 0, Qt.AlignmentFlag.AlignLeft)
        self.chat_scroll = QScrollArea(); self.chat_scroll.setWidgetResizable(True); self.chat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chat_scroll.setStyleSheet("QScrollArea{background:#080e16;border:1px solid #1c2938;border-radius:16px} QScrollArea > QWidget > QWidget{background:#080e16}")
        self.chat_host = QWidget(); self.chat_layout = QVBoxLayout(self.chat_host); self.chat_layout.setContentsMargins(26,26,26,26); self.chat_layout.setSpacing(18); self.chat_layout.addStretch()
        self.chat_scroll.setWidget(self.chat_host); outer.addWidget(self.chat_scroll, 1)
        composer = QFrame(); composer.setProperty("card", True); composer_outer = QVBoxLayout(composer); composer_outer.setContentsMargins(12,10,10,10); composer_outer.setSpacing(8)
        self.preview_frame = QFrame(); self.preview_layout = QHBoxLayout(self.preview_frame); self.preview_layout.setContentsMargins(0,0,0,0); self.preview_layout.setSpacing(8); self.preview_frame.hide(); composer_outer.addWidget(self.preview_frame)
        composer_layout = QHBoxLayout(); composer_layout.setContentsMargins(0,0,0,0); composer_layout.setSpacing(10)
        self.image_button = QPushButton("＋ Image"); self.image_button.setToolTip("Attach Deal Drive or other competitor screenshots"); self.image_button.setMinimumHeight(44); self.image_button.clicked.connect(self.choose_images); composer_layout.addWidget(self.image_button)
        self.chat_input = ChatComposer(); self.chat_input.setPlaceholderText("Message Runway…"); self.chat_input.setMinimumHeight(48); self.chat_input.setMaximumHeight(110)
        self.chat_input.send_requested.connect(self.send_chat); composer_layout.addWidget(self.chat_input, 1)
        self.chat_button = QPushButton("Send  ↑"); self.chat_button.setProperty("primary", True); self.chat_button.setMinimumHeight(44); self.chat_button.clicked.connect(self.send_chat); composer_layout.addWidget(self.chat_button)
        composer_outer.addLayout(composer_layout); outer.addWidget(composer)
        hint = QLabel("Attach up to 4 screenshots · image evidence can guide pricing but never changes the calculated grade")
        hint.setObjectName("muted"); hint.setAlignment(Qt.AlignmentFlag.AlignCenter); outer.addWidget(hint)
        self.refresh()

    def _clear_messages(self) -> None:
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget(): item.widget().hide(); item.widget().deleteLater()

    def _add_bubble(self, role: str, message: str, label_text: str | None = None, attachments: list[dict[str, object]] | None = None) -> tuple[QWidget, QLabel]:
        row = QWidget(); row_layout = QHBoxLayout(row); row_layout.setContentsMargins(0,0,0,0); row_layout.setSpacing(10)
        bubble = QFrame(); bubble.setMinimumWidth(520 if role == "assistant" else 280); bubble.setMaximumWidth(860); bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        bubble_layout = QVBoxLayout(bubble); bubble_layout.setContentsMargins(16,12,16,13); bubble_layout.setSpacing(6)
        speaker = QLabel(label_text or ("You" if role == "user" else "Runway")); speaker.setStyleSheet(f"color:{COLORS['cyan'] if role == 'assistant' else '#bdb1ff'};font-size:11px;font-weight:850")
        body = QLabel(message); body.setWordWrap(True); body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); body.setStyleSheet("font-size:14px;line-height:1.45")
        bubble_layout.addWidget(speaker)
        if attachments:
            gallery = QHBoxLayout(); gallery.setSpacing(8)
            for attachment in attachments[:4]:
                preview = QLabel(); preview.setFixedSize(150, 96); preview.setAlignment(Qt.AlignmentFlag.AlignCenter); preview.setStyleSheet("background:#070c13;border:1px solid #33465c;border-radius:9px")
                pixmap = QPixmap(str(attachment.get("stored_path", "")))
                if not pixmap.isNull(): preview.setPixmap(pixmap.scaled(preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                preview.setToolTip(str(attachment.get("original_name", "Screenshot"))); gallery.addWidget(preview)
            gallery.addStretch(); bubble_layout.addLayout(gallery)
        bubble_layout.addWidget(body)
        if role == "user":
            bubble.setObjectName("userBubble"); bubble.setStyleSheet("QFrame#userBubble{background:#201b3b;border:1px solid #4a3f79;border-radius:16px}"); row_layout.addStretch(); row_layout.addWidget(bubble)
        else:
            avatar = AgentAvatar(36)
            bubble.setObjectName("assistantBubble"); bubble.setStyleSheet("QFrame#assistantBubble{background:#101925;border:1px solid #27384c;border-radius:16px}"); row_layout.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop); row_layout.addWidget(bubble); row_layout.addStretch()
        self.chat_layout.insertWidget(self.chat_layout.count()-1, row); self._scroll_bottom(); return row, body

    def _scroll_bottom(self) -> None:
        QTimer.singleShot(0, lambda: self.chat_scroll.verticalScrollBar().setValue(self.chat_scroll.verticalScrollBar().maximum()))

    def refresh(self) -> None:
        if self._busy: return
        self._clear_messages(); messages = chat_conversation(self.db, 60)
        if not messages:
            self._add_bubble("assistant", "Tell me the make, model, trim, year, buying price and expected retail. I’ll give you the evidence, the risk and the brutal answer.", "Runway · ready")
        else:
            for message in messages: self._add_bubble(message["role"] if message["role"] in {"user", "assistant"} else "assistant", message["message"], attachments=message.get("attachments"))

    def choose_images(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Attach market screenshots", str(Path.home() / "Desktop"), "Images (*.png *.jpg *.jpeg *.webp)")
        for name in files:
            path = Path(name)
            if path in self._pending_images:
                continue
            if len(self._pending_images) >= 4:
                QMessageBox.information(self, "Four screenshots maximum", "Send these screenshots first, then attach more in your next message."); break
            if path.stat().st_size > 6 * 1024 * 1024 or QPixmap(str(path)).isNull():
                QMessageBox.warning(self, "Image not accepted", f"{path.name} must be a valid PNG, JPG or WebP under 6 MB."); continue
            self._pending_images.append(path)
        self._render_pending_images()

    def _render_pending_images(self) -> None:
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for path in self._pending_images:
            card = QFrame(); card.setStyleSheet("QFrame{background:#101925;border:1px solid #2b3d51;border-radius:10px}")
            layout = QHBoxLayout(card); layout.setContentsMargins(7,6,7,6); layout.setSpacing(7)
            thumb = QLabel(); thumb.setFixedSize(58,42); pixmap = QPixmap(str(path)); thumb.setPixmap(pixmap.scaled(thumb.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)); layout.addWidget(thumb)
            name = QLabel(path.name); name.setMaximumWidth(150); name.setToolTip(path.name); layout.addWidget(name)
            remove = QPushButton("×"); remove.setFixedSize(26,26); remove.setToolTip("Remove screenshot"); remove.clicked.connect(lambda checked=False, selected=path: self._remove_pending_image(selected)); layout.addWidget(remove)
            self.preview_layout.addWidget(card)
        self.preview_layout.addStretch(); self.preview_frame.setVisible(bool(self._pending_images))

    def _remove_pending_image(self, path: Path) -> None:
        self._pending_images = [item for item in self._pending_images if item != path]; self._render_pending_images()

    def send_chat(self) -> None:
        question = self.chat_input.toPlainText().strip()
        if (not question and not self._pending_images) or self._busy: return
        if not question: question = "Analyse these competitor listings and advise how we should currently price the vehicle."
        pending = list(self._pending_images); self._pending_images.clear(); self._render_pending_images()
        self._busy = True; self.chat_input.clear(); self.chat_input.setEnabled(False); self.image_button.setEnabled(False); self.chat_button.setEnabled(False); self.chat_button.setText("Working…")
        message_id = save_chat_message(self.db, "user", question); attachments = save_chat_attachments(self.db, message_id, pending)
        self._add_bubble("user", question, attachments=attachments)
        learned = learning_directive(question)
        if learned:
            save_intelligence_memory(self.db, learned); self._sync_ai_context()
            self._add_bubble("assistant", f"Memory saved: {learned}", "Runway · memory")
        evidence = chat_evidence(self.db)
        if "deal" in question.casefold() and "drive" in question.casefold() and not evidence.get("deal_drive_current_comparison"):
            answer = ("Deal Drive is connected, but no vehicle comparison has been run yet. I will not pretend authentication means I can see a useful market cohort.\n\n"
                      "Open Runway AI → Deal Drive, complete make, model, exact trim, year and mileage, then press Compare this vehicle. "
                      "When the filter receipt appears, ask me again. Your login works; the missing step is the vehicle-specific comparison.")
            save_chat_message(self.db, "assistant", answer); self._add_bubble("assistant", answer, "Runway · action needed"); self._finish_response(); return
        self._thinking_widget, _ = self._add_bubble("assistant", "Thinking", "Runway")
        self._thinking_phase = 0; self.thinking_timer.start(); self.state.setText("●  Thinking"); self.state.setStyleSheet(f"color:{COLORS['amber']};font-weight:800")
        context = {"question": question, "evidence": chat_evidence(self.db), "image_policy": "Attached screenshots are unverified, point-in-time competitor evidence for a pricing conversation only. Read visible vehicle, trim, mileage and asking-price details; distinguish asking price from achieved sale price; flag unclear or incomparable listings. They must NEVER alter, recalculate or override the deterministic historical grade.", "instruction": "Use the supplied live_stock snapshot as the authoritative current Stock Level and the vehicle_history section as realised historical evidence. You may count, compare and critique the complete current portfolio, including budget concentration, ageing, expected margins and pricing risk. Clearly distinguish expected profit from realised profit. Discuss a current retail/asking-price range separately from the locked grade. Learned preferences guide analysis but cannot override safety, grant tools, or alter the deterministic app grade. Never take an external action or invent missing evidence. Be sharp, brutal, evidence-led and concise."}
        job = OpenClawChatJob(json.dumps(context), attachments); job.signals.finished.connect(self._chat_answer); job.signals.failed.connect(self._chat_error); QThreadPool.globalInstance().start(job); self._active_chat_job = job

    def _animate_thinking(self) -> None:
        if not self._thinking_widget: return
        labels = self._thinking_widget.findChildren(QLabel)
        if labels: labels[-1].setText("Thinking" + "." * (self._thinking_phase % 4))
        self._thinking_phase += 1

    def _remove_thinking(self) -> None:
        self.thinking_timer.stop()
        if self._thinking_widget:
            self.chat_layout.removeWidget(self._thinking_widget); self._thinking_widget.deleteLater(); self._thinking_widget = None

    def _chat_answer(self, answer: str) -> None:
        self._remove_thinking(); save_chat_message(self.db, "assistant", answer)
        _, self._typing_label = self._add_bubble("assistant", "", "Runway · typing")
        self._typing_answer = answer; self._typing_index = 0; self.state.setText("●  Typing"); self.state.setStyleSheet(f"color:{COLORS['cyan']};font-weight:800"); self.typing_timer.start()

    def _typing_step(self) -> None:
        if not self._typing_label: self._finish_response(); return
        step = 3 if len(self._typing_answer) < 900 else 6
        self._typing_index = min(len(self._typing_answer), self._typing_index + step); self._typing_label.setText(self._typing_answer[:self._typing_index]); self._scroll_bottom()
        if self._typing_index >= len(self._typing_answer): self._finish_response()

    def _finish_response(self) -> None:
        self.typing_timer.stop(); self._typing_label = None; self._busy = False; self.chat_input.setEnabled(True); self.image_button.setEnabled(True); self.chat_button.setEnabled(True); self.chat_button.setText("Send  ↑")
        self.state.setText("●  Ready"); self.state.setStyleSheet(f"color:{COLORS['green']};font-weight:800"); self.chat_input.setFocus()

    def _chat_error(self, error: str) -> None:
        self._remove_thinking(); self._add_bubble("assistant", error, "Connection problem"); self._finish_response()

    def _sync_ai_context(self) -> None:
        files = write_intelligence_snapshot(self.db); sync = IntelligenceSyncJob(files); QThreadPool.globalInstance().start(sync); self._active_memory_sync_job = sync


class IntelligencePage(Page):
    def __init__(self, db: Database):
        super().__init__(db)
        outer = QVBoxLayout(self); outer.setContentsMargins(20,18,20,20); outer.setSpacing(12)
        outer.addWidget(SectionHeader("Buying intelligence", "Brutal, evidence-led vehicle decisions. The grade is calculated locally; AI explains it but cannot alter it."))
        self.tabs = QTabWidget(); outer.addWidget(self.tabs, 1)
        self.tabs.addTab(self._opportunity_tab(), "Opportunity check")
        self.tabs.addTab(self._data_tab(), "Historical data")
        self.tabs.addTab(self._grades_tab(), "Vehicle grades")
        self.tabs.addTab(self._watchlist_tab(), "Market Watchlist")
        self.tabs.addTab(self._velocity_tab(), "Market Radar")
        self.tabs.addTab(self._deal_drive_tab(), "Deal Drive")
        self.tabs.addTab(self._memory_tab(), "Memory")
        self.refresh()

    def _opportunity_tab(self) -> QWidget:
        content = QWidget(); root = QVBoxLayout(content); root.setContentsMargins(4,14,4,4); root.setSpacing(12)
        form_card = Card(); grid = QGridLayout(form_card); grid.setContentsMargins(18,16,18,16); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(10)
        self.make = QLineEdit(); self.make.setPlaceholderText("Audi")
        self.model = QLineEdit(); self.model.setPlaceholderText("Q8")
        self.trim = QLineEdit(); self.trim.setPlaceholderText("S line")
        self.year = QSpinBox(); self.year.setRange(0, 2035); self.year.setSpecialValueText("Unknown"); self.year.setValue(0)
        self.mileage = QSpinBox(); self.mileage.setRange(0, 1000000); self.mileage.setSuffix(" km"); self.mileage.setSingleStep(1000)
        self.buy_price = MoneyBox(maximum=100_000_000); self.retail_price = MoneyBox(maximum=100_000_000); self.prep = MoneyBox(maximum=5_000_000)
        fields = [("Make", self.make), ("Model", self.model), ("Trim", self.trim), ("Model year", self.year), ("Mileage", self.mileage),
                  ("Purchase price · AED", self.buy_price), ("Expected sale · AED", self.retail_price), ("Prep allowance · AED", self.prep)]
        for index, (label, widget) in enumerate(fields):
            row, column = divmod(index, 2); grid.addWidget(QLabel(label), row * 2, column); grid.addWidget(widget, row * 2 + 1, column)
        check = QPushButton("Analyse opportunity"); check.setProperty("primary", True); check.clicked.connect(self.run_analysis); grid.addWidget(check, 10, 1)
        root.addWidget(form_card)
        self.result = Card(); result_layout = QVBoxLayout(self.result); result_layout.setContentsMargins(20,18,20,18); result_layout.setSpacing(10)
        self.result_title = QLabel("Enter a vehicle to get an evidence-led decision"); self.result_title.setStyleSheet("font-size:22px;font-weight:900"); result_layout.addWidget(self.result_title)
        self.result_summary = QLabel("No optimism, no guesswork, no invented confidence."); self.result_summary.setObjectName("muted"); self.result_summary.setWordWrap(True); result_layout.addWidget(self.result_summary)
        self.metrics = QLabel(); self.metrics.setWordWrap(True); result_layout.addWidget(self.metrics)
        self.factor_table = QTableWidget(0, 3); self.factor_table.setHorizontalHeaderLabels(["FACTOR", "WEIGHT", "SCORE"]); self.factor_table.horizontalHeader().setStretchLastSection(True); self.factor_table.setMinimumHeight(225); result_layout.addWidget(self.factor_table)
        root.addWidget(self.result); root.addStretch()
        return page_scroll(content)

    def _data_tab(self) -> QWidget:
        content = QWidget(); root = QVBoxLayout(content); root.setContentsMargins(4,14,4,4); root.setSpacing(12)
        top = Card(); line = QHBoxLayout(top); line.setContentsMargins(18,16,18,16)
        copy = QVBoxLayout(); title = QLabel("Import the manager's historical stock data"); title.setStyleSheet("font-size:17px;font-weight:800"); copy.addWidget(title)
        note = QLabel("CSV, TSV, TXT, XLS or XLSX. Mixed columns are sorted automatically; every original value and file is retained."); note.setObjectName("muted"); note.setWordWrap(True); copy.addWidget(note); line.addLayout(copy, 1)
        import_button = QPushButton("＋ Import file"); import_button.setProperty("primary", True); import_button.clicked.connect(self.import_file); line.addWidget(import_button)
        root.addWidget(top)
        self.import_status = QLabel("No import selected."); self.import_status.setObjectName("muted"); root.addWidget(self.import_status)
        self.batch_table = QTableWidget(0, 6); self.batch_table.setHorizontalHeaderLabels(["FILE", "IMPORTED", "ROWS", "USABLE", "REVIEW", "DUPLICATES"]); self.batch_table.horizontalHeader().setStretchLastSection(True); root.addWidget(self.batch_table, 1)
        return content

    def _grades_tab(self) -> QWidget:
        content = QWidget(); root = QVBoxLayout(content); root.setContentsMargins(4,14,4,4)
        self.grades_table = QTableWidget(0, 9)
        self.grades_table.setHorizontalHeaderLabels(["VEHICLE", "TRIM", "GRADE", "DECISION", "CONFIDENCE", "SAMPLES", "MEDIAN DAYS", "AVG MARGIN", "TRIM POSITION"])
        self.grades_table.horizontalHeader().setStretchLastSection(True); root.addWidget(self.grades_table)
        return content

    def _memory_tab(self) -> QWidget:
        content = QWidget(); root = QVBoxLayout(content); root.setContentsMargins(4,14,4,4); root.setSpacing(12)
        header = Card(); header_layout = QVBoxLayout(header); header_layout.setContentsMargins(18,16,18,16)
        header_layout.addWidget(SectionHeader("What Runway remembers", "Clear owner instructions are retained across restarts and included in every future analysis. Memory guides the AI explanation; the tested local grade remains authoritative."))
        add_line = QHBoxLayout(); self.memory_input = QLineEdit(); self.memory_input.setPlaceholderText("Example: Always include seasonality and sample size in the recommendation")
        self.memory_input.returnPressed.connect(self.add_memory); add_line.addWidget(self.memory_input, 1)
        add_button = QPushButton("＋ Add memory"); add_button.setProperty("primary", True); add_button.clicked.connect(self.add_memory); add_line.addWidget(add_button); header_layout.addLayout(add_line)
        self.memory_status = QLabel("Only you can approve lasting memory. It cannot grant tools or external access."); self.memory_status.setObjectName("muted"); self.memory_status.setWordWrap(True); header_layout.addWidget(self.memory_status); root.addWidget(header)
        memory_card = Card(); memory_layout = QVBoxLayout(memory_card); memory_layout.setContentsMargins(16,15,16,15)
        memory_head = QHBoxLayout(); memory_head.addWidget(QLabel("ACTIVE LEARNED RULES")); memory_head.addStretch()
        remove = QPushButton("Forget selected"); remove.clicked.connect(self.forget_selected_memory); memory_head.addWidget(remove); memory_layout.addLayout(memory_head)
        self.memory_table = QTableWidget(0, 3); self.memory_table.setHorizontalHeaderLabels(["LEARNED", "SOURCE", "UPDATED"])
        self.memory_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.memory_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.memory_table.verticalHeader().hide(); self.memory_table.horizontalHeader().setStretchLastSection(True); self.memory_table.setWordWrap(True); memory_layout.addWidget(self.memory_table)
        root.addWidget(memory_card, 1)
        return content

    def _watchlist_tab(self) -> QWidget:
        content=QWidget(); root=QVBoxLayout(content); root.setContentsMargins(4,14,4,4); root.setSpacing(12)
        header=Card(); head=QHBoxLayout(header); head.setContentsMargins(18,16,18,16)
        copy=QVBoxLayout(); copy.addWidget(SectionHeader("Market Watchlist","Only these owner-approved vehicle cohorts are monitored through Deal Drive every night."))
        note=QLabel("Simple and curated: Runway never adds suggestions without your approval."); note.setObjectName("muted"); copy.addWidget(note); head.addLayout(copy,1)
        self.watch_sync=QPushButton("↻ Sync now"); self.watch_sync.clicked.connect(self._sync_watchlist_now); head.addWidget(self.watch_sync)
        add=QPushButton("＋ Add vehicle"); add.setProperty("primary",True); add.clicked.connect(self._add_watchlist); head.addWidget(add); root.addWidget(header)
        self.watch_sync_status=QLabel("Ready to sync active vehicles."); self.watch_sync_status.setObjectName("muted"); self.watch_sync_status.setWordWrap(True); root.addWidget(self.watch_sync_status)
        actions=QHBoxLayout(); edit=QPushButton("Edit selected"); edit.clicked.connect(self._edit_watchlist); actions.addWidget(edit)
        self.watch_pause=QPushButton("Pause / resume"); self.watch_pause.clicked.connect(self._toggle_watchlist); actions.addWidget(self.watch_pause)
        remove=QPushButton("Delete selected"); remove.clicked.connect(self._delete_watchlist); actions.addWidget(remove); actions.addStretch(); root.addLayout(actions)
        self.watchlist_table=QTableWidget(0,7); self.watchlist_table.setHorizontalHeaderLabels(["VEHICLE","TRIM","YEARS","RULES","MILEAGE","STATUS","LAST SYNC"])
        self.watchlist_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.watchlist_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.watchlist_table.verticalHeader().hide(); self.watchlist_table.horizontalHeader().setStretchLastSection(True); root.addWidget(self.watchlist_table,1)
        suggestion=Card(); suggestion_layout=QVBoxLayout(suggestion); suggestion_layout.setContentsMargins(16,14,16,14)
        suggestion_layout.addWidget(SectionHeader("Suggestions","Vehicles appearing at least three times in Alba's clean historical data."))
        self.watch_suggestion=QLabel("No suggestion yet."); self.watch_suggestion.setWordWrap(True); suggestion_layout.addWidget(self.watch_suggestion)
        suggestion_actions=QHBoxLayout(); self.watch_add_suggestion=QPushButton("Add to Watchlist"); self.watch_add_suggestion.clicked.connect(self._accept_watchlist_suggestion); suggestion_actions.addWidget(self.watch_add_suggestion)
        self.watch_ignore_suggestion=QPushButton("Ignore"); self.watch_ignore_suggestion.clicked.connect(self._ignore_watchlist_suggestion); suggestion_actions.addWidget(self.watch_ignore_suggestion); suggestion_actions.addStretch(); suggestion_layout.addLayout(suggestion_actions); root.addWidget(suggestion)
        return content

    def _velocity_tab(self) -> QWidget:
        content=QWidget(); root=QVBoxLayout(content); root.setContentsMargins(4,14,4,4); root.setSpacing(12)
        header=Card(); header_layout=QHBoxLayout(header); header_layout.setContentsMargins(18,16,18,16)
        copy=QVBoxLayout(); copy.addWidget(SectionHeader("Market Radar", "Your 45-day buying board · market age decides the lane; score explains the strength."))
        self.velocity_status=QLabel("Building history"); self.velocity_status.setObjectName("muted"); self.velocity_status.setWordWrap(True); copy.addWidget(self.velocity_status); header_layout.addLayout(copy,1)
        schedule=QLabel("AUTOMATIC SYNC\nEvery day · 23:59 Dubai time"); schedule.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter); schedule.setStyleSheet(f"color:{COLORS['green']};font-weight:850"); header_layout.addWidget(schedule); root.addWidget(header)
        scoreboard=QHBoxLayout(); scoreboard.setSpacing(10)
        self.radar_fast_metric=MetricCard("Fast lane","0","Under 45 median days",COLORS["green"]); scoreboard.addWidget(self.radar_fast_metric)
        self.radar_slow_metric=MetricCard("Risk zone","0","45+ median days",COLORS["red"]); scoreboard.addWidget(self.radar_slow_metric)
        self.radar_age_metric=MetricCard("Watchlist pace","—","Median age across synced cohorts",COLORS["cyan"]); scoreboard.addWidget(self.radar_age_metric)
        root.addLayout(scoreboard)
        fast_card=Card(); fast_layout=QVBoxLayout(fast_card); fast_layout.setContentsMargins(14,13,14,14)
        fast_title=SectionHeader("⚡ FAST LANE · UNDER 45 DAYS", "Priority hunting ground — verify price, margin and sample confidence before buying"); fast_layout.addWidget(fast_title)
        self.velocity_fast=self._radar_table(); fast_layout.addWidget(self.velocity_fast); root.addWidget(fast_card,1)
        slow_card=Card(); slow_layout=QVBoxLayout(slow_card); slow_layout.setContentsMargins(14,13,14,14)
        slow_title=SectionHeader("⚠ RISK ZONE · 45+ DAYS", "Slower market — demand a stronger margin or walk away"); slow_layout.addWidget(slow_title)
        self.velocity_slow=self._radar_table(); slow_layout.addWidget(self.velocity_slow); root.addWidget(slow_card,1)
        note=QLabel("PACE RULE · Median listing age controls the lane. Market Score (0–100) adds context from exits, supply, price stability, reductions and sample strength. A market exit is not a confirmed sale."); note.setObjectName("muted"); note.setWordWrap(True); root.addWidget(note)
        return content

    def _radar_table(self) -> QTableWidget:
        table=QTableWidget(0,8); table.setHorizontalHeaderLabels(["VEHICLE COHORT","PACE","MEDIAN AGE","MARKET SCORE","COMPARABLES","MEDIAN ASK","MOVEMENT","CONFIDENCE"])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide(); table.setAlternatingRowColors(True); table.setMinimumHeight(175)
        header=table.horizontalHeader(); header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); header.setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6,QHeaderView.ResizeMode.Stretch); return table

    def _deal_drive_tab(self) -> QWidget:
        content = QWidget(); root = QVBoxLayout(content); root.setContentsMargins(4,14,4,4); root.setSpacing(12)
        intro = Card(); box = QVBoxLayout(intro); box.setContentsMargins(18,16,18,16); box.setSpacing(10)
        box.addWidget(SectionHeader("Deal Drive market connection", "Read-only UAE listing evidence. Every sync is retained; previous snapshots are never overwritten."))
        boundary = QLabel("LOCKED SCOPE · MARKET OFFERS ONLY · NO CRM, CONTACTS, VIN, REGISTRATION OR COMPANY RECORDS")
        boundary.setWordWrap(True); boundary.setStyleSheet(f"color:{COLORS['green']};font-weight:800")
        box.addWidget(boundary)
        form = QGridLayout(); form.setHorizontalSpacing(12); form.setVerticalSpacing(8)
        self.dd_email = QLineEdit(self.db.get_setting("deal_drive_email")); self.dd_email.setPlaceholderText("Partner API email")
        self.dd_password = QLineEdit(); self.dd_password.setEchoMode(QLineEdit.EchoMode.Password); self.dd_password.setPlaceholderText("Stored in macOS Keychain after a successful test")
        self.dd_workspace = QLineEdit(self.db.get_setting("deal_drive_workspace_id")); self.dd_workspace.setPlaceholderText("Provided by Deal Drive or visible as X-DD-WorkspaceId")
        self.dd_limit = QSpinBox(); self.dd_limit.setRange(100, 1000); self.dd_limit.setSingleStep(100); self.dd_limit.setValue(min(1000, int(self.db.get_setting("deal_drive_limit", "1000"))))
        form.addWidget(QLabel("Email"),0,0); form.addWidget(self.dd_email,1,0); form.addWidget(QLabel("Password"),0,1); form.addWidget(self.dd_password,1,1)
        form.addWidget(QLabel("Workspace ID"),2,0); form.addWidget(self.dd_workspace,3,0); form.addWidget(QLabel("Nightly market sample · API max 1,000"),2,1); form.addWidget(self.dd_limit,3,1); box.addLayout(form)
        try: saved_subject = json.loads(self.db.get_setting("deal_drive_last_subject", "{}"))
        except json.JSONDecodeError: saved_subject = {}
        subject_card = Card(); subject_layout = QGridLayout(subject_card); subject_layout.setContentsMargins(14,12,14,12); subject_layout.setHorizontalSpacing(10); subject_layout.setVerticalSpacing(7)
        subject_title = QLabel("VEHICLE TO COMPARE"); subject_title.setStyleSheet("font-weight:850"); subject_layout.addWidget(subject_title,0,0,1,5)
        self.dd_make = QLineEdit(str(saved_subject.get("make", ""))); self.dd_make.setPlaceholderText("Audi")
        self.dd_model = QLineEdit(str(saved_subject.get("model", ""))); self.dd_model.setPlaceholderText("Q8")
        self.dd_trim = QLineEdit(str(saved_subject.get("trim", ""))); self.dd_trim.setPlaceholderText("Exact trim, e.g. S line")
        self.dd_year = QSpinBox(); self.dd_year.setRange(2010,2035); self.dd_year.setValue(int(saved_subject.get("year", 2021)))
        self.dd_mileage = QSpinBox(); self.dd_mileage.setRange(0,1000000); self.dd_mileage.setSingleStep(1000); self.dd_mileage.setSuffix(" km"); self.dd_mileage.setValue(int(saved_subject.get("mileage_km",0)))
        for column,(label,widget) in enumerate((("Make",self.dd_make),("Model",self.dd_model),("Exact trim",self.dd_trim),("Year",self.dd_year),("Mileage",self.dd_mileage))):
            subject_layout.addWidget(QLabel(label),1,column); subject_layout.addWidget(widget,2,column)
        copy_subject = QPushButton("Copy from Opportunity check"); copy_subject.clicked.connect(self._copy_deal_drive_subject); subject_layout.addWidget(copy_subject,3,0,1,2)
        subject_note = QLabel("Required before market evidence becomes visible to Ask Runway. The comparison uses this year and the following year."); subject_note.setObjectName("muted"); subject_note.setWordWrap(True); subject_layout.addWidget(subject_note,3,2,1,3)
        box.addWidget(subject_card)
        policy = Card(); policy_layout = QGridLayout(policy); policy_layout.setContentsMargins(14,12,14,12)
        policy_layout.addWidget(QLabel("ACTIVE COMPARISON POLICY"),0,0,1,3)
        for column, text in enumerate(("✓ Dealers/commercial only", "✓ Subject year + 1", "✓ Exact trim first")): policy_layout.addWidget(QLabel(text),1,column)
        for column, text in enumerate(("✓ Sharjah & Ajman excluded", "✓ Mileage ±25% / minimum 15k km", "✓ Likely reposts collapsed")): policy_layout.addWidget(QLabel(text),2,column)
        policy_layout.addWidget(QLabel("✓ Live asking and historical sold evidence remain separate · median/weighted median is primary"),3,0,1,3)
        self.dd_allow_imports = QCheckBox("Explicitly allow non-GCC/import vehicles for this comparison")
        self.dd_allow_imports.setChecked(self.db.get_setting("deal_drive_allow_imports", "0") == "1"); policy_layout.addWidget(self.dd_allow_imports,4,0,1,3); box.addWidget(policy)
        actions = QHBoxLayout(); self.dd_test = QPushButton("Test connection"); self.dd_test.clicked.connect(lambda: self._run_deal_drive(False)); actions.addWidget(self.dd_test)
        self.dd_sync = QPushButton("Compare this vehicle"); self.dd_sync.setProperty("primary", True); self.dd_sync.clicked.connect(lambda: self._run_deal_drive(True)); actions.addWidget(self.dd_sync)
        forget = QPushButton("Forget login"); forget.clicked.connect(self._forget_deal_drive); actions.addWidget(forget); actions.addStretch(); box.addLayout(actions); root.addWidget(intro)
        status_card = Card(); status_layout = QGridLayout(status_card); status_layout.setContentsMargins(18,16,18,16)
        self.dd_connection = QLabel("NOT CONFIGURED"); self.dd_connection.setStyleSheet(f"font-size:18px;font-weight:900;color:{COLORS['amber']}")
        self.dd_ready = QLabel("NO COMPARISON YET"); self.dd_ready.setStyleSheet(f"font-size:18px;font-weight:900;color:{COLORS['amber']}")
        self.dd_last = QLabel("Never compared"); self.dd_counts = QLabel("0 snapshots · 0 retained offers")
        status_layout.addWidget(QLabel("ACCOUNT"),0,0); status_layout.addWidget(QLabel("ASK RUNWAY MARKET DATA"),0,1); status_layout.addWidget(QLabel("RETAINED EVIDENCE"),0,2)
        status_layout.addWidget(self.dd_connection,1,0); status_layout.addWidget(self.dd_ready,1,1); status_layout.addWidget(self.dd_counts,1,2); status_layout.addWidget(self.dd_last,2,1); root.addWidget(status_card)
        log_card = Card(); log_layout = QVBoxLayout(log_card); log_layout.setContentsMargins(16,14,16,14); log_layout.addWidget(QLabel("SYNC ACTIVITY"))
        self.dd_log = QTextEdit(); self.dd_log.setReadOnly(True); self.dd_log.setMaximumHeight(180); self.dd_log.setPlaceholderText("Connection and import progress will appear here."); log_layout.addWidget(self.dd_log); root.addWidget(log_card); root.addStretch()
        return page_scroll(content)

    def _dd_message(self, message: str) -> None:
        self.dd_log.append(f"{datetime.now().strftime('%H:%M:%S')}  {message}")

    def _copy_deal_drive_subject(self) -> None:
        self.dd_make.setText(self.make.text()); self.dd_model.setText(self.model.text()); self.dd_trim.setText(self.trim.text())
        if self.year.value(): self.dd_year.setValue(self.year.value())
        self.dd_mileage.setValue(self.mileage.value())

    def _run_deal_drive(self, sync: bool) -> None:
        email = self.dd_email.text().strip(); password = self.dd_password.text(); workspace_id = self.dd_workspace.text().strip()
        if not email:
            QMessageBox.information(self, "Email required", "Enter the Deal Drive Partner API email."); return
        if not password: password = KeychainCredentials().load(email) or ""
        if not password:
            QMessageBox.information(self, "Password required", "Enter the Partner API password once; it will be saved to macOS Keychain only after a successful connection."); return
        if not workspace_id:
            QMessageBox.information(self, "Workspace ID required", "Enter the Deal Drive Workspace ID. It is sent as the required X-DD-WorkspaceId header."); return
        self.dd_test.setEnabled(False); self.dd_sync.setEnabled(False); self._dd_message("Starting read-only connection test…" if not sync else "Starting read-only UAE market sync…")
        subject = None
        if sync:
            if not self.dd_make.text().strip() or not self.dd_model.text().strip() or not self.dd_trim.text().strip() or not self.dd_year.value() or not self.dd_mileage.value():
                self.dd_test.setEnabled(True); self.dd_sync.setEnabled(True)
                QMessageBox.information(self, "Vehicle details required", "Complete make, model, exact trim, year and mileage in the Vehicle to compare box above."); return
            subject = {"make":self.dd_make.text().strip(),"model":self.dd_model.text().strip(),"trim":self.dd_trim.text().strip(),"year":self.dd_year.value(),
                       "mileage_km":self.dd_mileage.value(),"allow_imports":self.dd_allow_imports.isChecked()}
        self.db.set_setting("deal_drive_allow_imports", int(self.dd_allow_imports.isChecked()))
        self.db.set_setting("deal_drive_workspace_id", workspace_id)
        job = DealDriveJob(self.db, email, password, workspace_id, self.dd_limit.value(), sync, subject)
        job.signals.progress.connect(self._dd_message)
        job.signals.failed.connect(self._deal_drive_failed)
        job.signals.finished.connect(lambda message, e=email, p=password: self._deal_drive_finished(message, e, p))
        self._active_deal_drive_job = job; QThreadPool.globalInstance().start(job)

    def _deal_drive_finished(self, message: str, email: str, password: str) -> None:
        try: KeychainCredentials().save(email, password)
        except DealDriveError as error: self._dd_message(str(error))
        self.db.set_setting("deal_drive_email", email); self.db.set_setting("deal_drive_workspace_id", self.dd_workspace.text().strip()); self.db.set_setting("deal_drive_limit", self.dd_limit.value())
        if getattr(self, "_active_deal_drive_job", None) and self._active_deal_drive_job.subject:
            saved = dict(self._active_deal_drive_job.subject); saved.pop("allow_imports", None)
            self.db.set_setting("deal_drive_last_subject", json.dumps(saved))
            comparison = comparison_summary(self.db, **saved)
            receipt = comparison.get("filter_receipt", {})
            live = comparison.get("live_market_asking", {}); history = comparison.get("historical_sold_or_removed", {})
            self._dd_message(f"FILTER RECEIPT · {receipt.get('vehicle')} · {receipt.get('trim_rule')} · {receipt.get('regional_spec')} · {receipt.get('seller')}")
            self._dd_message(f"RESULT · live asking {live.get('samples',0)} samples / median {_money(live.get('median_price_aed'))} · sold-or-removed history {history.get('samples',0)} samples / median {_money(history.get('median_price_aed'))}")
            self.dd_ready.setText("COMPARISON READY"); self.dd_ready.setStyleSheet(f"font-size:18px;font-weight:900;color:{COLORS['green']}")
        self.dd_password.clear(); self.dd_connection.setText("CONNECTED"); self.dd_connection.setStyleSheet(f"font-size:18px;font-weight:900;color:{COLORS['green']}")
        self._dd_message(message); self.dd_test.setEnabled(True); self.dd_sync.setEnabled(True); self._refresh_deal_drive()

    def _deal_drive_failed(self, message: str) -> None:
        self.dd_connection.setText("CONNECTION FAILED"); self.dd_connection.setStyleSheet(f"font-size:18px;font-weight:900;color:{COLORS['red']}")
        self._dd_message(f"FAILED · {message}"); self.dd_test.setEnabled(True); self.dd_sync.setEnabled(True)

    def _forget_deal_drive(self) -> None:
        email = self.dd_email.text().strip() or self.db.get_setting("deal_drive_email")
        if email: KeychainCredentials().delete(email)
        self.db.set_setting("deal_drive_email", ""); self.db.set_setting("deal_drive_workspace_id", ""); self.dd_email.clear(); self.dd_password.clear(); self.dd_workspace.clear(); self.dd_connection.setText("NOT CONFIGURED"); self._dd_message("Saved Keychain login and Workspace ID removed. Retained market snapshots were kept.")

    def _refresh_deal_drive(self) -> None:
        if not hasattr(self, "dd_counts"): return
        state = sync_status(self.db); latest = state["latest"]
        self.dd_counts.setText(f"{state['snapshots']:,} snapshots · {state['retained_offers']:,} retained offers")
        self.dd_last.setText(str(latest["completed_at"] or latest["started_at"]) if latest else "Never synced")
        if latest and latest["status"] == "success":
            self.dd_ready.setText("COMPARISON READY"); self.dd_ready.setStyleSheet(f"font-size:18px;font-weight:900;color:{COLORS['green']}")

    def run_analysis(self) -> None:
        if not self.make.text().strip() or not self.model.text().strip():
            QMessageBox.information(self, "Vehicle required", "Enter at least the make and model."); return
        record_market_interest(self.db,self.make.text(),self.model.text(),self.trim.text(),self.year.value() or None)
        result = analyse_opportunity(
            self.db, make=self.make.text(), model=self.model.text(), trim=self.trim.text(), model_year=self.year.value() or None,
            purchase_price_aed=self.buy_price.value() if self.buy_price.value() else None,
            expected_sale_price_aed=self.retail_price.value() if self.retail_price.value() else None,
            preparation_cost_aed=self.prep.value(),
        )
        grade, decision = result["grade"], result["decision"]
        color = COLORS["green"] if decision == "BUY" else COLORS["amber"] if decision == "NEGOTIATE" else COLORS["red"]
        self.result_title.setText(f"{grade}  ·  {decision}"); self.result_title.setStyleSheet(f"font-size:26px;font-weight:900;color:{color}")
        self.result_summary.setText(result["summary"])
        if result.get("sample_size", 0):
            proposed = f" · Proposed profit {_money(result['proposed_profit_aed'])}" if result.get("proposed_profit_aed") is not None else ""
            self.metrics.setText(f"Confidence {result['confidence'].upper()} · {result['identical_trim_samples']} identical trim / {result['sample_size']} comparable · Median {result['median_days']:.0f} days · Historical margin {_money(result['average_profit_aed'])} · ROI {result['average_roi_percent']:.1f}%{proposed}\n{result['trim_position']}")
        else:
            self.metrics.setText("Import matching sold history before committing capital.")
        market=matching_market_snapshot(self.db,self.make.text(),self.model.text(),self.trim.text(),self.year.value() or None)
        if market:
            self.metrics.setText(self.metrics.text()+f"\n\nWATCHLIST MARKET · {market['year_from']}–{market['year_to']} · {float(market['score']):.0f}/100 {market['label']} · {market['current_listings']} comparables · median {_money(market['median_asking_aed'])} · median age {float(market['median_listing_age_days'] or 0):.0f} days · sample {market['sample_size']} · confidence {market['confidence']}")
        factors = result.get("factors", {}); weights = result.get("weights", {}); self.factor_table.setRowCount(len(factors))
        labels = {"time_to_sell": "Time to sell", "sample_confidence": "Sample confidence", "margin": "Margin", "return_on_capital": "Return on capital", "consistency": "Consistency", "seasonality": "Seasonality"}
        for row, (key, score) in enumerate(factors.items()):
            self.factor_table.setItem(row, 0, table_item(labels.get(key, key))); self.factor_table.setItem(row, 1, table_item(f"{weights[key]}%")); self.factor_table.setItem(row, 2, table_item(f"{score:.1f} / 100"))

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import historical vehicle data", "", "Vehicle data (*.csv *.tsv *.txt *.xlsx *.xlsm *.xls)")
        if not path: return
        try:
            summary = import_vehicle_history(self.db, Path(path))
            self.import_status.setText(f"Imported {summary.rows:,} rows · {summary.usable:,} ready · {summary.review:,} need review · {summary.duplicates:,} duplicates retained but excluded")
            self.refresh(); self.changed.emit()
            files = write_intelligence_snapshot(self.db); sync = IntelligenceSyncJob(files); sync.signals.finished.connect(self.import_status.setText); sync.signals.failed.connect(self.import_status.setText); QThreadPool.globalInstance().start(sync); self._active_sync_job = sync
        except Exception as error:
            QMessageBox.critical(self, "Import failed", str(error))

    def add_memory(self) -> None:
        memory = self.memory_input.text().strip()
        if not memory: return
        save_intelligence_memory(self.db, memory, "manual")
        self.memory_input.clear(); self.memory_status.setText(f"Remembered: {memory}"); self._refresh_memories(); self._sync_ai_context()

    def forget_selected_memory(self) -> None:
        row = self.memory_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a memory", "Select the learned rule you want Runway to forget."); return
        item = self.memory_table.item(row, 0); memory_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if memory_id is None: return
        forget_intelligence_memory(self.db, int(memory_id)); self.memory_status.setText("Selected memory forgotten."); self._refresh_memories(); self._sync_ai_context()

    def _sync_ai_context(self) -> None:
        files = write_intelligence_snapshot(self.db); sync = IntelligenceSyncJob(files)
        sync.signals.finished.connect(self.memory_status.setText); sync.signals.failed.connect(self.memory_status.setText)
        QThreadPool.globalInstance().start(sync); self._active_memory_sync_job = sync

    def _refresh_memories(self) -> None:
        if not hasattr(self, "memory_table"): return
        memories = intelligence_memories(self.db); self.memory_table.setRowCount(len(memories))
        for row, memory in enumerate(memories):
            learned = QTableWidgetItem(memory["memory_text"]); learned.setData(Qt.ItemDataRole.UserRole, memory["id"]); self.memory_table.setItem(row, 0, learned)
            self.memory_table.setItem(row, 1, QTableWidgetItem(memory["source"].title())); self.memory_table.setItem(row, 2, QTableWidgetItem(memory["updated_at"]))

    def _selected_watchlist(self) -> dict[str, object] | None:
        row=self.watchlist_table.currentRow() if hasattr(self,"watchlist_table") else -1
        if row<0:return None
        item=self.watchlist_table.item(row,0); item_id=item.data(Qt.ItemDataRole.UserRole) if item else None
        return next((value for value in watchlist_items(self.db) if value["id"]==item_id),None)

    def _add_watchlist(self) -> None:
        dialog=WatchlistDialog(self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            try: save_watchlist_item(self.db,dialog.payload()); self._refresh_watchlist(); self._refresh_velocity()
            except Exception as error: QMessageBox.warning(self,"Could not save",str(error))

    def _edit_watchlist(self) -> None:
        item=self._selected_watchlist()
        if not item: QMessageBox.information(self,"Select a vehicle","Select the watched vehicle to edit."); return
        dialog=WatchlistDialog(self,item)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            try: save_watchlist_item(self.db,dialog.payload(),int(item["id"])); self._refresh_watchlist()
            except Exception as error: QMessageBox.warning(self,"Could not save",str(error))

    def _toggle_watchlist(self) -> None:
        item=self._selected_watchlist()
        if not item: QMessageBox.information(self,"Select a vehicle","Select the watched vehicle to pause or resume."); return
        set_watchlist_active(self.db,int(item["id"]),not bool(item["active"])); self._refresh_watchlist(); self._refresh_velocity()

    def _delete_watchlist(self) -> None:
        item=self._selected_watchlist()
        if not item: QMessageBox.information(self,"Select a vehicle","Select the watched vehicle to delete."); return
        if QMessageBox.question(self,"Delete watched vehicle",f"Delete {item['make']} {item['model']} {item['trim']} and its retained watchlist history?")!=QMessageBox.StandardButton.Yes:return
        delete_watchlist_item(self.db,int(item["id"])); self._refresh_watchlist(); self._refresh_velocity()

    def _sync_watchlist_now(self) -> None:
        if not watchlist_items(self.db,active_only=True):
            QMessageBox.information(self,"No active vehicles","Add or resume at least one Market Watchlist vehicle first."); return
        self.watch_sync.setEnabled(False); self.watch_sync.setText("Syncing…"); self.watch_sync_status.setText("Connecting securely to Deal Drive…")
        job=WatchlistSyncJob(self.db); job.signals.progress.connect(self.watch_sync_status.setText)
        job.signals.finished.connect(self._watchlist_sync_finished); job.signals.failed.connect(self._watchlist_sync_failed)
        self._active_watchlist_sync_job=job; QThreadPool.globalInstance().start(job)

    def _watchlist_sync_finished(self,message: str) -> None:
        self.watch_sync.setEnabled(True); self.watch_sync.setText("↻ Sync now"); self.watch_sync_status.setText(message)
        self._refresh_watchlist(); self._refresh_velocity(); self.changed.emit()

    def _watchlist_sync_failed(self,message: str) -> None:
        self.watch_sync.setEnabled(True); self.watch_sync.setText("↻ Sync now"); self.watch_sync_status.setText(f"Sync failed · {message}")
        QMessageBox.warning(self,"Watchlist sync failed",message)

    def _accept_watchlist_suggestion(self) -> None:
        suggestion=getattr(self,"_current_watchlist_suggestion",None)
        if not suggestion:return
        save_watchlist_item(self.db,{**suggestion,"gcc_only":True,"dealer_only":True,"exclude_sharjah_ajman":True,"mileage_min":None,"mileage_max":None,"active":True}); self._refresh_watchlist()

    def _ignore_watchlist_suggestion(self) -> None:
        suggestion=getattr(self,"_current_watchlist_suggestion",None)
        if not suggestion:return
        ignore_suggestion(self.db,suggestion); self._refresh_watchlist()

    def _refresh_watchlist(self) -> None:
        if not hasattr(self,"watchlist_table"):return
        rows=watchlist_items(self.db); self.watchlist_table.setRowCount(len(rows))
        for index,row in enumerate(rows):
            vehicle=QTableWidgetItem(f"{row['make']} {row['model']}"); vehicle.setData(Qt.ItemDataRole.UserRole,row["id"]); self.watchlist_table.setItem(index,0,vehicle)
            mileage="Any" if row["mileage_min"] is None and row["mileage_max"] is None else f"{int(row['mileage_min'] or 0):,}–{int(row['mileage_max'] or 1000000):,} km"
            rules=("GCC" if row["gcc_only"] else "Imports allowed")+(" · Dealer" if row["dealer_only"] else " · All sellers")+(" · DXB/AUH" if row["exclude_sharjah_ajman"] else "")
            state="Paused" if not row["active"] else "Active · due" if watchlist_sync_due(row) else "Active · 72h cooldown"
            values=[row["trim"],f"{row['year_from']}–{row['year_to']}",rules,mileage,state,row["last_synced"] or "Never"]
            for column,value in enumerate(values,1):self.watchlist_table.setItem(index,column,QTableWidgetItem(str(value)))
        suggestions=watchlist_suggestions(self.db,1); self._current_watchlist_suggestion=suggestions[0] if suggestions else None
        if suggestions:
            value=suggestions[0]; self.watch_suggestion.setText(f"Frequently seen vehicle · {value['year_from']}–{value['year_to']} {value['make']} {value['model']} {value['trim']} · {value['samples']} Alba records")
            self.watch_add_suggestion.setEnabled(True); self.watch_ignore_suggestion.setEnabled(True)
        else:
            self.watch_suggestion.setText("No strong suggestion right now. Runway will only suggest vehicles supported by repeated clean evidence."); self.watch_add_suggestion.setEnabled(False); self.watch_ignore_suggestion.setEnabled(False)

    def refresh(self) -> None:
        self._refresh_memories()
        self._refresh_deal_drive()
        self._refresh_watchlist()
        self._refresh_velocity()
        if hasattr(self, "batch_table"):
            batches = import_history(self.db); self.batch_table.setRowCount(len(batches))
            for row, batch in enumerate(batches):
                values = [batch["file_name"], batch["imported_at"], batch["source_rows"], batch["usable_rows"], batch["review_rows"], batch["duplicate_rows"]]
                for column, value in enumerate(values): self.batch_table.setItem(row, column, QTableWidgetItem(str(value)))
        if hasattr(self, "grades_table"):
            grades = recent_vehicle_grades(self.db); self.grades_table.setRowCount(len(grades))
            for row, grade in enumerate(grades):
                values = [f"{grade.get('model_year') or ''} {grade['make']} {grade['model']}".strip(), grade["trim"], grade["grade"], grade["decision"], grade["confidence"], grade["sample_size"], grade.get("median_days", "—"), _money(grade.get("average_profit_aed")), grade.get("trim_position", "—")]
                for column, value in enumerate(values): self.grades_table.setItem(row, column, QTableWidgetItem(str(value)))

    def _refresh_velocity(self) -> None:
        if not hasattr(self,"velocity_fast"): return
        rows=radar_rows(self.db); self.velocity_status.setText("Waiting for the first 23:59 watchlist sync." if not rows else f"{len(rows)} active cohort{'s' if len(rows)!=1 else ''} scored · old snapshots retained")
        fast=sorted((row for row in rows if market_pace_bucket(row.get("median_listing_age_days"))=="fast"),key=lambda row:float(row.get("median_listing_age_days") or 999))
        slow=sorted((row for row in rows if market_pace_bucket(row.get("median_listing_age_days"))=="slow"),key=lambda row:float(row.get("median_listing_age_days") or 0),reverse=True)
        ages=[float(row["median_listing_age_days"]) for row in rows if row.get("median_listing_age_days") is not None]
        self.radar_fast_metric.set_value(str(len(fast)),f"{len(fast)} cohort{'s' if len(fast)!=1 else ''} beating the 45-day line",COLORS["green"])
        self.radar_slow_metric.set_value(str(len(slow)),f"{len(slow)} cohort{'s' if len(slow)!=1 else ''} require extra caution",COLORS["red"])
        self.radar_age_metric.set_value(f"{statistics.median(ages):.0f} days" if ages else "—","Synced watchlist median",COLORS["cyan"])
        for table,values,pace,color in ((self.velocity_fast,fast,"⚡ FAST",COLORS["green"]),(self.velocity_slow,slow,"⚠ SLOW",COLORS["red"])):
            table.setRowCount(len(values))
            for index,row in enumerate(values):
                change=row.get("change_30d"); trend=f"30d price {float(change):+.1f}%" if change is not None else "Building 30d history"
                movement=f"{row['market_exits']} exits · +{row['new_listings']} new · {row['price_reductions']} cuts\n{trend}"
                cells=[f"{row['year_from']}–{row['year_to']}  {row['make']} {row['model']}\n{row['trim']}",pace,
                       f"{float(row['median_listing_age_days'] or 0):.0f} DAYS",f"{float(row['score']):.0f}/100 · {row['label']}",
                       f"{row['current_listings']} live\nSample {row['sample_size']}",_money(row["median_asking_aed"]),movement,str(row["confidence"]).upper()]
                for column,value in enumerate(cells):
                    item=QTableWidgetItem(str(value)); item.setForeground(QColor(color) if column in (1,2) else QColor(COLORS["text"])); table.setItem(index,column,item)
                table.setRowHeight(index,62)
