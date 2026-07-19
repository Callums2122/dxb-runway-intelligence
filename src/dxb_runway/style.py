from __future__ import annotations

# A quiet, information-dense desktop foundation with brighter moments reserved
# for state, progress and action. Keeping the palette here makes every screen
# feel like one product rather than a collection of separate tools.
COLORS = {
    "bg": "#070b12", "sidebar": "#090e16", "panel": "#0e1520", "panel2": "#131c29",
    "border": "#1c2938", "border2": "#2a3b4f", "text": "#f4f7fb", "muted": "#8fa0b7",
    "cyan": "#47d7ff", "green": "#39dda5", "purple": "#9a82ff", "amber": "#ffc554",
    "red": "#ff6480", "orange": "#ff8b5f", "blue": "#5b8cff", "pink": "#ff70b7",
}

APP_QSS = f"""
* {{ font-family: "Segoe UI Variable", "Segoe UI"; font-size: 13px; color: {COLORS['text']}; }}
QMainWindow, QDialog, QWidget#appRoot {{ background: {COLORS['bg']}; }}
QWidget {{ outline: none; }}
QFrame#sidebar {{ background: {COLORS['sidebar']}; border-right: 1px solid {COLORS['border']}; }}
QFrame#topbar {{ background: #090e16; border-bottom: 1px solid {COLORS['border']}; }}
QFrame[card="true"] {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']}; border-radius: 16px; }}
QFrame[card="true"]:hover {{ border-color: {COLORS['border2']}; background: #111a27; }}
QFrame#accentRail {{ border: none; border-radius: 2px; min-height: 3px; max-height: 3px; }}
QLabel#brand {{ font-size: 15px; font-weight: 800; letter-spacing: 1px; }}
QLabel#eyebrow {{ color: #91a6c1; font-size: 10px; font-weight: 750; letter-spacing: 1.2px; }}
QLabel#pageTitle {{ font-size: 25px; font-weight: 760; letter-spacing: -0.3px; }}
QLabel#sectionTitle {{ font-size: 17px; font-weight: 730; }}
QLabel#heroValue {{ font-size: 35px; font-weight: 780; letter-spacing: -0.6px; }}
QLabel#metricValue {{ font-size: 22px; font-weight: 750; letter-spacing: -0.25px; }}
QLabel#muted {{ color: {COLORS['muted']}; }}
QLabel[positive="true"] {{ color: {COLORS['green']}; }}
QLabel[warning="true"] {{ color: {COLORS['amber']}; }}
QLabel[danger="true"] {{ color: {COLORS['red']}; }}
QPushButton {{ background: #121b28; border: 1px solid {COLORS['border2']}; border-radius: 9px; padding: 8px 14px; font-weight: 650; }}
QPushButton:hover {{ background: #182536; border-color: #405873; }}
QPushButton:pressed {{ background: #0b111a; padding-top: 9px; padding-bottom: 7px; }}
QPushButton:disabled {{ color: #58677b; background: #0c121b; border-color: #182231; }}
QPushButton[primary="true"] {{ background: {COLORS['cyan']}; color: #041018; border: none; font-weight: 750; }}
QPushButton[primary="true"]:hover {{ background: #78e2ff; }}
QPushButton[danger="true"] {{ color: {COLORS['red']}; }}
QFrame[navGroup="true"] {{ border-radius: 10px; border-left: 3px solid transparent; }}
QFrame[navGroup="true"][section="leads"] {{ background: #151329; border-left-color: {COLORS['purple']}; }}
QFrame[navGroup="true"][section="money"] {{ background: #0e241e; border-left-color: {COLORS['green']}; }}
QFrame[navGroup="true"][section="other"] {{ background: #281e0e; border-left-color: {COLORS['amber']}; }}
QPushButton#nav {{ background: transparent; border: 1px solid transparent; text-align: left; padding: 9px 12px; color: #91a0b5; border-radius: 9px; }}
QPushButton#nav:hover {{ background: #121d2a; color: {COLORS['text']}; border-color: #1e2d3f; }}
QPushButton#nav[section="overview"] {{ background: #0f1925; color: #b7c5d6; border-color: #1b2a3a; min-height: 22px; }}
QPushButton#nav[section="overview"]:hover {{ background: #142735; color: {COLORS['cyan']}; border-color: #28485a; }}
QPushButton#nav[section="overview"]:checked {{ background: #153246; color: {COLORS['cyan']}; border-color: #2b637f; }}
QPushButton#nav[section="leads"]:checked {{ background: #241e43; color: #c5b9ff; border-color: #54468f; }}
QPushButton#nav[section="money"]:checked {{ background: #153a30; color: {COLORS['green']}; border-color: #2c7059; }}
QPushButton#nav[section="other"]:checked {{ background: #3a2a12; color: #ffd77e; border-color: #765822; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit, QTextEdit {{
  background: #0a111b; border: 1px solid {COLORS['border2']}; border-radius: 9px; padding: 8px 10px; selection-background-color: {COLORS['purple']};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QDateEdit:hover, QDateTimeEdit:hover {{ border-color: #3a4c63; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QDateTimeEdit:focus, QTextEdit:focus {{ border: 1px solid {COLORS['cyan']}; background: #0d1723; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{ background: {COLORS['panel2']}; border: 1px solid {COLORS['border2']}; selection-background-color: #25384f; padding: 5px; }}
QTableWidget {{ background: #090f17; alternate-background-color: #0c131d; border: 1px solid {COLORS['border']}; border-radius: 12px; gridline-color: transparent; }}
QTableWidget::item {{ padding: 9px; border-bottom: 1px solid #182331; }}
QTableWidget::item:hover {{ background: #111d2a; }}
QTableWidget::item:selected {{ background: #173348; color: #ffffff; }}
QHeaderView::section {{ background: #0d151f; color: #8296b0; padding: 10px; border: none; border-bottom: 1px solid {COLORS['border']}; font-size: 10px; font-weight: 750; letter-spacing: .6px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 3px 2px; }}
QScrollBar::handle:vertical {{ background: #2b3c50; border-radius: 4px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: #3a526d; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; }}
QScrollBar::handle:horizontal {{ background: #2b3c50; border-radius: 4px; min-width: 32px; }}
QProgressBar {{ background: #080d14; border: 1px solid #15202d; border-radius: 5px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {COLORS['green']}; border-radius: 4px; }}
QTabWidget::pane {{ border: 1px solid {COLORS['border']}; border-radius: 12px; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {COLORS['muted']}; padding: 10px 15px; }}
QTabBar::tab:hover {{ color: {COLORS['text']}; }}
QTabBar::tab:selected {{ color: {COLORS['cyan']}; border-bottom: 2px solid {COLORS['cyan']}; }}
QToolTip {{ background: #172334; color: white; border: 1px solid #3a4f69; border-radius: 6px; padding: 7px; }}
QCalendarWidget QWidget {{ alternate-background-color: {COLORS['panel2']}; }}
QCalendarWidget QToolButton {{ background: transparent; border: none; }}
QLabel#calendarMonth {{ font-size: 22px; font-weight: 760; }}
QLabel#calendarDay {{ font-size: 25px; font-weight: 760; line-height: 1.15; }}
QLabel#budgetMonth {{ font-size: 17px; font-weight: 730; min-width: 118px; qproperty-alignment: AlignCenter; }}
QLabel#budgetHero {{ font-size: 28px; font-weight: 770; }}
QPushButton#calendarNav {{ background: #142031; border: 1px solid {COLORS['border2']}; border-radius: 12px; padding: 0; font-size: 25px; font-weight: 500; }}
QPushButton#calendarNav:hover {{ background: #1b3043; border-color: {COLORS['cyan']}; color: {COLORS['cyan']}; }}
QPushButton#calendarNav:pressed {{ background: #0d151e; }}
QPushButton#calendarToday {{ background: #112a37; color: {COLORS['cyan']}; border-color: #25526a; border-radius: 10px; padding: 9px 16px; }}
QPushButton#calendarToday:hover {{ background: #183b4c; border-color: {COLORS['cyan']}; }}
QFrame#calendarDivider {{ color: {COLORS['border']}; background: {COLORS['border']}; border: none; max-height: 1px; }}
QFrame#calendarEmpty {{ background: #0b121c; border: 1px dashed {COLORS['border2']}; border-radius: 13px; }}
QLabel#calendarEmptyIcon {{ color: {COLORS['purple']}; font-size: 25px; }}
"""
