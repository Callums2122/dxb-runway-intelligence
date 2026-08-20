from __future__ import annotations

import calendar
from datetime import date,datetime,timedelta

from PySide6.QtCore import QObject,QRunnable,QThreadPool,QTimer,Qt,Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView,QComboBox,QGridLayout,QHeaderView,QHBoxLayout,QLabel,QPushButton,QTableWidget,QVBoxLayout,QWidget

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


def _working(shift:str)->bool:return shift not in OFF_TYPES and shift not in {"REMOVED FROM LEADS","No rota supplied"}
def _category(shift:str)->str:
    if shift=="EVENING SHIFT":return "evening"
    if shift=="OFF":return "off"
    if shift in {"Normal Working Day","STANDARD"}:return "working"
    if shift=="No rota supplied":return "missing"
    return "leave"
def _colour(shift:str)->str:return {"working":COLORS["green"],"evening":COLORS["purple"],"off":COLORS["red"],"leave":COLORS["amber"],"missing":COLORS["muted"]}[_category(shift)]
def _short(shift:str)->str:return {"Normal Working Day":"WORKING","STANDARD":"WORKING","EVENING SHIFT":"EVENING","ADDITIONAL/SPECIAL LEAVE":"SPECIAL LEAVE","ALBA HOLIDAY / COMP OFF":"HOLIDAY","GOLDEN DAY / COMP OFF":"COMP OFF"}.get(shift,shift)


class SchedulePage(Page):
    def __init__(self,db:Database):
        super().__init__(db);self._busy=False;self._month_keys=[];outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);content=QWidget();root=QVBoxLayout(content);root.setContentsMargins(24,22,24,28);root.setSpacing(14)
        head=QHBoxLayout();head.addWidget(SectionHeader("Schedule","A simple view of when you are working, on evenings, OFF or on leave."));head.addStretch();self.status_label=QLabel();self.status_label.setObjectName("muted");head.addWidget(self.status_label);self.sync_button=QPushButton("↻ Refresh now");self.sync_button.clicked.connect(lambda:self.start_sync(True));head.addWidget(self.sync_button);root.addLayout(head)
        self.coverage=QLabel();self.coverage.setWordWrap(True);self.coverage.setStyleSheet(f"color:{COLORS['amber']};font-weight:800");root.addWidget(self.coverage)
        metrics=QGridLayout();metrics.setSpacing(12);self.metrics={}
        for column,(key,label,color) in enumerate((("today","Today",COLORS["cyan"]),("next","Next working day",COLORS["green"]),("evening","Next evening shift",COLORS["purple"]),("off","Next OFF / leave",COLORS["amber"]))):card=MetricCard(label,accent=color);self.metrics[key]=card;metrics.addWidget(card,0,column)
        root.addLayout(metrics)
        glance=Card();gal=QVBoxLayout(glance);gal.addWidget(SectionHeader("Next 30 rota days","Everything important, grouped so you can read it in seconds."));legend=QHBoxLayout();self.glance={}
        for key,title,color in (("working","WORKING DAYS",COLORS["green"]),("evening","EVENING SHIFTS",COLORS["purple"]),("off","DAYS OFF",COLORS["red"]),("leave","LEAVE / HOLIDAY",COLORS["amber"])):
            block=Card();bl=QVBoxLayout(block);heading=QLabel(title);heading.setStyleSheet(f"color:{color};font-weight:900");bl.addWidget(heading);value=QLabel();value.setWordWrap(True);value.setMinimumHeight(72);bl.addWidget(value);self.glance[key]=value;legend.addWidget(block,1)
        gal.addLayout(legend);root.addWidget(glance)
        month=Card();ml=QVBoxLayout(month);mh=QHBoxLayout();self.month_title=SectionHeader("Rota calendar","Each day is colour-coded: green working, purple evening, red OFF and amber leave.");mh.addWidget(self.month_title);mh.addStretch();self.month_picker=QComboBox();self.month_picker.setMinimumWidth(150);self.month_picker.currentIndexChanged.connect(self._render_month);mh.addWidget(self.month_picker);ml.addLayout(mh);self.month=QTableWidget(6,7);self.month.setHorizontalHeaderLabels(["MON","TUE","WED","THU","FRI","SAT","SUN"]);self.month.verticalHeader().hide();self.month.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.month.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.month.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection);self.month.setMinimumHeight(450);ml.addWidget(self.month);root.addWidget(month)
        bottom=QGridLayout();bottom.setSpacing(12)
        evening=Card();el=QVBoxLayout(evening);el.addWidget(SectionHeader("Evening shift team","Who is working the evening shift with you."));self.evening=QTableWidget(0,3);self._setup(self.evening,["DATE","DAY","TEAM WITH CALLUM"]);el.addWidget(self.evening);bottom.addWidget(evening,0,0)
        changes=Card();cl=QVBoxLayout(changes);cl.addWidget(SectionHeader("Recent schedule changes","Latest future changes management made after your previous sync."));self.changes=QTableWidget(0,3);self._setup(self.changes,["DATE","PREVIOUS","NEW"]);cl.addWidget(self.changes);bottom.addWidget(changes,0,1);root.addLayout(bottom)
        summary=Card();sl=QVBoxLayout(summary);sl.addWidget(SectionHeader("Selected month summary","A clean count for the month shown above."));self.summary=QLabel();self.summary.setWordWrap(True);sl.addWidget(self.summary);root.addWidget(summary);outer.addWidget(page_scroll(content))
        self.timer=QTimer(self);self.timer.setInterval(600_000);self.timer.timeout.connect(lambda:self.start_sync(False));self.timer.start();self.refresh();QTimer.singleShot(1000,lambda:self.start_sync(False))

    def _setup(self,table:QTableWidget,labels:list[str]):table.setHorizontalHeaderLabels(labels);table.verticalHeader().hide();table.horizontalHeader().setStretchLastSection(True);table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection);table.setMinimumHeight(235)
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
        self._busy=True;self.sync_button.setEnabled(False);self.status_label.setText("Reading management rota…");job=_SyncJob(self.db);job.signals.finished.connect(self._done);job.signals.failed.connect(self._failed);self._job=job;QThreadPool.globalInstance().start(job)
    def _done(self,message:str)->None:self._busy=False;self.sync_button.setEnabled(True);self.status_label.setText(message);self.refresh();self.changed.emit()
    def _failed(self,message:str)->None:self._busy=False;self.sync_button.setEnabled(True);self.status_label.setText(f"Cached rota · {message}");self.refresh()

    def refresh(self)->None:
        rows=get_my_schedule(self.db);by_day={row["schedule_date"]:row for row in rows};today=date.today();first=date.fromisoformat(rows[0]["schedule_date"]) if rows else None;last=date.fromisoformat(rows[-1]["schedule_date"]) if rows else None
        if first and today<first:self.coverage.setText(f"ⓘ Management has supplied this rota from {first.strftime('%A %d %B %Y')}. Days before that date are not present in the sheet.")
        elif first:self.coverage.setText(f"✓ LIVE READ-ONLY ROTA · Coverage {first.strftime('%d %b %Y')} to {last.strftime('%d %b %Y')} · refreshed every 10 minutes")
        else:self.coverage.setText("No rota has been cached yet. Press Refresh now to retry.")
        today_row=by_day.get(today.isoformat());today_shift=today_row["shift_type"] if today_row else "No rota supplied";today_detail="Management rota starts later" if first and today<first else "Working · Evening shift" if today_shift=="EVENING SHIFT" else "Working" if _working(today_shift) else "Not working"
        self.metrics["today"].set_value(_short(today_shift),today_detail,_colour(today_shift));upcoming=get_upcoming_schedule(self.db,today)
        next_work=next((row for row in upcoming if _working(row["shift_type"])),None);next_evening=next((row for row in upcoming if row["shift_type"]=="EVENING SHIFT"),None);next_rest=next((row for row in upcoming if not _working(row["shift_type"])),None)
        self.metrics["next"].set_value(_short(next_work["shift_type"]) if next_work else "—",self._day_detail(next_work),COLORS["green"]);team=get_evening_shift_team(self.db,next_evening["schedule_date"]) if next_evening else [];self.metrics["evening"].set_value("EVENING" if next_evening else "—",self._day_detail(next_evening)+(f" · With {', '.join(team)}" if team else ""),COLORS["purple"]);self.metrics["off"].set_value(_short(next_rest["shift_type"]) if next_rest else "—",self._day_detail(next_rest),_colour(next_rest["shift_type"]) if next_rest else COLORS["amber"])
        window=upcoming[:30]
        groups={key:[row for row in window if _category(row["shift_type"])==key] for key in self.glance}
        all_work=[row for row in window if _working(row["shift_type"])]
        groups["working"]=all_work
        for key,items in groups.items():
            dates=" · ".join(date.fromisoformat(row["schedule_date"]).strftime("%a %d %b") for row in items[:8]);extra=f"\n+ {len(items)-8} more shown in the calendar" if len(items)>8 else "";self.glance[key].setText(f"{len(items)} days\n"+(dates+extra if items else "None scheduled"))
        months=sorted({row["schedule_date"][:7] for row in rows});selected=self.month_picker.currentData();self.month_picker.blockSignals(True);self.month_picker.clear();self._month_keys=months
        for key in months:self.month_picker.addItem(datetime.strptime(key,"%Y-%m").strftime("%B %Y"),key)
        preferred=selected if selected in months else today.strftime("%Y-%m") if sum(row["schedule_date"].startswith(today.strftime("%Y-%m")) for row in rows)>=7 else next((key for key in months if key>=today.strftime("%Y-%m") and sum(row["schedule_date"].startswith(key) for row in rows)>=7),months[0] if months else None)
        if preferred in months:self.month_picker.setCurrentIndex(months.index(preferred))
        self.month_picker.blockSignals(False);self._render_month()
        evening_rows=[row for row in upcoming if row["shift_type"]=="EVENING SHIFT"][:12];self.evening.setRowCount(len(evening_rows))
        for i,row in enumerate(evening_rows):
            day=date.fromisoformat(row["schedule_date"]);values=[day.strftime("%d %b %Y"),day.strftime("%A"),", ".join(get_evening_shift_team(self.db,row["schedule_date"])) or "No other evening purchaser"]
            for j,value in enumerate(values):self.evening.setItem(i,j,table_item(value,color=COLORS["purple"] if j==2 else None))
        changes=get_recent_changes(self.db);self.changes.setRowCount(len(changes))
        for i,row in enumerate(changes):
            for j,value in enumerate((date.fromisoformat(row["schedule_date"]).strftime("%d %b"),_short(row["old_shift"]),_short(row["new_shift"]))):self.changes.setItem(i,j,table_item(value,color=_colour(row["new_shift"]) if j==2 else None))
        status=sync_status(self.db);self.status_label.setText(f"{status.get('message')} · Last synced {status.get('completed_at') or 'never'}")
        if status.get("status")=="never" and not self._busy:QTimer.singleShot(0,lambda:self.start_sync(False))

    def _render_month(self)->None:
        if not hasattr(self,"month") or not self.month_picker.currentData():return
        key=str(self.month_picker.currentData());year,month_number=(int(value) for value in key.split("-"));rows={row["schedule_date"]:row for row in get_my_schedule(self.db) if row["schedule_date"].startswith(key)};self.month.clearContents();cal=calendar.Calendar(firstweekday=0)
        weeks=cal.monthdayscalendar(year,month_number)
        for week_index in range(6):
            for weekday in range(7):
                day_number=weeks[week_index][weekday] if week_index<len(weeks) else 0
                if not day_number:continue
                current=date(year,month_number,day_number);row=rows.get(current.isoformat());shift=row["shift_type"] if row else "No rota supplied";item=table_item(f"{day_number}\n{_short(shift)}",Qt.AlignmentFlag.AlignCenter,color=_colour(shift));item.setBackground(QColor(_colour(shift)).darker(300));item.setToolTip(shift);self.month.setItem(week_index,weekday,item)
        self.month.setRowCount(6)
        for row in range(6):self.month.setRowHeight(row,64)
        counts={}
        for row in rows.values():counts[row["shift_type"]]=counts.get(row["shift_type"],0)+1
        work=sum(_working(row["shift_type"]) for row in rows.values());self.summary.setText(f"WORKING  {work} days   ·   EVENING  {counts.get('EVENING SHIFT',0)}   ·   OFF  {counts.get('OFF',0)}   ·   NORMAL  {counts.get('Normal Working Day',0)+counts.get('STANDARD',0)}   ·   ANNUAL LEAVE  {counts.get('ANNUAL LEAVE',0)}   ·   SPECIAL LEAVE  {counts.get('ADDITIONAL/SPECIAL LEAVE',0)}   ·   HOLIDAYS  {counts.get('ALBA HOLIDAY / COMP OFF',0)}")

    @staticmethod
    def _day_detail(row:dict|None)->str:
        if not row:return "Nothing upcoming in the cached rota"
        day=date.fromisoformat(row["schedule_date"]);return day.strftime("%A · %d %b %Y")
