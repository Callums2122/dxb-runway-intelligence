from __future__ import annotations

from datetime import date,datetime,timedelta

from PySide6.QtCore import QObject,QRunnable,QThreadPool,QTimer,Qt,Signal
from PySide6.QtWidgets import QAbstractItemView,QGridLayout,QHBoxLayout,QLabel,QPushButton,QTableWidget,QVBoxLayout,QWidget

from .database import Database
from .google_schedule import GoogleSheetsReadOnlyClient,GoogleScheduleError
from .schedule import OFF_TYPES,get_evening_shift_team,get_my_schedule,get_recent_changes,get_upcoming_schedule,sync_schedule,sync_status
from .screens import Page,page_scroll,table_item
from .style import COLORS
from .widgets import Card,MetricCard,SectionHeader

class _Signals(QObject):finished=Signal(str);failed=Signal(str)
class _SyncJob(QRunnable):
    def __init__(self,db:Database):super().__init__();self.db=db;self.signals=_Signals()
    def run(self):
        try:self.signals.finished.emit(f"Read-only sync complete · {sync_schedule(self.db)} rota days")
        except Exception as error:self.signals.failed.emit(str(error))

def _working(shift:str)->bool:return shift not in OFF_TYPES and shift!="REMOVED FROM LEADS"
def _colour(shift:str)->str:
    return COLORS["muted"] if shift=="No cached rota" else COLORS["purple"] if shift=="EVENING SHIFT" else COLORS["red"] if shift=="OFF" else COLORS["amber"] if "LEAVE" in shift or "HOLIDAY" in shift else COLORS["green"]

class SchedulePage(Page):
    def __init__(self,db:Database):
        super().__init__(db);self._busy=False;outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);content=QWidget();root=QVBoxLayout(content);root.setContentsMargins(24,22,24,28);root.setSpacing(14)
        head=QHBoxLayout();head.addWidget(SectionHeader("Schedule","Live read-only view of management’s Google rota. The source spreadsheet can never be modified."));head.addStretch();self.status_label=QLabel();self.status_label.setObjectName("muted");head.addWidget(self.status_label);self.sync_button=QPushButton("↻ Refresh now");self.sync_button.clicked.connect(lambda:self.start_sync(True));head.addWidget(self.sync_button);root.addLayout(head)
        safety=QLabel("CONNECTED ACCESS IS READ ONLY · spreadsheets.readonly · cached rota remains available if Google is offline");safety.setStyleSheet(f"color:{COLORS['green']};font-weight:800");root.addWidget(safety)
        metrics=QGridLayout();metrics.setSpacing(12);self.metrics={}
        for column,(key,label,color) in enumerate((("today","Today",COLORS["cyan"]),("next","Next shift",COLORS["green"]),("evening","Next evening shift",COLORS["purple"]),("off","Next day off",COLORS["amber"]))):card=MetricCard(label,accent=color);self.metrics[key]=card;metrics.addWidget(card,0,column)
        root.addLayout(metrics)
        grids=QGridLayout();grids.setSpacing(12)
        week=Card();wl=QVBoxLayout(week);wl.addWidget(SectionHeader("This week","Your status for each day of the current week."));self.week=QTableWidget(0,3);self._setup(self.week,["DATE","DAY","MY STATUS"]);wl.addWidget(self.week);grids.addWidget(week,0,0)
        changes=Card();cl=QVBoxLayout(changes);cl.addWidget(SectionHeader("Recent schedule changes","Latest 10 future rota changes detected against the previous local cache."));self.changes=QTableWidget(0,3);self._setup(self.changes,["DATE","PREVIOUS","NEW"]);cl.addWidget(self.changes);grids.addWidget(changes,0,1);root.addLayout(grids)
        month=Card();ml=QVBoxLayout(month);ml.addWidget(SectionHeader("This month","Normal working days, evening shifts, OFF, leave and holidays."));self.month=QTableWidget(0,3);self._setup(self.month,["DATE","DAY","MY STATUS"]);ml.addWidget(self.month);root.addWidget(month)
        evening=Card();el=QVBoxLayout(evening);el.addWidget(SectionHeader("Evening shift team","Everyone scheduled on the evening shift with you."));self.evening=QTableWidget(0,3);self._setup(self.evening,["DATE","DAY","TEAM WITH CALLUM"]);el.addWidget(self.evening);root.addWidget(evening)
        summary=Card();sl=QVBoxLayout(summary);sl.addWidget(SectionHeader("Monthly summary","Counts are calculated from the locally cached management rota."));self.summary=QLabel();self.summary.setWordWrap(True);sl.addWidget(self.summary);root.addWidget(summary);outer.addWidget(page_scroll(content))
        self.timer=QTimer(self);self.timer.setInterval(600_000);self.timer.timeout.connect(lambda:self.start_sync(False));self.timer.start();self.refresh();QTimer.singleShot(1000,lambda:self.start_sync(False))
    def _setup(self,table:QTableWidget,labels:list[str]):table.setHorizontalHeaderLabels(labels);table.verticalHeader().hide();table.horizontalHeader().setStretchLastSection(True);table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection);table.setMinimumHeight(250)
    def start_sync(self,force:bool)->None:
        if self._busy:return
        if not force:
            try:
                if not GoogleSheetsReadOnlyClient().connected():return
            except GoogleScheduleError:return
        status=sync_status(self.db);last=status.get("completed_at")
        if not force and last:
            try:
                if datetime.now()-datetime.fromisoformat(str(last))<timedelta(minutes=10):return
            except ValueError:pass
        self._busy=True;self.sync_button.setEnabled(False);self.status_label.setText("Reading Google Sheet…");job=_SyncJob(self.db);job.signals.finished.connect(self._done);job.signals.failed.connect(self._failed);self._job=job;QThreadPool.globalInstance().start(job)
    def _done(self,message:str)->None:self._busy=False;self.sync_button.setEnabled(True);self.status_label.setText(message);self.refresh();self.changed.emit()
    def _failed(self,message:str)->None:self._busy=False;self.sync_button.setEnabled(True);self.status_label.setText(f"Cached rota · {message}");self.refresh()
    def refresh(self)->None:
        rows=get_my_schedule(self.db);by_day={row["schedule_date"]:row for row in rows};today=date.today();today_row=by_day.get(today.isoformat());today_shift=today_row["shift_type"] if today_row else "No cached rota"
        today_detail="No schedule cached" if not today_row else "Working · Evening shift" if today_shift=="EVENING SHIFT" else "Working" if _working(today_shift) else "Not working"
        self.metrics["today"].set_value(today_shift,today_detail,_colour(today_shift))
        upcoming=get_upcoming_schedule(self.db,today);next_work=next((row for row in upcoming if row["schedule_date"]>today.isoformat() and _working(row["shift_type"])),None);next_evening=next((row for row in upcoming if row["schedule_date"]>=today.isoformat() and row["shift_type"]=="EVENING SHIFT"),None);next_off=next((row for row in upcoming if row["schedule_date"]>=today.isoformat() and row["shift_type"]=="OFF"),None)
        self.metrics["next"].set_value(next_work["shift_type"] if next_work else "—",self._day_detail(next_work),COLORS["green"]);team=get_evening_shift_team(self.db,next_evening["schedule_date"]) if next_evening else [];self.metrics["evening"].set_value(next_evening["shift_type"] if next_evening else "—",self._day_detail(next_evening)+(f" · With {', '.join(team)}" if team else ""),COLORS["purple"]);self.metrics["off"].set_value("OFF" if next_off else "—",self._day_detail(next_off),COLORS["amber"])
        week_start=today-timedelta(days=today.weekday());week_rows=[by_day.get((week_start+timedelta(days=i)).isoformat(),{"schedule_date":(week_start+timedelta(days=i)).isoformat(),"shift_type":"No cached rota"}) for i in range(7)];self._fill_schedule(self.week,week_rows)
        month_rows=[row for row in rows if row["schedule_date"].startswith(today.strftime("%Y-%m"))];self._fill_schedule(self.month,month_rows);self.month.setMinimumHeight(max(280,35+len(month_rows)*38))
        evening_rows=[row for row in rows if row["schedule_date"]>=today.isoformat() and row["shift_type"]=="EVENING SHIFT"];self.evening.setRowCount(len(evening_rows))
        for i,row in enumerate(evening_rows):
            day=date.fromisoformat(row["schedule_date"]);values=[day.strftime("%d %b %Y"),day.strftime("%A"),", ".join(get_evening_shift_team(self.db,row["schedule_date"])) or "No other evening purchaser"]
            for j,value in enumerate(values):self.evening.setItem(i,j,table_item(value,color=COLORS["purple"] if j==2 else None))
        changes=get_recent_changes(self.db);self.changes.setRowCount(len(changes))
        for i,row in enumerate(changes):
            for j,value in enumerate((date.fromisoformat(row["schedule_date"]).strftime("%d %b"),row["old_shift"],row["new_shift"])):self.changes.setItem(i,j,table_item(value,color=_colour(row["new_shift"]) if j==2 else None))
        counts={};
        for row in month_rows:counts[row["shift_type"]]=counts.get(row["shift_type"],0)+1
        work=sum(_working(row["shift_type"]) for row in month_rows);self.summary.setText(f"Evening shifts  {counts.get('EVENING SHIFT',0)}   ·   OFF  {counts.get('OFF',0)}   ·   Normal working days  {counts.get('Normal Working Day',0)+counts.get('STANDARD',0)}   ·   Annual leave  {counts.get('ANNUAL LEAVE',0)}   ·   Special leave  {counts.get('ADDITIONAL/SPECIAL LEAVE',0)}   ·   Holidays  {counts.get('ALBA HOLIDAY / COMP OFF',0)}   ·   Total scheduled working days  {work}")
        status=sync_status(self.db);self.status_label.setText(f"{status.get('message')} · Last synced {status.get('completed_at') or 'never'}")
        if status.get("status")=="never" and not self._busy:QTimer.singleShot(0,lambda:self.start_sync(False))
    def _fill_schedule(self,table:QTableWidget,rows:list[dict]):
        table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            day=date.fromisoformat(row["schedule_date"]);values=[day.strftime("%d %b %Y"),day.strftime("%A"),row["shift_type"]]
            for j,value in enumerate(values):table.setItem(i,j,table_item(value,color=_colour(row["shift_type"]) if j==2 else None))
    @staticmethod
    def _day_detail(row:dict|None)->str:
        if not row:return "No upcoming cached entry"
        day=date.fromisoformat(row["schedule_date"]);return day.strftime("%A · %d %b %Y")
