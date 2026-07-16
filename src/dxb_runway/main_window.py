from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget
)

from .database import Database
from .dialogs import CommandPalette, TransactionDialog
from .screens import (
    BudgetsPage, CalendarPage, DashboardPage, DebtPage, EarningsPage, GoalsPage, ReportsPage,
    ScenarioPage, SettingsPage, TransactionsPage, VehicleDeskPage
)
from .style import COLORS


NAVIGATION = [
    ("dashboard", "⌂", "Overview"), ("vehicles", "▱", "Vehicle desk"), ("transactions", "↕", "Transactions"), ("debt", "◇", "Debt control"),
    ("earnings", "◆", "Salary + commission"), ("scenarios", "⌁", "Scenario lab"), ("budgets", "▤", "Budgets"),
    ("calendar", "□", "Calendar"), ("goals", "◎", "Momentum"), ("reports", "▥", "Reports"),
    ("settings", "⚙", "Settings"),
]


class MainWindow(QMainWindow):
    def __init__(self, db: Database, icon_path: Path | None = None):
        super().__init__(); self.db=db; self.icon_path=icon_path; self.setWindowTitle("DXB RUNWAY · Financial Command Centre"); self.setMinimumSize(1100,720); self.resize(1480,920)
        if icon_path and icon_path.exists(): self.setWindowIcon(QIcon(str(icon_path)))
        root=QWidget(); root.setObjectName("appRoot"); self.setCentralWidget(root); shell=QHBoxLayout(root); shell.setContentsMargins(0,0,0,0); shell.setSpacing(0)
        self.sidebar=QFrame(); self.sidebar.setObjectName("sidebar"); self.sidebar.setMinimumWidth(228); self.sidebar.setMaximumWidth(228); side=QVBoxLayout(self.sidebar); side.setContentsMargins(12,14,12,14); side.setSpacing(6)
        brand_row=QHBoxLayout(); self.brand_icon=QLabel("DR"); self.brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter); self.brand_icon.setFixedSize(34,34); self.brand_icon.setStyleSheet(f"background:#16242e;color:{COLORS['cyan']};border:1px solid #294b5b;border-radius:10px;font-weight:900")
        self.brand=QLabel("DXB RUNWAY"); self.brand.setObjectName("brand"); brand_row.addWidget(self.brand_icon); brand_row.addWidget(self.brand); brand_row.addStretch(); collapse=QPushButton("‹"); collapse.setFixedSize(30,30); collapse.clicked.connect(self.toggle_sidebar); brand_row.addWidget(collapse); side.addLayout(brand_row); side.addSpacing(12)
        workspace=QLabel("PRIVATE WORKSPACE"); workspace.setObjectName("eyebrow"); side.addWidget(workspace)
        self.nav_buttons={}; self.page_keys=[]
        for key,icon,label in NAVIGATION:
            button=QPushButton(f"{icon}    {label}"); button.setObjectName("nav"); button.setCheckable(True); button.clicked.connect(lambda checked,k=key:self.navigate(k)); button.setMinimumHeight(38); side.addWidget(button); self.nav_buttons[key]=button
            if key=="calendar": side.addSpacing(8)
        side.addStretch(); privacy=QFrame(); privacy.setProperty("card",True); pl=QVBoxLayout(privacy); pl.setContentsMargins(11,10,11,10); lock=QLabel("●  LOCAL & PRIVATE"); lock.setStyleSheet(f"color:{COLORS['green']};font-size:10px;font-weight:800"); pl.addWidget(lock); self.privacy_copy=QLabel("No cloud · no telemetry"); self.privacy_copy.setObjectName("muted"); pl.addWidget(self.privacy_copy); side.addWidget(privacy); shell.addWidget(self.sidebar)
        right=QVBoxLayout(); right.setContentsMargins(0,0,0,0); right.setSpacing(0); top=QFrame(); top.setObjectName("topbar"); tl=QHBoxLayout(top); tl.setContentsMargins(20,10,20,10); self.context=QLabel("OVERVIEW"); self.context.setObjectName("eyebrow"); tl.addWidget(self.context); tl.addStretch(); command=QPushButton("⌕  Search or command     Ctrl K"); command.clicked.connect(self.open_palette); tl.addWidget(command); quick=QPushButton("＋"); quick.setToolTip("Quick add transaction · Ctrl+N"); quick.setProperty("primary",True); quick.clicked.connect(self.quick_add); tl.addWidget(quick); right.addWidget(top)
        self.stack=QStackedWidget(); right.addWidget(self.stack,1); shell.addLayout(right,1)
        self.pages={"dashboard":DashboardPage(db),"vehicles":VehicleDeskPage(db),"transactions":TransactionsPage(db),"debt":DebtPage(db),"earnings":EarningsPage(db),"scenarios":ScenarioPage(db),"budgets":BudgetsPage(db),"calendar":CalendarPage(db),"goals":GoalsPage(db),"reports":ReportsPage(db),"settings":SettingsPage(db)}
        for key,_,_ in NAVIGATION: self.stack.addWidget(self.pages[key]); self.page_keys.append(key)
        self.pages["dashboard"].quick_add.connect(self.quick_add)
        for page in self.pages.values(): page.changed.connect(self.refresh_all)
        QShortcut(QKeySequence("Ctrl+K"),self,activated=self.open_palette); QShortcut(QKeySequence("Ctrl+N"),self,activated=self.quick_add); QShortcut(QKeySequence("Ctrl+1"),self,activated=lambda:self.navigate("dashboard")); QShortcut(QKeySequence("Ctrl+2"),self,activated=lambda:self.navigate("transactions")); QShortcut(QKeySequence("Ctrl+3"),self,activated=lambda:self.navigate("scenarios")); QShortcut(QKeySequence("F5"),self,activated=self.refresh_all)
        self.compact=False; self.navigate("dashboard")

    def navigate(self,key:str)->None:
        if key not in self.pages:return
        self.stack.setCurrentWidget(self.pages[key]); self.context.setText(next(label.upper() for k,_,label in NAVIGATION if k==key))
        for k,button in self.nav_buttons.items():button.setChecked(k==key)
        self.pages[key].refresh()

    def refresh_all(self)->None:
        for page in self.pages.values():
            try: page.refresh()
            except Exception: pass

    def quick_add(self)->None:
        dialog=TransactionDialog(self.db,parent=self)
        if dialog.exec():self.db.add_transaction(dialog.values());self.refresh_all()

    def toggle_sidebar(self)->None:
        self.compact=not self.compact; start=self.sidebar.width(); end=72 if self.compact else 228; self.sidebar.setMinimumWidth(end)
        animation=QPropertyAnimation(self.sidebar,b"maximumWidth",self); animation.setDuration(180); animation.setStartValue(start); animation.setEndValue(end); animation.setEasingCurve(QEasingCurve.Type.OutCubic); animation.start(); self._sidebar_animation=animation
        self.brand.setVisible(not self.compact); self.privacy_copy.setVisible(not self.compact)
        for key,icon,label in NAVIGATION:self.nav_buttons[key].setText(icon if self.compact else f"{icon}    {label}");self.nav_buttons[key].setToolTip(label)

    def open_palette(self)->None:
        commands=[("Go to overview","nav:dashboard"),("Open vehicle desk","nav:vehicles"),("Go to transactions","nav:transactions"),("Go to debt control","nav:debt"),("Open salary & commission","nav:earnings"),("Open scenario lab","nav:scenarios"),("Open budgets","nav:budgets"),("Open financial calendar","nav:calendar"),("Open reports","nav:reports"),("Open settings","nav:settings"),("Add transaction","add"),("Refresh all data","refresh")]
        palette=CommandPalette(commands,self); palette.command_selected.connect(self.execute_command); center=self.geometry().center(); palette.move(center.x()-palette.width()//2,self.geometry().top()+90); palette.exec()

    def execute_command(self,command:str)->None:
        if command.startswith("nav:"):self.navigate(command.split(":",1)[1])
        elif command=="add":self.quick_add()
        elif command=="refresh":self.refresh_all()

    def resizeEvent(self,event)->None:
        super().resizeEvent(event)
        if self.width()<1220 and not self.compact:self.toggle_sidebar()
