from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QVBoxLayout, QWidget
)

from .database import Database
from .dialogs import CommandPalette
from .gym import GymDashboardPage, GymMealsPage, GymNutritionPage, GymProgressPage, GymTrainingPage
from .intelligence_screen import IntelligencePage
from .mobile_sync import MobileSyncManager
from .screens import (
    BudgetsPage, CalendarPage, CustomerContactPage, DashboardPage, DebtPage, GoalsPage, InspectionPage, KPITrackerPage, ReportsPage,
    ScenarioPage, SettingsPage, StockLevelPage, SuccessChecklistPage, TodayTodoPage, TransactionsPage, VehicleDeskPage, VehicleHistoryPage,
    WhatsAppTemplatesPage
)
from .style import COLORS


NAV_SECTIONS = [
    ("leads", "LEADS", COLORS["purple"], [("todo", "✓", "Today's to-do"), ("success", "★", "Checklist to success"), ("kpi", "◫", "KPI tracker"), ("stock", "▦", "Stock level"), ("vehicles", "◈", "Vehicle desk"), ("vehicle_history", "◷", "Vehicle performance"), ("calendar", "▣", "Calendar")]),
    ("ai", "RUNWAY AI", COLORS["cyan"], [("intelligence", "✦", "Buying intelligence")]),
    ("other", "MISC / OTHER", COLORS["amber"], [("contacts", "◉", "Customer contact"), ("inspection", "⌕", "Inspection"), ("templates", "✉", "WhatsApp templates"), ("settings", "⚙", "Settings")]),
]
NAVIGATION = [item for _,_,_,items in NAV_SECTIONS for item in items]
COMMAND_MOD = "Meta" if sys.platform == "darwin" else "Ctrl"
COMMAND_LABEL = "⌘" if sys.platform == "darwin" else "Ctrl"


class MainWindow(QMainWindow):
    def __init__(self, db: Database, icon_path: Path | None = None):
        super().__init__(); self.db=db; self.icon_path=icon_path; self.setWindowTitle("DXB RUNWAY Intelligence · Buying Command Centre"); self.setMinimumSize(1100,720); self.resize(1480,920)
        if icon_path and icon_path.exists(): self.setWindowIcon(QIcon(str(icon_path)))
        root=QWidget(); root.setObjectName("appRoot"); self.setCentralWidget(root); shell=QHBoxLayout(root); shell.setContentsMargins(0,0,0,0); shell.setSpacing(0)
        self.sidebar=QFrame(); self.sidebar.setObjectName("sidebar"); self.sidebar.setMinimumWidth(244); self.sidebar.setMaximumWidth(244); side=QVBoxLayout(self.sidebar); side.setContentsMargins(12,14,12,14); side.setSpacing(5)
        brand_row=QHBoxLayout(); self.brand_icon=QLabel("DR"); self.brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter); self.brand_icon.setFixedSize(34,34); self.brand_icon.setStyleSheet(f"background:#16242e;color:{COLORS['cyan']};border:1px solid #294b5b;border-radius:10px;font-weight:900")
        self.brand=QLabel("DXB RUNWAY AI"); self.brand.setObjectName("brand"); brand_row.addWidget(self.brand_icon); brand_row.addWidget(self.brand); brand_row.addStretch(); self.collapse=QPushButton("‹"); self.collapse.setFixedSize(30,30); self.collapse.setToolTip("Collapse sidebar"); self.collapse.clicked.connect(self.toggle_sidebar); brand_row.addWidget(self.collapse); side.addLayout(brand_row); side.addSpacing(10)
        self.workspace_label=QLabel("YOUR WORKSPACE"); self.workspace_label.setObjectName("eyebrow"); side.addWidget(self.workspace_label); side.addSpacing(2)
        self.nav_buttons={}; self.page_keys=[]; self.section_headers={}
        nav_scroll=QScrollArea(); nav_scroll.setWidgetResizable(True); nav_scroll.setFrameShape(QFrame.Shape.NoFrame); nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); nav_scroll.setStyleSheet("QScrollArea{background:transparent;border:none} QScrollArea > QWidget > QWidget{background:transparent}")
        nav_host=QWidget(); nav_side=QVBoxLayout(nav_host); nav_side.setContentsMargins(0,0,0,0); nav_side.setSpacing(5); nav_scroll.setWidget(nav_host)

        def add_nav(key:str,icon:str,label:str,section:str)->None:
            button=QPushButton(f"{icon}    {label}"); button.setObjectName("nav"); button.setProperty("section",section); button.setCheckable(True); button.clicked.connect(lambda checked,k=key:self.navigate(k)); button.setMinimumHeight(38); button.setToolTip(label); nav_side.addWidget(button); self.nav_buttons[key]=button

        for section,title,color,items in NAV_SECTIONS:
            header=QFrame(); header.setProperty("navGroup",True); header.setProperty("section",section); header_l=QHBoxLayout(header); header_l.setContentsMargins(10,6,8,6); header_l.setSpacing(7)
            group_label=QLabel(f"●  {title}"); group_label.setStyleSheet(f"color:{color};font-size:10px;font-weight:800;letter-spacing:1px"); header_l.addWidget(group_label); header_l.addStretch()
            count=QLabel(str(len(items))); count.setAlignment(Qt.AlignmentFlag.AlignCenter); count.setFixedSize(20,20); count.setStyleSheet(f"background:{color};color:#091016;border-radius:10px;font-size:10px;font-weight:900"); header_l.addWidget(count)
            nav_side.addWidget(header); self.section_headers[section]=(header,group_label,count,title,color)
            for key,icon,label in items: add_nav(key,icon,label,section)
            nav_side.addSpacing(5)
        nav_side.addStretch(); side.addWidget(nav_scroll,1); privacy=QFrame(); privacy.setProperty("card",True); pl=QVBoxLayout(privacy); pl.setContentsMargins(11,10,11,10); self.privacy_lock=QLabel("●  PRIVATE SYNC"); self.privacy_lock.setStyleSheet(f"color:{COLORS['green']};font-size:10px;font-weight:800"); pl.addWidget(self.privacy_lock); self.privacy_copy=QLabel("Mac is source · no telemetry"); self.privacy_copy.setObjectName("muted"); pl.addWidget(self.privacy_copy); side.addWidget(privacy); shell.addWidget(self.sidebar)
        right=QVBoxLayout(); right.setContentsMargins(0,0,0,0); right.setSpacing(0); top=QFrame(); top.setObjectName("topbar"); tl=QHBoxLayout(top); tl.setContentsMargins(20,10,20,10); self.context=QLabel("BUYING INTELLIGENCE"); self.context.setObjectName("eyebrow"); tl.addWidget(self.context); tl.addStretch(); self.sync_status=QLabel("Private sync checking…"); self.sync_status.setObjectName("muted"); tl.addWidget(self.sync_status); command=QPushButton(f"⌕  Search or command     {COMMAND_LABEL} K"); command.clicked.connect(self.open_palette); tl.addWidget(command); right.addWidget(top)
        self.stack=QStackedWidget(); right.addWidget(self.stack,1); shell.addLayout(right,1)
        # Legacy pages remain constructible for data compatibility, but are intentionally absent from navigation in this edition.
        self.pages={"dashboard":DashboardPage(db),"todo":TodayTodoPage(db),"success":SuccessChecklistPage(db),"kpi":KPITrackerPage(db),"contacts":CustomerContactPage(db),"inspection":InspectionPage(db),"templates":WhatsAppTemplatesPage(db),"stock":StockLevelPage(db),"vehicles":VehicleDeskPage(db),"gym_today":GymDashboardPage(db),"gym_training":GymTrainingPage(db),"gym_nutrition":GymNutritionPage(db),"gym_progress":GymProgressPage(db),"gym_meals":GymMealsPage(db),"transactions":TransactionsPage(db),"debt":DebtPage(db),"scenarios":ScenarioPage(db),"budgets":BudgetsPage(db),"calendar":CalendarPage(db),"goals":GoalsPage(db),"vehicle_history":VehicleHistoryPage(db),"reports":ReportsPage(db),"intelligence":IntelligencePage(db),"settings":SettingsPage(db)}
        for key,page in self.pages.items(): self.stack.addWidget(page); self.page_keys.append(key)
        self.mobile_sync=MobileSyncManager(db,self); self.mobile_sync.status_changed.connect(self.set_sync_status)
        for page in self.pages.values(): page.changed.connect(self.refresh_all); page.changed.connect(self.mobile_sync.schedule)
        QShortcut(QKeySequence(f"{COMMAND_MOD}+K"),self,activated=self.open_palette); QShortcut(QKeySequence(f"{COMMAND_MOD}+1"),self,activated=lambda:self.navigate("intelligence")); QShortcut(QKeySequence("F5"),self,activated=self.refresh_all)
        self.compact=False; self.navigate("intelligence"); QTimer.singleShot(1200,self.mobile_sync.schedule)

    def set_sync_status(self,text:str,okay:bool)->None:
        self.sync_status.setText(text); self.sync_status.setStyleSheet(f"color:{COLORS['green'] if okay else COLORS['muted']};font-size:10px")

    def navigate(self,key:str)->None:
        if key not in self.pages:return
        page=self.pages[key]; self.stack.setCurrentWidget(page); self.context.setText(next((label.upper() for k,_,label in NAVIGATION if k==key), key.replace("_", " ").upper()))
        for k,button in self.nav_buttons.items():button.setChecked(k==key)
        page.refresh()

    def refresh_all(self)->None:
        for page in self.pages.values():
            try: page.refresh()
            except Exception: pass

    def toggle_sidebar(self)->None:
        self.compact=not self.compact; start=self.sidebar.width(); end=72 if self.compact else 244; self.sidebar.setMinimumWidth(end)
        animation=QPropertyAnimation(self.sidebar,b"maximumWidth",self); animation.setDuration(180); animation.setStartValue(start); animation.setEndValue(end); animation.setEasingCurve(QEasingCurve.Type.OutCubic); animation.start(); self._sidebar_animation=animation
        self.brand.setVisible(not self.compact); self.workspace_label.setVisible(not self.compact); self.privacy_copy.setVisible(not self.compact); self.collapse.setText("›" if self.compact else "‹"); self.collapse.setToolTip("Expand sidebar" if self.compact else "Collapse sidebar"); self.privacy_lock.setText("●" if self.compact else "●  PRIVATE SYNC"); self.privacy_lock.setAlignment(Qt.AlignmentFlag.AlignCenter if self.compact else Qt.AlignmentFlag.AlignLeft)
        for key,icon,label in NAVIGATION:self.nav_buttons[key].setText(icon if self.compact else f"{icon}    {label}");self.nav_buttons[key].setToolTip(label)
        for header,label,count,title,color in self.section_headers.values():
            label.setText("●" if self.compact else f"●  {title}"); label.setAlignment(Qt.AlignmentFlag.AlignCenter if self.compact else Qt.AlignmentFlag.AlignLeft); count.setVisible(not self.compact); header.layout().setContentsMargins(0,4,0,4) if self.compact else header.layout().setContentsMargins(10,6,8,6)

    def open_palette(self)->None:
        commands=[("Open buying intelligence","nav:intelligence"),("Open today's to-do list","nav:todo"),("Open checklist to success","nav:success"),("Open KPI tracker","nav:kpi"),("Open customer contact","nav:contacts"),("Open inspection","nav:inspection"),("Open WhatsApp templates","nav:templates"),("Open stock level","nav:stock"),("Open vehicle desk","nav:vehicles"),("Open vehicle performance","nav:vehicle_history"),("Open calendar","nav:calendar"),("Open settings","nav:settings"),("Refresh all data","refresh")]
        palette=CommandPalette(commands,self); palette.command_selected.connect(self.execute_command); center=self.geometry().center(); palette.move(center.x()-palette.width()//2,self.geometry().top()+90); palette.exec()

    def execute_command(self,command:str)->None:
        if command.startswith("nav:"):self.navigate(command.split(":",1)[1])
        elif command=="refresh":self.refresh_all()

    def resizeEvent(self,event)->None:
        super().resizeEvent(event)
        if self.width()<1220 and not self.compact:self.toggle_sidebar()
