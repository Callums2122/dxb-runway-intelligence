from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QDate, QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QDateEdit, QGridLayout, QHeaderView, QHBoxLayout, QLabel, QPushButton, QTableWidget, QVBoxLayout, QWidget

from .database import Database
from .pipeline import appointments, sync_pipeline, sync_status
from .screens import Page, page_scroll, table_item
from .style import COLORS
from .widgets import Card, MetricCard, SectionHeader


class _Signals(QObject):
    finished = Signal(str); failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, db: Database): super().__init__(); self.db = db; self.signals = _Signals()
    def run(self):
        try: self.signals.finished.emit(f"Read-only sync complete · {sync_pipeline(self.db)} appointments")
        except Exception as error: self.signals.failed.emit(str(error))


class PipelinePage(Page):
    def __init__(self, db: Database):
        super().__init__(db); self._busy = False
        outer = QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content = QWidget(); root = QVBoxLayout(content); root.setContentsMargins(24,22,24,28); root.setSpacing(14)
        head = QHBoxLayout(); head.addWidget(SectionHeader("Appointments","Live management Pipeline appointments matched against your current stock.")); head.addStretch(); self.status = QLabel(); self.status.setObjectName("muted"); head.addWidget(self.status); self.day = QDateEdit(); self.day.setCalendarPopup(True); self.day.setDisplayFormat("ddd dd MMM yyyy"); self.day.setDate(QDate.currentDate()); self.day.dateChanged.connect(self.refresh); head.addWidget(self.day); self.sync_button = QPushButton("↻ Refresh now"); self.sync_button.clicked.connect(lambda:self.start_sync(True)); head.addWidget(self.sync_button); root.addLayout(head)
        safety = QLabel("CONNECTED ACCESS IS STRICTLY READ ONLY · refreshes every 10 minutes · the management spreadsheet can never be edited")
        safety.setStyleSheet(f"color:{COLORS['green']};font-weight:850"); safety.setWordWrap(True); root.addWidget(safety)
        metrics = QGridLayout(); metrics.setSpacing(12); self.metrics = {}
        for column,(key,label,color) in enumerate((("total","Appointments",COLORS["cyan"]),("green","Exact stock match",COLORS["green"]),("amber","Model match",COLORS["amber"]),("unmatched","Not in your stock",COLORS["muted"]))):
            card=MetricCard(label,accent=color); self.metrics[key]=card; metrics.addWidget(card,0,column)
        root.addLayout(metrics)
        legend = Card(); ll = QHBoxLayout(legend); ll.addWidget(QLabel("🟢 GREEN · exact year, make and model")); ll.addSpacing(20); ll.addWidget(QLabel("🟠 AMBER · same make and model, different/unknown year")); ll.addSpacing(20); ll.addWidget(QLabel("⚪ UNMATCHED · no current-stock equivalent")); ll.addStretch(); root.addWidget(legend)
        card = Card(); cl = QVBoxLayout(card); cl.addWidget(SectionHeader("Daily appointment board","The strongest matches are placed first so you can act quickly.")); self.table = QTableWidget(0,8); self.table.setHorizontalHeaderLabels(["GRADE","TIME","CUSTOMER","APPOINTMENT VEHICLE","YOUR STOCK MATCH","SN","CHECKED IN","NOTE"]); self.table.verticalHeader().hide(); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch); self.table.horizontalHeader().setSectionResizeMode(4,QHeaderView.ResizeMode.Stretch); self.table.setMinimumHeight(520); cl.addWidget(self.table); root.addWidget(card)
        outer.addWidget(page_scroll(content)); self.timer=QTimer(self); self.timer.setInterval(600_000); self.timer.timeout.connect(lambda:self.start_sync(False)); self.timer.start(); self.refresh(); QTimer.singleShot(1200,lambda:self.start_sync(False))

    def start_sync(self, force: bool) -> None:
        if self._busy: return
        if not self.db.get_setting("pipeline_spreadsheet_id", "").strip(): self.status.setText("Paste the Pipeline Sheet link in Settings"); return
        previous = sync_status(self.db); last = previous.get("completed_at")
        if not force and last:
            try:
                if datetime.now()-datetime.fromisoformat(str(last)) < timedelta(minutes=10): return
            except ValueError: pass
        self._busy=True; self.sync_button.setEnabled(False); self.status.setText("Reading Pipeline…"); job=_Job(self.db); job.signals.finished.connect(self._done); job.signals.failed.connect(self._failed); self._job=job; QThreadPool.globalInstance().start(job)

    def _done(self,message:str)->None: self._busy=False; self.sync_button.setEnabled(True); self.status.setText(message); self.refresh(); self.changed.emit()
    def _failed(self,message:str)->None: self._busy=False; self.sync_button.setEnabled(True); self.status.setText(f"Cached appointments · {message}"); self.refresh()

    def refresh(self) -> None:
        selected = self.day.date().toString("yyyy-MM-dd"); rows = appointments(self.db, selected); order={"green":0,"amber":1,"unmatched":2}; rows.sort(key=lambda row:(order.get(row["match_grade"],3),row["appointment_time"]))
        counts={grade:sum(row["match_grade"]==grade for row in rows) for grade in ("green","amber","unmatched")}
        self.metrics["total"].set_value(str(len(rows)),date.fromisoformat(selected).strftime("%A · %d %B"),COLORS["cyan"])
        for grade,color in (("green",COLORS["green"]),("amber",COLORS["amber"]),("unmatched",COLORS["muted"])): self.metrics[grade].set_value(str(counts[grade]),f"{counts[grade]} of {len(rows)} appointments",color)
        self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            grade=row["match_grade"]; color=COLORS["green"] if grade=="green" else COLORS["amber"] if grade=="amber" else COLORS["muted"]; label="EXACT" if grade=="green" else "MODEL" if grade=="amber" else "—"
            values=[label,row["appointment_time"],row["customer_name"],row["vehicle_text"],row.get("matched_vehicle") or "No stock match",row["stock_number"],row["checked_in"],row["note"]]
            for j,value in enumerate(values):
                item=table_item(value,Qt.AlignmentFlag.AlignVCenter,color=color if j in {0,4} else None)
                if grade in {"green","amber"}: item.setBackground(QColor(color).darker(430))
                item.setToolTip(row["match_detail"]); self.table.setItem(i,j,item)
            self.table.setRowHeight(i,48)
        state=sync_status(self.db); self.status.setText(f"{state.get('message')} · Last synced {state.get('completed_at') or 'never'}")
