from __future__ import annotations

COLORS = {
    "bg": "#080b10", "sidebar": "#0b0f15", "panel": "#10151d", "panel2": "#141a24",
    "border": "#202937", "border2": "#2b3545", "text": "#f3f7fb", "muted": "#8894a7",
    "cyan": "#4dd8ff", "green": "#31d69b", "purple": "#927dff", "amber": "#f4b740",
    "red": "#ff5d73", "orange": "#ff8a4c",
}

APP_QSS = f"""
* {{ font-family: "Segoe UI Variable", "Segoe UI"; font-size: 13px; color: {COLORS['text']}; }}
QMainWindow, QDialog, QWidget#appRoot {{ background: {COLORS['bg']}; }}
QWidget {{ outline: none; }}
QFrame#sidebar {{ background: {COLORS['sidebar']}; border-right: 1px solid {COLORS['border']}; }}
QFrame#topbar {{ background: {COLORS['bg']}; border-bottom: 1px solid {COLORS['border']}; }}
QFrame[card="true"] {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']}; border-radius: 14px; }}
QFrame[card="true"]:hover {{ border-color: {COLORS['border2']}; background: {COLORS['panel2']}; }}
QLabel#brand {{ font-size: 15px; font-weight: 800; letter-spacing: 1px; }}
QLabel#eyebrow {{ color: {COLORS['muted']}; font-size: 10px; font-weight: 700; letter-spacing: 1px; }}
QLabel#pageTitle {{ font-size: 24px; font-weight: 730; }}
QLabel#heroValue {{ font-size: 34px; font-weight: 760; }}
QLabel#metricValue {{ font-size: 21px; font-weight: 720; }}
QLabel#muted {{ color: {COLORS['muted']}; }}
QLabel[positive="true"] {{ color: {COLORS['green']}; }}
QLabel[warning="true"] {{ color: {COLORS['amber']}; }}
QLabel[danger="true"] {{ color: {COLORS['red']}; }}
QPushButton {{ background: {COLORS['panel2']}; border: 1px solid {COLORS['border2']}; border-radius: 8px; padding: 8px 13px; font-weight: 600; }}
QPushButton:hover {{ background: #1b2431; border-color: #3b4b61; }}
QPushButton:pressed {{ background: #0d1118; }}
QPushButton[primary="true"] {{ background: {COLORS['cyan']}; color: #071016; border: none; }}
QPushButton[primary="true"]:hover {{ background: #7be3ff; }}
QPushButton[danger="true"] {{ color: {COLORS['red']}; }}
QPushButton#nav {{ background: transparent; border: none; text-align: left; padding: 9px 12px; color: {COLORS['muted']}; border-radius: 8px; }}
QPushButton#nav:hover {{ background: #121923; color: {COLORS['text']}; }}
QPushButton#nav:checked {{ background: #15202a; color: {COLORS['cyan']}; border: 1px solid #233747; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit, QTextEdit {{
  background: #0c1118; border: 1px solid {COLORS['border2']}; border-radius: 8px; padding: 8px; selection-background-color: {COLORS['purple']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QDateTimeEdit:focus, QTextEdit:focus {{ border-color: {COLORS['cyan']}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {COLORS['panel2']}; border: 1px solid {COLORS['border2']}; selection-background-color: #26364a; }}
QTableWidget {{ background: transparent; alternate-background-color: #0d1219; border: 1px solid {COLORS['border']}; border-radius: 10px; gridline-color: {COLORS['border']}; }}
QTableWidget::item {{ padding: 8px; border-bottom: 1px solid #171e28; }}
QTableWidget::item:selected {{ background: #1b3443; }}
QHeaderView::section {{ background: #0d1219; color: {COLORS['muted']}; padding: 9px; border: none; border-bottom: 1px solid {COLORS['border']}; font-size: 10px; font-weight: 700; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2b3545; border-radius: 4px; min-height: 28px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QProgressBar {{ background: #080c12; border: none; border-radius: 4px; height: 7px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {COLORS['green']}; border-radius: 4px; }}
QTabWidget::pane {{ border: 1px solid {COLORS['border']}; border-radius: 10px; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {COLORS['muted']}; padding: 9px 14px; }}
QTabBar::tab:selected {{ color: {COLORS['cyan']}; border-bottom: 2px solid {COLORS['cyan']}; }}
QToolTip {{ background: #1a2230; color: white; border: 1px solid #354157; padding: 6px; }}
QCalendarWidget QWidget {{ alternate-background-color: {COLORS['panel2']}; }}
QCalendarWidget QToolButton {{ background: transparent; border: none; }}
"""

