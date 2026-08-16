from __future__ import annotations

import base64
import json
import shlex
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QRectF, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from .database import Database
from .dialogs import MoneyBox
from .intelligence import (
    analyse_opportunity, chat_conversation, chat_evidence, forget_intelligence_memory,
    import_history, import_vehicle_history, intelligence_memories, learning_directive,
    recent_vehicle_grades, save_chat_attachments, save_chat_message, save_intelligence_memory, write_intelligence_snapshot,
)
from .screens import Page, page_scroll, table_item
from .style import COLORS
from .widgets import Card, SectionHeader


def _money(value: object) -> str:
    return f"AED {float(value or 0):,.0f}"


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
        self.tabs.addTab(self._memory_tab(), "Memory")
        self.refresh()

    def _opportunity_tab(self) -> QWidget:
        content = QWidget(); root = QVBoxLayout(content); root.setContentsMargins(4,14,4,4); root.setSpacing(12)
        form_card = Card(); grid = QGridLayout(form_card); grid.setContentsMargins(18,16,18,16); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(10)
        self.make = QLineEdit(); self.make.setPlaceholderText("Audi")
        self.model = QLineEdit(); self.model.setPlaceholderText("Q8")
        self.trim = QLineEdit(); self.trim.setPlaceholderText("S line")
        self.year = QSpinBox(); self.year.setRange(0, 2035); self.year.setSpecialValueText("Unknown"); self.year.setValue(0)
        self.buy_price = MoneyBox(maximum=100_000_000); self.retail_price = MoneyBox(maximum=100_000_000); self.prep = MoneyBox(maximum=5_000_000)
        fields = [("Make", self.make), ("Model", self.model), ("Trim", self.trim), ("Model year", self.year),
                  ("Purchase price · AED", self.buy_price), ("Expected sale · AED", self.retail_price), ("Prep allowance · AED", self.prep)]
        for index, (label, widget) in enumerate(fields):
            row, column = divmod(index, 2); grid.addWidget(QLabel(label), row * 2, column); grid.addWidget(widget, row * 2 + 1, column)
        check = QPushButton("Analyse opportunity"); check.setProperty("primary", True); check.clicked.connect(self.run_analysis); grid.addWidget(check, 8, 1)
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

    def run_analysis(self) -> None:
        if not self.make.text().strip() or not self.model.text().strip():
            QMessageBox.information(self, "Vehicle required", "Enter at least the make and model."); return
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

    def refresh(self) -> None:
        self._refresh_memories()
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
