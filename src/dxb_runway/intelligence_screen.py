from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from .database import Database
from .dialogs import MoneyBox
from .intelligence import analyse_opportunity, import_history, import_vehicle_history, recent_vehicle_grades, write_intelligence_snapshot
from .screens import Page, page_scroll, table_item
from .style import COLORS
from .widgets import Card, SectionHeader


def _money(value: object) -> str:
    return f"AED {float(value or 0):,.0f}"


class WorkerSignals(QObject):
    finished = Signal(str)
    failed = Signal(str)


class OpenClawChatJob(QRunnable):
    """Runs only the fixed, owner-controlled OpenClaw agent over the dedicated SSH key."""

    def __init__(self, prompt: str):
        super().__init__()
        self.prompt = prompt
        self.signals = WorkerSignals()

    def run(self) -> None:
        key = Path.home() / ".ssh" / "dxb_runway_openclaw"
        if not key.exists():
            self.signals.failed.emit("AI connection is not configured on this computer. Offline grading still works.")
            return
        remote = "set -a; . ~/.openclaw/gateway.systemd.env >/dev/null 2>&1; set +a; openclaw agent --agent dxb-runway --thinking medium --json --message " + shlex.quote(self.prompt)
        try:
            result = subprocess.run(
                ["ssh", "-i", str(key), "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
                 "callumadmin@157.180.75.235", remote],
                capture_output=True, text=True, timeout=150, check=False,
            )
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "OpenClaw did not answer")
            answer = result.stdout.strip()
            try:
                payload = json.loads(answer)
                answer = payload.get("result") or payload.get("response") or payload.get("text") or answer
            except json.JSONDecodeError:
                pass
            self.signals.finished.emit(str(answer))
        except Exception as error:
            self.signals.failed.emit(str(error))


class IntelligenceSyncJob(QRunnable):
    def __init__(self, files: tuple[Path, Path]):
        super().__init__(); self.files = files; self.signals = WorkerSignals()

    def run(self) -> None:
        key = Path.home() / ".ssh" / "dxb_runway_openclaw"
        if not key.exists():
            self.signals.failed.emit("Saved locally; VPS sync key is not installed on this computer."); return
        try:
            result = subprocess.run(
                ["scp", "-i", str(key), "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
                 *(str(path) for path in self.files),
                 "callumadmin@157.180.75.235:/home/callumadmin/.openclaw/workspace-dxb-runway/data/"],
                capture_output=True, text=True, timeout=300, check=False,
            )
            if result.returncode: raise RuntimeError(result.stderr.strip() or "Secure sync failed")
            self.signals.finished.emit("Historical data securely synced to Runway AI.")
        except Exception as error:
            self.signals.failed.emit(f"Saved locally; AI sync failed: {error}")


class IntelligencePage(Page):
    def __init__(self, db: Database):
        super().__init__(db)
        outer = QVBoxLayout(self); outer.setContentsMargins(20,18,20,20); outer.setSpacing(12)
        outer.addWidget(SectionHeader("Buying intelligence", "Brutal, evidence-led vehicle decisions. The grade is calculated locally; AI explains it but cannot alter it."))
        self.tabs = QTabWidget(); outer.addWidget(self.tabs, 1)
        self.tabs.addTab(self._opportunity_tab(), "Opportunity check")
        self.tabs.addTab(self._data_tab(), "Historical data")
        self.tabs.addTab(self._grades_tab(), "Vehicle grades")
        self.tabs.addTab(self._chat_tab(), "Ask Runway")

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

    def _chat_tab(self) -> QWidget:
        content = QWidget(); root = QVBoxLayout(content); root.setContentsMargins(4,14,4,4); root.setSpacing(10)
        safety = QLabel("Runway AI is read-only. It cannot contact customers, access CRM/company systems, send email, make calls, spend money or change grades.")
        safety.setWordWrap(True); safety.setStyleSheet(f"color:{COLORS['green']};font-weight:700"); root.addWidget(safety)
        self.chat_history = QTextEdit(); self.chat_history.setReadOnly(True); self.chat_history.setPlaceholderText("Ask about a car, margin, stock risk or the evidence behind a grade."); root.addWidget(self.chat_history, 1)
        line = QHBoxLayout(); self.chat_input = QLineEdit(); self.chat_input.setPlaceholderText("Ask Runway…"); self.chat_input.returnPressed.connect(self.send_chat); line.addWidget(self.chat_input, 1)
        self.chat_button = QPushButton("Send"); self.chat_button.setProperty("primary", True); self.chat_button.clicked.connect(self.send_chat); line.addWidget(self.chat_button); root.addLayout(line)
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

    def send_chat(self) -> None:
        question = self.chat_input.text().strip()
        if not question: return
        self.chat_input.clear(); self.chat_history.append(f"<b>You</b><br>{question}<br>"); self.chat_button.setEnabled(False); self.chat_button.setText("Thinking…")
        context = {"question": question, "instruction": "Use read-only vehicle intelligence. Never take an external action. Be sharp, brutal, evidence-led and concise."}
        job = OpenClawChatJob(json.dumps(context)); job.signals.finished.connect(self._chat_answer); job.signals.failed.connect(self._chat_error); QThreadPool.globalInstance().start(job); self._active_chat_job = job

    def _chat_answer(self, answer: str) -> None:
        self.chat_history.append(f"<b>Runway</b><br>{answer}<br>"); self.chat_button.setEnabled(True); self.chat_button.setText("Send")

    def _chat_error(self, error: str) -> None:
        self.chat_history.append(f"<b>Connection</b><br>{error}<br>"); self.chat_button.setEnabled(True); self.chat_button.setText("Send")

    def refresh(self) -> None:
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
