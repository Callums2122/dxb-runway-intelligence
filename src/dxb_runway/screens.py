from __future__ import annotations

import calendar
import json
import math
import os
import re
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QDate, QEvent, QFile, QObject, QRunnable, QStandardPaths, QThreadPool, QTimer, Qt, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCalendarWidget, QCheckBox, QComboBox, QDateEdit, QDialog, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QStyledItemDelegate, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget
)

from .database import Database
from .contact_import import import_downloaded_contacts
from .deal_drive import DealDriveClient, DealDriveError, KeychainCredentials
from .google_schedule import GoogleSheetsReadOnlyClient, GoogleScheduleError, SCOPE
from .intelligence import analyse_opportunity, split_vehicle, stock_research_subject
from .market_watchlist import research_vehicle_now
from .pipeline import rematch_cached_appointments, spreadsheet_id
from .dialogs import CustomerContactDialog, InspectionDateDialog, MessageTemplateDialog, MoneyBox, PayCardDialog, SellVehicleDialog, TransactionDialog, VehicleDialog
from .domain import (
    CommissionTier, FinancialPosition, TARGET_PERCENTAGES, basic_salary, calculate_earnings, calculate_timed_runway, card_utilisation,
    dual_amount, estimate_monthly_interest, gbp_equivalent, money, repayment_months, simulate_scenario, to_aed,
    utilisation_status
)
from .reporting import create_financial_pdf
from .style import COLORS
from .widgets import Card, MetricCard, RingWidget, SectionHeader, bar_chart, clear_layout, line_chart, pie_chart


def page_scroll(content: QWidget) -> QScrollArea:
    area = QScrollArea(); area.setWidgetResizable(True); area.setWidget(content); area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return area


def customer_vehicle_year(stored_value: int) -> int | str:
    value=int(stored_value)
    if value==0: return "Year unknown"
    return value if 2018<=value<=2026 else max(2018,min(2026,2026-value))


def display_call_date(stored_value: str) -> str:
    try: return date.fromisoformat(str(stored_value)[:10]).strftime("%d %b %Y")
    except ValueError: return str(stored_value)


def call_month_pace(total_calls:int,month:str,target:int=240,today:date|None=None)->dict[str,object]:
    today=today or date.today(); year,month_number=(int(value) for value in month.split("-")); days=calendar.monthrange(year,month_number)[1]
    selected=(year,month_number); current=(today.year,today.month); remaining=max(0,target-int(total_calls))
    if selected<current:
        return {"state":"hit" if total_calls>=target else "missed","pace_delta":int(total_calls)-target,"remaining":remaining,"days_left":0,"average_needed":0.0,"current_average":float(total_calls)/days}
    completed_days=0 if selected>current else max(0,today.day-1); days_left=days-completed_days
    required_by_now=math.ceil(target*completed_days/days); delta=int(total_calls)-required_by_now
    state="not_started" if selected>current else "ahead" if delta>=0 else "behind"
    elapsed_days=1 if selected>current else today.day
    current_average=float(total_calls)/elapsed_days
    return {"state":state,"pace_delta":delta,"remaining":remaining,"days_left":days_left,"average_needed":remaining/days_left if days_left else 0.0,"current_average":current_average}


def offer_route(listing_price:Decimal|float|int,offer:Decimal|float|int)->dict[str,object]:
    """Choose a conversation route from the offer-to-asking percentage."""
    asking=Decimal(str(listing_price)); cash_offer=Decimal(str(offer))
    percentage=float(cash_offer/asking*100) if asking>0 else 0.0
    if percentage>=90:
        return {"key":"strong","percentage":percentage,"title":"Lead with the offer","color":COLORS["green"],"detail":"This is a strong offer. Confirm availability, then use the number as your hook."}
    if percentage>=80:
        return {"key":"flexibility","percentage":percentage,"title":"Ask flexibility first","color":COLORS["amber"],"detail":"Learn how firm the seller is before revealing your offer."}
    return {"key":"qualify","percentage":percentage,"title":"Qualify motivation first","color":COLORS["pink"],"detail":"Your offer is well below asking. Learn their timing and realistic expectation before sharing it."}


def offer_message_steps(route_key:str,vehicle:str,listing_price:Decimal|float|int,offer:Decimal|float|int)->list[tuple[str,str]]:
    vehicle_text=vehicle.strip() or "vehicle"; asking=Decimal(str(listing_price)); cash_offer=Decimal(str(offer))
    opening=f"Hi, it’s Callum from Alba Cars regarding your {vehicle_text}. Is it still available?"
    offer_message=(f"No problem. I’ve had a look at the market and I’d be around AED {cash_offer:,.0f} cash, subject to inspection. "
                   "If we can make the numbers work, we can get you booked in and complete payment the same day. 🤝")
    if route_key=="strong":
        return [("1 · Confirm availability",opening),("2 · Lead with your offer",offer_message)]
    if route_key=="flexibility":
        flexibility=(f"Perfect, thank you. Are you fairly firm on your AED {asking:,.0f} asking price, or is there some room "
                     "if we can make it a quick, straightforward sale?")
        return [("1 · Confirm availability",opening),("2 · Ask about flexibility",flexibility),("3 · If they ask for your number",offer_message)]
    motivation="Perfect, thank you. Before I put a figure forward, may I ask whether you’re looking for a quick sale or mainly trying to achieve the full asking price?"
    expectation="And what is the best figure you would realistically consider for a quick, straightforward sale?"
    return [("1 · Confirm availability",opening),("2 · Qualify their motivation",motivation),("3 · Learn their expectation",expectation),("4 · If they ask for your number",offer_message)]


def monthly_kpi_results(db:Database,month:str,call_target:int=240)->list[tuple[str,str,str,bool]]:
    calls=sum(int(row["call_count"]) for row in db.kpi_calls(month)); work=db.kpi_work_days(month); avg_hours=sum(float(row["hours"]) for row in work)/len(work) if work else 0
    budget=db.performance_budget(month); cash_used=db.active_cash_stock_total(); spend_pct=float(cash_used/budget*100) if budget else 0
    sold=db.sold_vehicles(month); cash_profit=[float(row["realised_profit_aed"]) for row in sold if row["purchase_type"]=="cash"]; all_profit=[float(row["realised_profit_aed"]) for row in sold]; avg_cash=sum(cash_profit)/len(cash_profit) if cash_profit else 0; top=max(all_profit,default=0)
    stock=db.stock_vehicles(); pipeline_cash=[float(row["expected_profit_aed"]) for row in stock if row["purchase_type"]=="cash"]; pipeline_con=[float(row["expected_profit_aed"]) for row in stock if row["purchase_type"]=="consignment"]; avg_pc=sum(pipeline_cash)/len(pipeline_cash) if pipeline_cash else 0; avg_pcon=sum(pipeline_con)/len(pipeline_con) if pipeline_con else 0
    consignment_count=sum(1 for row in sold if row["purchase_type"]=="consignment" and float(row["realised_profit_aed"])>=20000); consignment_target=max(1,int((budget+Decimal("999999"))//Decimal("1000000")))
    year,month_number=(int(value) for value in month.split("-")); month_end=date(year,month_number,calendar.monthrange(year,month_number)[1]); eligible=[]
    for row in db.query("SELECT * FROM vehicles WHERE purchased_date<=? AND (sold_date IS NULL OR sold_date>=?)",(month_end.isoformat(),f"{month}-01")):
        start=date.fromisoformat(row["purchased_date"]); finish=date.fromisoformat(row["sold_date"]) if row["sold_date"] and row["sold_date"]<=month_end.isoformat() else month_end; eligible.append(max(0,(finish-start).days+1))
    avg_days=sum(eligible)/len(eligible) if eligible else 0
    return [("Call Maestro",f"{call_target} calls",f"{calls} calls",calls>=call_target),("Profit Wizard","AED 27,500 avg",f"AED {avg_cash:,.0f}",avg_cash>=27500),("Pipeline Gold","Cash 30k + Con 20k",f"AED {avg_pc:,.0f} / {avg_pcon:,.0f}",avg_pc>=30000 and avg_pcon>=20000),("Bayzat Champion","10h avg + 20 days",f"{avg_hours:.1f}h · {len(work)} days",avg_hours>=10 and len(work)>=20),("Top Gun Deal","AED 65,000",f"AED {top:,.0f}",top>=65000),("Big Spender","95% of budget",f"{spend_pct:.1f}%",spend_pct>=95),("Consignmenite",f"{consignment_target} qualifying sold",str(consignment_count),consignment_count>=consignment_target),("Lightweight","35 days or less",f"{avg_days:.1f} days",bool(eligible) and avg_days<=35)]


def monthly_kpi_adjustment(db:Database,month:str)->tuple[int,Decimal]:
    hit_count=sum(1 for *_,hit in monthly_kpi_results(db,month) if hit)
    return hit_count,Decimal("0.005")*hit_count


def vehicle_model_name(vehicle_name:str)->str:
    """Normalise a vehicle name for model-level performance averages."""
    cleaned=re.sub(r"^\s*(?:19|20)\d{2}\s+", "", str(vehicle_name).strip())
    return re.sub(r"\s+", " ", cleaned) or "Unknown vehicle"


def vehicle_speed_grade(days:Decimal|float|int)->str:
    """Grade stock velocity using the agreed day bands."""
    elapsed=Decimal(str(days))
    if elapsed<10: return "A+"
    if elapsed<=20: return "A"
    if elapsed<=30: return "B"
    if elapsed<=60: return "C"
    return "C-"


def vehicle_grade_color(grade:str)->str:
    return {"A+":COLORS["green"],"A":COLORS["cyan"],"B":COLORS["amber"],"C":COLORS["amber"],"C-":COLORS["red"]}.get(grade,COLORS["muted"])


def vehicle_margin_percent(profit:Decimal,cost:Decimal)->Decimal:
    return (profit/cost*Decimal("100")) if cost>0 else Decimal("0")


def table_item(text: str, alignment: Qt.AlignmentFlag | None = None, color: str | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if alignment: item.setTextAlignment(alignment)
    if color: item.setForeground(QColor(color))
    return item


CATEGORY_ICONS = {
    "Accommodation": "🏠", "Transport": "🚕", "Groceries": "🛒", "Restaurants": "🍽",
    "Flight/relocation": "✈", "Visa/administration": "🪪", "Utilities": "⚡", "Phone/internet": "📱",
    "Entertainment": "🎟", "Shopping": "🛍", "Credit card repayment": "💳", "Salary": "↗",
    "Commission": "◆", "Miscellaneous": "●",
}


def category_label(category: str | None) -> str:
    """Give transactions visual identity without changing their stored category."""
    name = category or "Other"
    return f"{CATEGORY_ICONS.get(name, '●')}  {name}"


def latest_occurrence_for_month(month_number: int, today: date | None = None) -> str:
    """Map a month name to its latest occurrence without exposing years in Vehicle Desk."""
    current=today or date.today()
    year=current.year if month_number<=current.month else current.year-1
    return f"{year:04d}-{month_number:02d}"


def contact_countdown(next_contact_date: str, today: date | None = None) -> str:
    current=today or date.today(); remaining=(date.fromisoformat(next_contact_date[:10])-current).days
    if remaining>1: return f"{remaining} days left"
    if remaining==1: return "1 day left"
    if remaining==0: return "Due today"
    overdue=abs(remaining); return f"Overdue by {overdue} day{'s' if overdue!=1 else ''}"


class TransactionHighlightDelegate(QStyledItemDelegate):
    def paint(self,painter,option,index)->None:
        super().paint(painter,option,index)
        if index.data(Qt.ItemDataRole.UserRole):
            painter.save(); painter.fillRect(option.rect,QColor(244,183,64,72)); painter.restore()


class Page(QWidget):
    changed = Signal()
    def __init__(self, db: Database): super().__init__(); self.db = db
    def refresh(self) -> None: pass


class PlayfulCalendar(QCalendarWidget):
    """A calmer, modern calendar with one month change per wheel gesture."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.event_colors: dict[QDate, list[str]] = {}
        self._last_wheel_at = 0.0
        self.setNavigationBarVisible(False)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)
        self.setGridVisible(False)
        self.setMouseTracking(True)
        self.setMinimumHeight(570)
        self.setStyleSheet(f"""
            QCalendarWidget {{ background: transparent; border: none; }}
            QCalendarWidget QWidget {{ background: transparent; alternate-background-color: transparent; }}
            QCalendarWidget QAbstractItemView {{
                background: transparent; border: none; selection-background-color: transparent;
                alternate-background-color: transparent;
            }}
            QCalendarWidget QHeaderView::section {{
                background: transparent; color: {COLORS['muted']}; border: none;
                padding: 12px 0 14px 0; font-size: 11px; font-weight: 700;
            }}
        """)
        self.installEventFilter(self)
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)

    def set_event_colors(self, event_colors: dict[QDate, list[str]]) -> None:
        self.event_colors = event_colors
        self.updateCells()

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Wheel:
            self.handle_wheel(event.angleDelta().y())
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def handle_wheel(self, delta: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        moved = bool(delta and (not self._last_wheel_at or now - self._last_wheel_at > 0.48))
        if moved:
            self.showPreviousMonth() if delta > 0 else self.showNextMonth()
        self._last_wheel_at = now
        return moved

    def paintCell(self, painter: QPainter, rect, day: QDate) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cell = rect.adjusted(7, 5, -7, -5)
        in_month = day.month() == self.monthShown() and day.year() == self.yearShown()
        selected = day == self.selectedDate()
        today = day == QDate.currentDate()

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#26364a"))
            painter.drawRoundedRect(cell, 13, 13)
        elif today:
            painter.setPen(QColor(COLORS["cyan"]))
            painter.setBrush(QColor("#10212b"))
            painter.drawRoundedRect(cell, 13, 13)

        color = QColor(COLORS["text"] if in_month else "#4d5868")
        if selected:
            color = QColor("#ffffff")
        painter.setPen(color)
        font = painter.font()
        font.setPointSize(11)
        font.setWeight(QFont.Weight.DemiBold if selected or today else QFont.Weight.Normal)
        painter.setFont(font)
        painter.drawText(cell.adjusted(0, -4, 0, 0), Qt.AlignmentFlag.AlignCenter, str(day.day()))

        dots = self.event_colors.get(day, [])[:3]
        if dots:
            diameter, gap = 6, 4
            total = len(dots) * diameter + (len(dots) - 1) * gap
            x = cell.center().x() - total / 2
            y = cell.bottom() - 11
            painter.setPen(Qt.PenStyle.NoPen)
            for dot_color in dots:
                painter.setBrush(QColor(dot_color))
                painter.drawEllipse(int(x), int(y), diameter, diameter)
                x += diameter + gap
        painter.restore()


class BudgetCategoryCard(Card):
    def __init__(self, name: str, color: str):
        super().__init__()
        self.name, self.color, self.spent, self.rate = name, color, Decimal("0"), Decimal("1")
        root=QVBoxLayout(self); root.setContentsMargins(16,15,16,15); root.setSpacing(9)
        top=QHBoxLayout(); title=QLabel("Food & groceries" if name=="Groceries" else name); title.setStyleSheet("font-size:15px;font-weight:700"); top.addWidget(title); top.addStretch()
        self.percent=QLabel("0%"); self.percent.setStyleSheet(f"color:{color};font-weight:700"); top.addWidget(self.percent); root.addLayout(top)
        self.spent_label=QLabel(); self.spent_label.setObjectName("muted"); root.addWidget(self.spent_label)
        self.progress=QProgressBar(); self.progress.setRange(0,100); self.progress.setTextVisible(False); self.progress.setStyleSheet(f"QProgressBar::chunk{{background:{color};border-radius:4px;}}"); root.addWidget(self.progress)
        plan_row=QHBoxLayout(); plan_copy=QLabel("MONTHLY LIMIT"); plan_copy.setObjectName("eyebrow"); plan_row.addWidget(plan_copy); plan_row.addStretch(); self.plan=MoneyBox(maximum=1_000_000); self.plan.setSuffix(" AED"); self.plan.setMaximumWidth(165); plan_row.addWidget(self.plan); root.addLayout(plan_row)
        self.remaining=QLabel(); self.remaining.setWordWrap(True); root.addWidget(self.remaining)

    def set_data(self, planned: float, spent: Decimal, rate: Decimal) -> None:
        self.spent, self.rate = spent, rate
        self.plan.blockSignals(True); self.plan.setValue(planned); self.plan.blockSignals(False)
        self.update_display()

    def update_display(self) -> None:
        planned=Decimal(str(self.plan.value())); remaining=planned-self.spent; used=min(100,int(self.spent/planned*100)) if planned else (100 if self.spent else 0)
        self.progress.setValue(used); self.percent.setText(f"{used}%")
        spent_aed,spent_gbp=dual_amount(self.spent,self.rate); self.spent_label.setText(f"Spent {spent_aed}  ·  {spent_gbp}")
        left_aed,left_gbp=dual_amount(remaining,self.rate,signed=True); self.remaining.setText(f"{left_aed}  /  {left_gbp} left")
        self.remaining.setStyleSheet(f"font-size:14px;font-weight:700;color:{COLORS['red'] if remaining<0 else COLORS['green']}")


class DashboardPage(Page):
    quick_add = Signal()
    def __init__(self, db: Database):
        super().__init__(db)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget(); self.layout = QVBoxLayout(content); self.layout.setContentsMargins(24, 22, 24, 28); self.layout.setSpacing(18)
        header = QHBoxLayout(); text = QVBoxLayout(); title = QLabel("Financial command centre"); title.setObjectName("pageTitle"); text.addWidget(title)
        self.subtitle = QLabel(); self.subtitle.setObjectName("muted"); text.addWidget(self.subtitle); header.addLayout(text); header.addStretch()
        add = QPushButton("＋  Quick add"); add.setProperty("primary", True); add.clicked.connect(self.quick_add); header.addWidget(add); self.layout.addLayout(header)
        self.hero = Card(); hero_layout = QHBoxLayout(self.hero); hero_layout.setContentsMargins(22, 20, 22, 20); hero_layout.setSpacing(24)
        run = QVBoxLayout(); eyebrow = QLabel("SURVIVAL STATUS"); eyebrow.setObjectName("eyebrow"); run.addWidget(eyebrow)
        self.runway = QLabel("RUNWAY: — DAYS"); self.runway.setObjectName("heroValue"); run.addWidget(self.runway)
        self.allowance = QLabel("SAFE DAILY ALLOWANCE: —"); self.allowance.setStyleSheet(f"font-size:16px;font-weight:700;color:{COLORS['green']}"); run.addWidget(self.allowance)
        self.basis = QLabel(); self.basis.setObjectName("muted"); self.basis.setWordWrap(True); run.addWidget(self.basis)
        self.status = QLabel(); self.status.setObjectName("muted"); self.status.setWordWrap(True); run.addWidget(self.status); hero_layout.addLayout(run, 1)
        self.ring = RingWidget(0); hero_layout.addWidget(self.ring); self.layout.addWidget(self.hero)
        daily=Card(); daily_layout=QVBoxLayout(daily); daily_layout.setContentsMargins(18,16,18,16); daily_layout.setSpacing(12)
        daily_layout.addWidget(SectionHeader("Daily spending guide","Your GBP 1,700 monthly spending cap, converted at the stored rate and divided across the days left. Updates from Transactions; setup costs and card repayments are ignored."))
        daily_grid=QGridLayout(); daily_grid.setSpacing(12); self.daily_metrics={}
        for index,(key,label,color) in enumerate([("limit","Today's spending limit",COLORS["cyan"]),("spent","Spent today",COLORS["amber"]),("left","Left to spend today",COLORS["green"])]):
            card=MetricCard(label,accent=color); self.daily_metrics[key]=card; daily_grid.addWidget(card,0,index)
        daily_layout.addLayout(daily_grid); self.layout.addWidget(daily)
        grid = QGridLayout(); grid.setSpacing(12); self.metrics = {}
        configs = [("cash","Current cash",COLORS["cyan"]),("protected","Protected fund",COLORS["green"]),("spendable","Spendable cash",COLORS["green"]),
                   ("debt","Card balance",COLORS["amber"]),("credit","Available credit",COLORS["purple"]),("rate","GBP / AED",COLORS["cyan"]),
                   ("income","Income this month",COLORS["green"]),("expense","Expenditure",COLORS["amber"]),("projected","Month-end projection",COLORS["cyan"]),
                   ("salary","Next salary",COLORS["purple"]),("commission","Pending commission",COLORS["purple"]),("budget","Budget consumed",COLORS["cyan"])]
        for index, (key, label, accent) in enumerate(configs): card = MetricCard(label, accent=accent); self.metrics[key] = card; grid.addWidget(card, index//4, index%4)
        self.layout.addLayout(grid)
        self.chart_row = QHBoxLayout(); self.chart_row.setSpacing(12); self.layout.addLayout(self.chart_row)
        self.chart_row2 = QHBoxLayout(); self.chart_row2.setSpacing(12); self.layout.addLayout(self.chart_row2)
        self.layout.addWidget(SectionHeader("Recent activity", "The last five movements affecting your position."))
        self.recent = QTableWidget(0, 4); self.recent.setHorizontalHeaderLabels(["WHEN", "MERCHANT", "CATEGORY", "AMOUNT"]); self.recent.horizontalHeader().setStretchLastSection(True); self.recent.verticalHeader().hide(); self.recent.setMaximumHeight(245); self.layout.addWidget(self.recent)
        outer.addWidget(page_scroll(content)); self.refresh()

    def position(self, as_of: date | None = None) -> tuple[FinancialPosition, dict]:
        today=as_of or date.today(); settings = self.db.all_settings(); rate = Decimal(settings.get("gbp_aed_rate", "4.928313")); month = today.strftime("%Y-%m")
        tx = self.db.transactions(month=month, limit=100000); all_tx = self.db.transactions(limit=100000)
        income = sum((to_aed(r["amount"], r["currency"], rate) for r in tx if r["kind"] == "income" and not r["refundable_deposit"]), Decimal(0))
        expense = sum((to_aed(r["amount"], r["currency"], rate) for r in tx if r["kind"] == "expense" and not r["refundable_deposit"] and r["card_effect"]!=-1 and not r["budget_excluded"]), Decimal(0))
        cash_out = sum((to_aed(r["amount"],r["currency"],rate) for r in tx if r["kind"]=="expense" and r["payment_method"]!="Credit card" and not r["refundable_deposit"]),Decimal(0))
        deposits = sum((to_aed(r["amount"], r["currency"], rate) * (1 if r["kind"] == "expense" else -1) for r in all_tx if r["refundable_deposit"]), Decimal(settings.get("security_deposit_aed", "0")))
        opening = Decimal(settings.get("uk_cash_gbp", "0")) * rate
        cash = opening + sum((to_aed(r["amount"], r["currency"], rate) * (1 if r["kind"] == "income" else -1) for r in all_tx if r["payment_method"] != "Credit card" and not r["refundable_deposit"]), Decimal(0))
        cards = self.db.query("SELECT * FROM credit_cards")
        debt = sum((to_aed(r["current_balance"], r["currency"], rate) for r in cards), Decimal(0)); limit = sum((to_aed(r["credit_limit"], r["currency"], rate) for r in cards), Decimal(0))
        pending = sum((Decimal(str(r["commission_aed"])) for r in self.db.query("SELECT commission_aed FROM earnings WHERE received=0")), Decimal(0))
        budget_rows=self.db.query("SELECT b.planned_aed,c.name,c.essential_default FROM budgets b JOIN categories c ON c.id=b.category_id WHERE b.month=?",(month,))
        if budget_rows:
            essential=sum((Decimal(str(r["planned_aed"])) for r in budget_rows if r["essential_default"]),Decimal(0)); discretionary=sum((Decimal(str(r["planned_aed"])) for r in budget_rows if not r["essential_default"]),Decimal(0)); budget_source="saved budget"
        else:
            essential=Decimal(settings.get("rent_aed","4500"))+Decimal(settings.get("transport_aed","2000"))+Decimal(settings.get("food_aed","1250")); discretionary=Decimal(0); budget_source="baseline settings"
        debt_budget=sum((Decimal(str(r["planned_aed"])) for r in budget_rows if r["name"]=="Debt repayment"),Decimal(0))
        minimum_cards_aed=sum((to_aed(min(Decimal(str(r["current_balance"])),Decimal(str(r["minimum_payment"]))),r["currency"],rate) for r in cards if r["current_balance"]>0),Decimal(0))
        if debt_budget<=0: essential+=minimum_cards_aed
        earning=self.db.query("SELECT salary_aed FROM earnings WHERE year=? AND month=?",(today.year,today.month)); guaranteed=Decimal(str(earning[0]["salary_aed"])) if earning else Decimal(settings.get("salary_aed","6000")); income_source="salary engine" if earning else "salary setting"
        month_end=date(today.year,today.month,calendar.monthrange(today.year,today.month)[1]); salary_received=any(r["kind"]=="income" and r["category"]=="Salary" for r in tx)
        reminder_floor=today+timedelta(days=1) if salary_received else today
        reminders=self.db.query("SELECT event_date FROM reminders WHERE completed=0 AND event_type='salary' AND event_date>=? ORDER BY event_date LIMIT 1",(reminder_floor.isoformat(),))
        if reminders: next_salary=date.fromisoformat(reminders[0]["event_date"][:10]); salary_date_source="calendar"
        else:
            start=date.fromisoformat(settings.get("start_date",today.isoformat())[:10]); salary_base=max(today,start); next_salary=date(salary_base.year,salary_base.month,calendar.monthrange(salary_base.year,salary_base.month)[1]); salary_date_source="job start/month-end"
            if salary_received: next_month=next_salary+timedelta(days=1); next_salary=date(next_month.year,next_month.month,calendar.monthrange(next_month.year,next_month.month)[1])
        position = FinancialPosition(money(cash), money(settings.get("emergency_fund_aed", "3000")), money(max(0, deposits)), money(debt), money(limit), money(pending), money(essential), money(discretionary), money(guaranteed))
        actual_runway=calculate_timed_runway(position.spendable_cash_aed,position.monthly_essential_aed+position.monthly_discretionary_aed,position.guaranteed_income_aed,today,next_salary)
        setup_adjustment=sum((to_aed(r["amount"],r["currency"],rate)*(1 if r["kind"]=="expense" else -1) for r in all_tx if r["budget_excluded"] and r["payment_method"]!="Credit card" and not r["refundable_deposit"]),Decimal(0))
        operating_position=FinancialPosition(money(position.cash_aed+setup_adjustment),position.protected_fund_aed,position.deposits_aed,position.card_debt_aed,position.credit_limit_aed,position.pending_commission_aed,position.monthly_essential_aed,position.monthly_discretionary_aed,position.guaranteed_income_aed)
        operating_runway=calculate_timed_runway(operating_position.spendable_cash_aed,operating_position.monthly_essential_aed+operating_position.monthly_discretionary_aed,operating_position.guaranteed_income_aed,today,next_salary)
        days_remaining=(month_end-today).days+1; monthly_cap_gbp=Decimal(settings.get("monthly_spending_cap_gbp","1700")); monthly_cap_aed=money(monthly_cap_gbp*rate); monthly_budget_left=max(Decimal(0),monthly_cap_aed-expense); daily_limit=money(monthly_budget_left/Decimal(days_remaining))
        spent_today=sum((to_aed(r["amount"],r["currency"],rate) for r in tx if r["occurred_at"][:10]==today.isoformat() and r["kind"]=="expense" and not r["refundable_deposit"] and r["card_effect"]!=-1 and not r["budget_excluded"]),Decimal(0)); daily_left=money(daily_limit-spent_today)
        return position, {"settings":settings,"rate":rate,"income":money(income),"expense":money(expense),"cash_out":money(cash_out),"tx":tx,"all":all_tx,"runway":operating_runway,"actual_runway":actual_runway,"operating_position":operating_position,"setup_adjustment":money(setup_adjustment),"monthly_cap_gbp":money(monthly_cap_gbp),"monthly_cap_aed":monthly_cap_aed,"daily_limit":daily_limit,"spent_today":money(spent_today),"daily_left":daily_left,"monthly_budget_left":money(monthly_budget_left),"days_remaining":days_remaining,"next_salary":next_salary,"budget_source":budget_source,"income_source":income_source,"salary_date_source":salary_date_source,"minimum_cards":money(minimum_cards_aed)}

    def refresh(self) -> None:
        position, data = self.position(); today = date.today(); days_salary = max(0, (data["next_salary"]-today).days)
        self.subtitle.setText(today.strftime("%A, %d %B %Y  ·  All values remain on this PC"))
        runway = data["runway"]; shown_runway = "999+" if runway >= 999 else str(runway); runway_label="OPERATING RUNWAY" if data["setup_adjustment"]>0 else "RUNWAY"; self.runway.setText(f"{runway_label}: {shown_runway} DAYS")
        allowance_aed, allowance_gbp = dual_amount(data["operating_position"].safe_daily_allowance_aed, data["rate"])
        self.allowance.setText(f"SAFE DAILY ALLOWANCE  ·  {allowance_aed} / {allowance_gbp}")
        spendable_copy=f"Operating spendable AED {data['operating_position'].spendable_cash_aed:,.0f} · Actual AED {position.spendable_cash_aed:,.0f} · Setup reset AED {data['setup_adjustment']:,.0f}" if data["setup_adjustment"]>0 else f"Spendable AED {position.spendable_cash_aed:,.0f}"
        self.basis.setText(f"LIVE BASIS  ·  {spendable_copy}  ·  Monthly plan AED {position.monthly_essential_aed+position.monthly_discretionary_aed:,.0f} ({data['budget_source']})  ·  Guaranteed income AED {position.guaranteed_income_aed:,.0f} ({data['income_source']})")
        self.basis.setToolTip(f"Next guaranteed salary: {data['next_salary']:%d %b %Y} from {data['salary_date_source']}. Card minimums included: AED {data['minimum_cards']:,.2f}. Pending commission and available credit are excluded.")
        if runway < 14: status, color = "Immediate action: switch to the survival budget and protect the return fund.", COLORS["red"]
        elif runway < 30: status, color = "Runway below 30 days. Remove discretionary spend and review timing risks.", COLORS["red"]
        elif runway < 60: status, color = "Runway below 60 days. Keep commission upside out of current spending plans.", COLORS["amber"]
        elif runway < 90: status, color = "Runway below 90 days. Maintain a conservative daily allowance.", COLORS["amber"]
        else: status, color = "Emergency return fund: protected. Pending commission excluded from spendable cash.", COLORS["green"]
        if data["setup_adjustment"]>0: status+=f"  Actual cash runway: {data['actual_runway']} days; operating view adds back AED {data['setup_adjustment']:,.0f} of marked setup costs."
        self.runway.setStyleSheet(f"color:{color}"); self.status.setText(status); self.ring.color = QColor(color); self.ring.set_value(data["operating_position"].health_score_for_runway(runway))
        rate = data["rate"]; projected = data["income"] - data["expense"]
        daily_limit_aed,daily_limit_gbp=dual_amount(data["daily_limit"],rate,2); spent_aed,spent_gbp=dual_amount(data["spent_today"],rate,2); left_aed,left_gbp=dual_amount(max(Decimal(0),data["daily_left"]),rate,2)
        self.daily_metrics["limit"].set_value(daily_limit_aed,f"{daily_limit_gbp} · GBP {data['monthly_cap_gbp']:,.0f} monthly cap · {data['days_remaining']} days left")
        self.daily_metrics["spent"].set_value(spent_aed,f"{spent_gbp} · From today's normal transactions",COLORS["red"] if data["daily_left"]<0 else COLORS["amber"])
        left_detail=f"Over today's guide by {dual_amount(abs(data['daily_left']),rate)[0]}" if data["daily_left"]<0 else f"{left_gbp} · Available for the rest of today"
        self.daily_metrics["left"].set_value(left_aed,left_detail,COLORS["red"] if data["daily_left"]<0 else COLORS["green"])
        budget_total = position.monthly_essential_aed + position.monthly_discretionary_aed; consumed = int(data["expense"] / budget_total * 100) if budget_total else 0
        def converted(value, note, signed=False):
            primary, secondary = dual_amount(value, rate, signed=signed)
            return primary, f"{secondary} · {note}"
        rate_date=data["settings"].get("gbp_aed_rate_updated_at","—")
        values = {"cash":converted(position.cash_aed,"Real cash only"), "protected":converted(position.protected_fund_aed,"Excluded from allowance"),
                  "spendable":converted(position.spendable_cash_aed,"After protected funds & deposits"), "debt":converted(position.card_debt_aed,"Credit is not an asset"),
                  "credit":converted(position.available_credit_aed,"Debt capacity, not wealth"), "rate":(f"{rate:.6f}",f"1 GBP · official snapshot {rate_date}"),
                  "income":converted(data["income"],"Received cash"), "expense":converted(data["expense"],"Actual this month"),
                  "projected":converted(projected,"Current month cash flow",True), "salary":(f"{days_salary} days",data["next_salary"].strftime("%d %b %Y")+f" · {data['salary_date_source']}"),
                  "commission":converted(position.pending_commission_aed,"Earned, not spendable"), "budget":(f"{consumed}%", "Warnings at 70 / 85 / 100%")}
        for key, (value, detail) in values.items(): self.metrics[key].set_value(value, detail, COLORS["red"] if key == "projected" and projected < 0 else None)
        clear_layout(self.chart_row); clear_layout(self.chart_row2)
        history = [float(position.cash_aed - data["expense"] * Decimal(i)/Decimal(7)) for i in reversed(range(8))]
        self.chart_row.addWidget(line_chart("Cash balance over time", history), 2)
        planned = [float(position.monthly_essential_aed), float(max(0, position.monthly_discretionary_aed))]; actual = [float(sum(to_aed(r["amount"], r["currency"], rate) for r in data["tx"] if r["essential"] and r["kind"]=="expense" and r["card_effect"]!=-1 and not r["budget_excluded"])), float(sum(to_aed(r["amount"], r["currency"], rate) for r in data["tx"] if not r["essential"] and r["kind"]=="expense" and r["card_effect"]!=-1 and not r["budget_excluded"]))]
        self.chart_row.addWidget(bar_chart("Planned vs actual", planned, actual, ["Essential", "Discretionary"]), 1)
        cats: dict[str, float] = {}
        color_map: dict[str, str] = {}
        for r in data["tx"]:
            if r["kind"] == "expense" and r["card_effect"]!=-1 and not r["budget_excluded"]: cats[r["category"] or "Other"] = cats.get(r["category"] or "Other", 0)+float(to_aed(r["amount"], r["currency"], rate)); color_map[r["category"] or "Other"] = r["category_color"] or COLORS["muted"]
        self.chart_row2.addWidget(pie_chart("Spending by category", [(k,v,color_map[k]) for k,v in sorted(cats.items(), key=lambda x:-x[1])[:6]] or [("No spend",1,COLORS["border2"])]), 1)
        scenario_values = [float(data["operating_position"].spendable_cash_aed - max(0, data["operating_position"].monthly_burn_aed) * Decimal(i)/Decimal(6)) for i in range(7)]
        self.chart_row2.addWidget(line_chart("Projected runway · conservative", scenario_values, color=COLORS["purple"]), 2)
        recent = data["all"][:5]; self.recent.setRowCount(len(recent))
        for i, row in enumerate(recent):
            self.recent.setRowHeight(i,48); signed_aed=to_aed(row["amount"],row["currency"],rate)*(1 if row["kind"]=="income" else -1); primary,secondary=dual_amount(signed_aed,rate,2,True); color = COLORS["green"] if row["kind"] == "income" else COLORS["text"]
            for col, item in enumerate([row["occurred_at"][:10], row["merchant"] or "—", category_label(row["category"]), f"{primary}\n{secondary}"]): self.recent.setItem(i,col,table_item(str(item), Qt.AlignmentFlag.AlignRight if col==3 else None, color if col==3 else None))
        self.recent.resizeColumnsToContents(); self.recent.horizontalHeader().setStretchLastSection(True)


class CustomerContactPage(Page):
    def __init__(self,db:Database):
        super().__init__(db); layout=QVBoxLayout(self); layout.setContentsMargins(24,22,24,24); layout.setSpacing(14)
        top=QHBoxLayout(); top.addWidget(SectionHeader("Customer contact","Friendly three-day follow-ups for owners who may need time before selling.")); top.addStretch()
        import_button=QPushButton("Import downloaded chats"); import_button.clicked.connect(self.import_chats); top.addWidget(import_button)
        add=QPushButton("＋ Add customer"); add.setProperty("primary",True); add.clicked.connect(self.add_customer); top.addWidget(add); layout.addLayout(top)
        metrics=QGridLayout(); metrics.setSpacing(12); self.metrics={}
        for i,(key,label,color) in enumerate([("today","Contact today",COLORS["red"]),("tomorrow","Tomorrow",COLORS["amber"]),("active","Active customers",COLORS["cyan"]),("rapport","Strong rapport",COLORS["red"])]):
            card=MetricCard(label,accent=color); self.metrics[key]=card; metrics.addWidget(card,0,i)
        layout.addLayout(metrics)
        tools=QHBoxLayout()
        for label,callback in [("Contacted · reset 3 days",self.mark_contacted),("Toggle green / red",self.toggle_rapport),("Edit",self.edit_customer),("Sold",self.mark_sold),("Sold to another buyer",self.sold_elsewhere),("Add to inspection",self.move_to_inspection)]:
            button=QPushButton(label); button.clicked.connect(callback); tools.addWidget(button)
        tools.addStretch(); self.search=QLineEdit(); self.search.setPlaceholderText("Find customer, car or phone digits…"); self.search.setMaximumWidth(320); self.search.textChanged.connect(self.refresh); tools.addWidget(self.search); layout.addLayout(tools)
        self.tabs=QTabWidget(); self.tables={}
        for key,label in [("today","Contact today"),("tomorrow","Tomorrow"),("all","All customers")]:
            table=QTableWidget(0,7); table.setHorizontalHeaderLabels(["CUSTOMER","VEHICLE","MILEAGE","PHONE","VALUATION","OFFERS","RAPPORT / NEXT CONTACT"]); table.setWordWrap(True); table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); table.verticalHeader().hide(); table.horizontalHeader().setStretchLastSection(True); table.doubleClicked.connect(self.edit_customer); table.itemSelectionChanged.connect(self.show_selected_notes); self.tables[key]=table; self.tabs.addTab(table,label)
        self.tabs.currentChanged.connect(self.show_selected_notes); layout.addWidget(self.tabs,1)
        self.notes_card=Card(); notes_layout=QVBoxLayout(self.notes_card); notes_layout.setContentsMargins(16,14,16,14); notes_top=QHBoxLayout(); self.notes_title=QLabel("CUSTOMER NOTES"); self.notes_title.setStyleSheet("font-weight:800"); notes_top.addWidget(self.notes_title); notes_top.addStretch(); delete_note=QPushButton("Delete selected note"); delete_note.clicked.connect(self.delete_note); notes_top.addWidget(delete_note); close_notes=QPushButton("Close notes"); close_notes.clicked.connect(self.close_notes); notes_top.addWidget(close_notes); notes_layout.addLayout(notes_top)
        self.notes_table=QTableWidget(0,2); self.notes_table.setHorizontalHeaderLabels(["ADDED","NOTE"]); self.notes_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.notes_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.notes_table.verticalHeader().hide(); self.notes_table.horizontalHeader().setStretchLastSection(True); self.notes_table.setMaximumHeight(150); notes_layout.addWidget(self.notes_table)
        note_row=QHBoxLayout(); self.note_input=QLineEdit(); self.note_input.setPlaceholderText("Add a note about the conversation, timing or seller position…"); self.note_input.returnPressed.connect(self.add_note); note_row.addWidget(self.note_input,1); add_note=QPushButton("Add note"); add_note.setProperty("primary",True); add_note.clicked.connect(self.add_note); note_row.addWidget(add_note); notes_layout.addLayout(note_row); self.notes_card.hide(); layout.addWidget(self.notes_card); self.refresh()

    def selected_customer(self):
        key=("today","tomorrow","all")[self.tabs.currentIndex()]; table=self.tables[key]; row=table.currentRow()
        if row<0 or not table.item(row,0): return None
        customer_id=table.item(row,0).data(Qt.ItemDataRole.UserRole); matches=self.db.query("SELECT * FROM customer_contacts WHERE id=?",(customer_id,))
        return matches[0] if matches else None

    def refresh(self)->None:
        today=self.db.customer_contacts(due="today"); tomorrow=self.db.customer_contacts(due="tomorrow"); active=self.db.customer_contacts(); all_rows=self.db.customer_contacts(search=self.search.text().strip(),include_sold=True)
        self.metrics["today"].set_value(str(len(today)),"Includes overdue follow-ups"); self.metrics["tomorrow"].set_value(str(len(tomorrow)),"Due next"); self.metrics["active"].set_value(str(len(active)),"Not marked sold"); self.metrics["rapport"].set_value(str(sum(1 for row in active if row["rapport"]=="red")),"Red · strong rapport")
        for key,rows in (("today",today),("tomorrow",tomorrow),("all",all_rows)): self.populate_table(self.tables[key],rows)
        self.tabs.setTabText(0,f"Contact today · {len(today)}"); self.tabs.setTabText(1,f"Tomorrow · {len(tomorrow)}"); self.tabs.setTabText(2,f"All customers · {len(all_rows)}")

    def populate_table(self,table:QTableWidget,rows)->None:
        rate=Decimal(self.db.get_setting("gbp_aed_rate","4.928313")); today=date.today().isoformat(); table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            table.setRowHeight(i,72); first=table_item(row["customer_name"]); first.setData(Qt.ItemDataRole.UserRole,row["id"]); first.setToolTip(row["notes"] or "Select to open customer notes"); table.setItem(i,0,first)
            valuation=Decimal(str(row["vehicle_price_aed"])); cash=Decimal(str(row["cash_offer_aed"])); consignment=Decimal(str(row["consignment_offer_aed"]))
            status=f"SOLD · {row['sold_date']}" if row["status"]=="sold" else f"Next · {row['next_contact_date']}\n{contact_countdown(row['next_contact_date'])}"; rapport="Red · strong" if row["rapport"]=="red" else "Green"; final=f"{rapport}\n{status}"
            values=[f"{customer_vehicle_year(row['vehicle_age_years'])} {row['vehicle_name']}",f"{row['mileage']:,} km",f"••••• {row['phone_last5']}",f"{valuation:,.0f} AED\n{gbp_equivalent(valuation,rate):,.0f} GBP",f"Cash {cash:,.0f}\nConsign {consignment:,.0f}",final]
            for j,value in enumerate(values,1):
                color=COLORS["red"] if j==6 and row["rapport"]=="red" else COLORS["green"] if j==6 and row["rapport"]=="green" else None
                item=table_item(str(value),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight if j in {2,4,5,6} else Qt.AlignmentFlag.AlignVCenter,color)
                if j==6 and row["status"]=="active" and row["next_contact_date"]<=today: item.setBackground(QColor("#5a1f2b"))
                table.setItem(i,j,item)
        table.setColumnWidth(0,135); table.setColumnWidth(1,160); table.setColumnWidth(2,130); table.setColumnWidth(3,105); table.setColumnWidth(4,135); table.setColumnWidth(5,150)

    def show_selected_notes(self)->None:
        customer=self.selected_customer()
        if not customer: self.notes_card.hide(); return
        self.notes_card.show(); self.notes_title.setText(f"NOTES · {customer['customer_name']} · {customer_vehicle_year(customer['vehicle_age_years'])} {customer['vehicle_name']}")
        notes=self.db.customer_contact_notes(customer["id"]); self.notes_table.setRowCount(len(notes))
        for i,note in enumerate(notes):
            self.notes_table.setRowHeight(i,42); added=table_item(note["created_at"][:16].replace("T"," ")); added.setData(Qt.ItemDataRole.UserRole,note["id"]); self.notes_table.setItem(i,0,added); self.notes_table.setItem(i,1,table_item(note["note_text"]))
        self.notes_table.setColumnWidth(0,145); self.notes_table.horizontalHeader().setStretchLastSection(True)

    def add_note(self)->None:
        customer=self.selected_customer()
        if not customer: QMessageBox.information(self,"Select a customer","Select a customer before adding a note."); return
        note=self.note_input.text().strip()
        if not note: return
        self.db.add_customer_contact_note(customer["id"],note); self.note_input.clear(); self.show_selected_notes(); self.changed.emit()

    def delete_note(self)->None:
        customer=self.selected_customer(); row=self.notes_table.currentRow()
        if not customer or row<0 or not self.notes_table.item(row,0): QMessageBox.information(self,"Select a note","Select the note you want to delete."); return
        note_id=self.notes_table.item(row,0).data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self,"Delete note","Delete this customer note?")==QMessageBox.StandardButton.Yes:
            self.db.delete_customer_contact_note(customer["id"],note_id); self.show_selected_notes(); self.changed.emit()

    def close_notes(self)->None:
        for table in self.tables.values(): table.clearSelection()
        self.note_input.clear(); self.notes_card.hide()

    def add_customer(self)->None:
        dialog=CustomerContactDialog(self.db,parent=self)
        if dialog.exec(): self.db.add_customer_contact(dialog.values()); self.refresh(); self.changed.emit()

    def import_chats(self)->None:
        downloads=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation))
        result=import_downloaded_contacts(self.db,downloads); trashed=0
        for path in result.processed_files:
            if QFile.moveToTrash(str(path)): trashed+=1
        self.refresh(); self.changed.emit()
        summary=f"Added {result.added} · Updated {result.updated} · Moved {trashed} export(s) to Trash"
        if result.failed:
            summary += "\n\nNeeds attention:\n"+"\n".join(result.failed[:8])
        elif not result.processed_files:
            summary += "\n\nNo usable HTML chat exports were found in Downloads."
        QMessageBox.information(self,"Downloaded chats",summary)

    def edit_customer(self)->None:
        customer=self.selected_customer()
        if not customer: QMessageBox.information(self,"Select a customer","Select a customer first."); return
        dialog=CustomerContactDialog(self.db,customer,self)
        if dialog.exec(): self.db.update_customer_contact(customer["id"],dialog.values()); self.refresh(); self.changed.emit()

    def mark_contacted(self)->None:
        customer=self.selected_customer()
        if not customer: QMessageBox.information(self,"Select a customer","Select the customer you contacted."); return
        if customer["status"]!="active": QMessageBox.information(self,"Already sold","Sold customers are kept only for reference."); return
        self.db.mark_customer_contacted(customer["id"]); self.refresh(); self.changed.emit()

    def move_to_inspection(self)->None:
        customer=self.selected_customer()
        if not customer: QMessageBox.information(self,"Select a customer","Select the caller you want to move into inspection."); return
        if customer["status"]!="active": QMessageBox.information(self,"Already sold","Sold customers cannot be moved into inspection."); return
        dialog=InspectionDateDialog(customer,self)
        if dialog.exec():
            self.db.move_customer_to_inspection(customer["id"],dialog.value()); self.close_notes(); self.refresh(); self.changed.emit()

    def toggle_rapport(self)->None:
        customer=self.selected_customer()
        if not customer: QMessageBox.information(self,"Select a customer","Select a customer first."); return
        self.db.toggle_customer_rapport(customer["id"]); self.refresh(); self.changed.emit()

    def mark_sold(self)->None:
        customer=self.selected_customer()
        if not customer: QMessageBox.information(self,"Select a customer","Select the customer whose vehicle has sold."); return
        if customer["status"]!="active": QMessageBox.information(self,"Already sold","This customer is already outside the contact queue."); return
        if QMessageBox.question(self,"Mark vehicle sold",f"Remove {customer['customer_name']} from the daily contact queue? Their record will remain searchable.")==QMessageBox.StandardButton.Yes:
            self.db.mark_customer_sold(customer["id"]); self.refresh(); self.changed.emit()

    def sold_elsewhere(self)->None:
        customer=self.selected_customer()
        if not customer: QMessageBox.information(self,"Select a customer","Select the customer whose vehicle sold to another buyer."); return
        if customer["status"]!="active": QMessageBox.information(self,"Already sold","This customer is already stored as sold."); return
        message=f"{customer['customer_name']} sold their {customer_vehicle_year(customer['vehicle_age_years'])} {customer['vehicle_name']} to another buyer.\n\nPermanently delete this customer, their offers, follow-up history and all notes from DXB RUNWAY?"
        if QMessageBox.question(self,"Sold to another buyer",message)==QMessageBox.StandardButton.Yes:
            self.db.delete_customer_contact(customer["id"]); self.close_notes(); self.refresh(); self.changed.emit()


class InspectionPage(Page):
    def __init__(self,db:Database):
        super().__init__(db); layout=QVBoxLayout(self); layout.setContentsMargins(24,22,24,24); layout.setSpacing(14)
        top=QHBoxLayout(); top.addWidget(SectionHeader("Inspection","Customers whose vehicles have progressed from caller follow-up to inspection.")); top.addStretch()
        self.count=MetricCard("Awaiting inspection",accent=COLORS["purple"]); self.count.setMaximumWidth(230); top.addWidget(self.count); layout.addLayout(top)
        tools=QHBoxLayout()
        for label,callback in [("Return to callers",self.return_to_callers),("Edit customer",self.edit_customer),("Bought · move to stock",self.mark_sold)]:
            button=QPushButton(label); button.clicked.connect(callback); tools.addWidget(button)
        tools.addStretch(); self.search=QLineEdit(); self.search.setPlaceholderText("Find customer, car or phone digits…"); self.search.setMaximumWidth(320); self.search.textChanged.connect(self.refresh); tools.addWidget(self.search); layout.addLayout(tools)
        self.table=QTableWidget(0,9); self.table.setHorizontalHeaderLabels(["INSPECTION DATE","CUSTOMER","VEHICLE","MILEAGE","PHONE","VALUATION","OFFERS","RAPPORT","LATEST NOTES"]); self.table.setWordWrap(True); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); self.table.doubleClicked.connect(self.edit_customer); layout.addWidget(self.table,1); self.refresh()

    def selected_customer(self):
        row=self.table.currentRow()
        if row<0 or not self.table.item(row,0): return None
        matches=self.db.query("SELECT * FROM customer_contacts WHERE id=?",(self.table.item(row,0).data(Qt.ItemDataRole.UserRole),))
        return matches[0] if matches else None

    def refresh(self)->None:
        rows=self.db.customer_contacts(search=self.search.text().strip(),stage="inspection"); rate=Decimal(self.db.get_setting("gbp_aed_rate","4.928313")); self.count.set_value(str(len(rows)),"Moved from Customer contact"); self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            self.table.setRowHeight(i,72); first=table_item(row["inspection_date"] or "Date not set"); first.setData(Qt.ItemDataRole.UserRole,row["id"]); self.table.setItem(i,0,first); self.table.setItem(i,1,table_item(row["customer_name"]))
            valuation=Decimal(str(row["vehicle_price_aed"])); cash=Decimal(str(row["cash_offer_aed"])); consignment=Decimal(str(row["consignment_offer_aed"])); notes=self.db.customer_contact_notes(row["id"]); latest=notes[0]["note_text"] if notes else row["notes"] or "—"
            values=[f"{customer_vehicle_year(row['vehicle_age_years'])} {row['vehicle_name']}",f"{row['mileage']:,} km",f"••••• {row['phone_last5']}",f"{valuation:,.0f} AED\n{gbp_equivalent(valuation,rate):,.0f} GBP",f"Cash {cash:,.0f}\nConsign {consignment:,.0f}","Red · strong" if row["rapport"]=="red" else "Green",latest]
            for j,value in enumerate(values,2): self.table.setItem(i,j,table_item(str(value),Qt.AlignmentFlag.AlignVCenter))
        for column,width in enumerate([125,135,175,110,100,135,150,105]): self.table.setColumnWidth(column,width)

    def return_to_callers(self)->None:
        customer=self.selected_customer()
        if not customer: QMessageBox.information(self,"Select a customer","Select the inspection you want to return to callers."); return
        if QMessageBox.question(self,"Return to callers",f"Return {customer['customer_name']} to today's contact list?")==QMessageBox.StandardButton.Yes:
            self.db.return_customer_to_callers(customer["id"]); self.refresh(); self.changed.emit()

    def edit_customer(self)->None:
        customer=self.selected_customer()
        if not customer: QMessageBox.information(self,"Select a customer","Select an inspection first."); return
        dialog=CustomerContactDialog(self.db,customer,self)
        if dialog.exec(): self.db.update_customer_contact(customer["id"],dialog.values()); self.refresh(); self.changed.emit()

    def mark_sold(self)->None:
        customer=self.selected_customer()
        if not customer: QMessageBox.information(self,"Select a customer","Select the inspected vehicle we bought."); return
        dialog=VehicleDialog(self.db,self,source_customer=customer)
        if dialog.exec(): self.db.acquire_inspected_vehicle(customer["id"],dialog.values()); self.refresh(); self.changed.emit(); QMessageBox.information(self,"Added to Stock Level","Purchase confirmed. The vehicle is now in Stock Level with its verified cost and expected selling price.")


class WhatsAppTemplatesPage(Page):
    def __init__(self,db:Database):
        super().__init__(db); layout=QVBoxLayout(self); layout.setContentsMargins(24,22,24,24); layout.setSpacing(14)
        top=QHBoxLayout(); top.addWidget(SectionHeader("WhatsApp templates","Save polished messages once, then copy them whenever you need to contact a customer.")); top.addStretch(); add=QPushButton("＋ Add template"); add.setProperty("primary",True); add.clicked.connect(self.add_template); top.addWidget(add); layout.addLayout(top)
        tabs=QTabWidget(); layout.addWidget(tabs,1)

        route_page=QWidget(); route_layout=QVBoxLayout(route_page); route_layout.setContentsMargins(12,14,12,12); route_layout.setSpacing(14)
        calculator=Card(); calculator_layout=QVBoxLayout(calculator); calculator_layout.setContentsMargins(18,16,18,16); calculator_layout.setSpacing(12)
        calculator_layout.addWidget(QLabel("OFFER ROUTE CALCULATOR"))
        inputs=QHBoxLayout(); inputs.setSpacing(12)
        for label,widget in [("LISTING PRICE · AED",MoneyBox(decimals=0)),("YOUR CASH OFFER · AED",MoneyBox(decimals=0))]:
            field=QVBoxLayout(); caption=QLabel(label); caption.setObjectName("eyebrow"); field.addWidget(caption); widget.setSingleStep(1000); field.addWidget(widget); inputs.addLayout(field,1)
            if "LISTING" in label: self.route_listing=widget
            else: self.route_offer=widget
        vehicle_field=QVBoxLayout(); vehicle_caption=QLabel("VEHICLE · OPTIONAL"); vehicle_caption.setObjectName("eyebrow"); vehicle_field.addWidget(vehicle_caption); self.route_vehicle=QLineEdit(); self.route_vehicle.setPlaceholderText("Example: 2021 Volkswagen Tiguan"); vehicle_field.addWidget(self.route_vehicle); inputs.addLayout(vehicle_field,1); calculator_layout.addLayout(inputs)
        result=QHBoxLayout(); self.route_percent=QLabel("Enter both prices"); self.route_percent.setStyleSheet("font-size:22px;font-weight:900"); result.addWidget(self.route_percent); result.addSpacing(14); self.route_title=QLabel("Your recommended approach will appear here."); self.route_title.setStyleSheet("font-size:17px;font-weight:800"); result.addWidget(self.route_title); result.addStretch(); calculator_layout.addLayout(result)
        self.route_detail=QLabel("Offer ≥ 90%: lead with offer  ·  80–89.9%: ask flexibility first  ·  Below 80%: qualify motivation first"); self.route_detail.setObjectName("muted"); self.route_detail.setWordWrap(True); calculator_layout.addWidget(self.route_detail); route_layout.addWidget(calculator)
        message_card=Card(); message_layout=QVBoxLayout(message_card); message_layout.setContentsMargins(18,16,18,16); message_layout.setSpacing(10); message_layout.addWidget(QLabel("RECOMMENDED MESSAGE SEQUENCE")); self.route_step=QComboBox(); self.route_step.currentIndexChanged.connect(self.show_route_message); message_layout.addWidget(self.route_step); self.route_preview=QTextEdit(); self.route_preview.setReadOnly(True); self.route_preview.setMinimumHeight(155); self.route_preview.setPlaceholderText("Enter the listing price and your offer above to generate the best route."); message_layout.addWidget(self.route_preview,1); self.route_copy=QPushButton("Copy this message"); self.route_copy.setProperty("primary",True); self.route_copy.setEnabled(False); self.route_copy.clicked.connect(self.copy_route_message); message_layout.addWidget(self.route_copy); route_layout.addWidget(message_card,1)
        note=QLabel("Use this as a starting framework, not a rigid rule. High-end and consignment prospects may still benefit from more credibility and service context before discussing numbers."); note.setObjectName("muted"); note.setWordWrap(True); route_layout.addWidget(note); tabs.addTab(route_page,"Offer route")

        saved_page=QWidget(); saved_layout=QVBoxLayout(saved_page); saved_layout.setContentsMargins(12,14,12,12); saved_layout.setSpacing(12)
        tools=QHBoxLayout()
        for label,callback in [("Edit selected",self.edit_template),("Delete selected",self.delete_template)]:
            button=QPushButton(label); button.clicked.connect(callback); tools.addWidget(button)
        tools.addStretch(); saved_layout.addLayout(tools)
        body=QHBoxLayout(); body.setSpacing(14); list_card=Card(); list_layout=QVBoxLayout(list_card); list_layout.setContentsMargins(16,15,16,15); list_layout.addWidget(QLabel("SAVED TEMPLATES")); self.table=QTableWidget(0,1); self.table.setHorizontalHeaderLabels(["TEMPLATE"]); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); self.table.itemSelectionChanged.connect(self.show_selected); list_layout.addWidget(self.table); body.addWidget(list_card,1)
        preview_card=Card(); preview_layout=QVBoxLayout(preview_card); preview_layout.setContentsMargins(18,16,18,16); self.preview_title=QLabel("SELECT A TEMPLATE"); self.preview_title.setStyleSheet("font-size:18px;font-weight:800"); preview_layout.addWidget(self.preview_title)
        search_row=QHBoxLayout(); search_row.addWidget(QLabel("SEARCH CUSTOMER")); self.customer_search=QLineEdit(); self.customer_search.setPlaceholderText("Type a name, vehicle or last 5 phone digits…"); self.customer_search.setClearButtonEnabled(True); self.customer_search.textChanged.connect(self.filter_customers); search_row.addWidget(self.customer_search,1); preview_layout.addLayout(search_row)
        result_row=QHBoxLayout(); result_row.addWidget(QLabel("MATCHING CUSTOMERS")); self.customer=QComboBox(); self.customer.setMaxVisibleItems(12); self.customer.setMinimumWidth(420); self.customer.currentIndexChanged.connect(self.show_selected); result_row.addWidget(self.customer,1); preview_layout.addLayout(result_row)
        self.customer_hint=QLabel("Search across active callers and inspections, then choose the correct customer by vehicle and phone suffix."); self.customer_hint.setObjectName("muted"); preview_layout.addWidget(self.customer_hint); self.preview=QTextEdit(); self.preview.setReadOnly(True); self.preview.setPlaceholderText("Your selected WhatsApp message will appear here."); preview_layout.addWidget(self.preview,1); self.copy_button=QPushButton("Copy personalised message"); self.copy_button.setProperty("primary",True); self.copy_button.clicked.connect(self.copy_message); self.copy_button.setEnabled(False); preview_layout.addWidget(self.copy_button); body.addWidget(preview_card,2); saved_layout.addLayout(body,1); tabs.addTab(saved_page,"Saved templates")
        self.route_listing.valueChanged.connect(self.update_offer_route); self.route_offer.valueChanged.connect(self.update_offer_route); self.route_vehicle.textChanged.connect(self.update_offer_route); self.route_steps=[]; self.customer_rows=[]; self.refresh(); self.update_offer_route()

    def update_offer_route(self)->None:
        asking=self.route_listing.value(); cash_offer=self.route_offer.value(); self.route_step.blockSignals(True); self.route_step.clear(); self.route_steps=[]
        if asking<=0 or cash_offer<=0:
            self.route_percent.setText("Enter both prices"); self.route_percent.setStyleSheet("font-size:22px;font-weight:900;color:#8894a7"); self.route_title.setText("Your recommended approach will appear here."); self.route_detail.setText("Offer ≥ 90%: lead with offer  ·  80–89.9%: ask flexibility first  ·  Below 80%: qualify motivation first"); self.route_preview.clear(); self.route_copy.setEnabled(False); self.route_step.setEnabled(False); self.route_step.blockSignals(False); return
        route=offer_route(asking,cash_offer); self.route_percent.setText(f"{route['percentage']:.1f}% of asking"); self.route_percent.setStyleSheet(f"font-size:22px;font-weight:900;color:{route['color']}"); self.route_title.setText(str(route["title"])); self.route_detail.setText(str(route["detail"])); self.route_steps=offer_message_steps(str(route["key"]),self.route_vehicle.text(),asking,cash_offer)
        for title,_ in self.route_steps: self.route_step.addItem(title)
        self.route_step.setEnabled(True); self.route_step.blockSignals(False); self.route_step.setCurrentIndex(0); self.show_route_message()

    def show_route_message(self)->None:
        index=self.route_step.currentIndex()
        if 0<=index<len(self.route_steps): self.route_preview.setPlainText(self.route_steps[index][1]); self.route_copy.setEnabled(True)
        else: self.route_preview.clear(); self.route_copy.setEnabled(False)

    def copy_route_message(self)->None:
        message=self.route_preview.toPlainText().strip()
        if not message:return
        QApplication.clipboard().setText(message); QMessageBox.information(self,"Copied","Recommended message copied.\n\nIt is ready to paste into WhatsApp.")

    def selected_template(self):
        row=self.table.currentRow()
        if row<0 or not self.table.item(row,0): return None
        matches=self.db.query("SELECT * FROM message_templates WHERE id=?",(self.table.item(row,0).data(Qt.ItemDataRole.UserRole),))
        return matches[0] if matches else None

    def refresh(self)->None:
        self.customer_rows=self.db.customer_contacts(stage=None); self.customer_search.blockSignals(True); self.customer_search.clear(); self.customer_search.blockSignals(False); self.filter_customers(""); rows=self.db.message_templates(); self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            item=table_item(row["title"]); item.setData(Qt.ItemDataRole.UserRole,row["id"]); self.table.setItem(i,0,item); self.table.setRowHeight(i,44)
        if rows: self.table.selectRow(0)
        else: self.preview_title.setText("SELECT A TEMPLATE"); self.preview.clear(); self.copy_button.setEnabled(False)

    def show_selected(self)->None:
        template=self.selected_template()
        if not template: self.preview_title.setText("SELECT A TEMPLATE"); self.preview.clear(); self.copy_button.setEnabled(False); return
        message=template["message_text"]; needs_customer="{{customer_name}}" in message or "{{vehicle}}" in message; customer_id=self.customer.currentData() if self.customer.currentIndex()>0 else None; customer=None
        if customer_id is not None:
            rows=self.db.query("SELECT * FROM customer_contacts WHERE id=?",(customer_id,)); customer=rows[0] if rows else None
        if customer:
            message=message.replace("{{customer_name}}",customer["customer_name"]).replace("{{vehicle}}",f"{customer_vehicle_year(customer['vehicle_age_years'])} {customer['vehicle_name']}")
        self.preview_title.setText(template["title"]); self.preview.setPlainText(message); self.copy_button.setEnabled(not needs_customer or customer is not None)
        self.copy_button.setToolTip("Choose a customer to fill the smart fields before copying." if needs_customer and customer is None else "Copy this finished message to the clipboard.")

    def filter_customers(self,text:str)->None:
        query=text.strip().casefold(); matches=[]
        if query:
            for customer in self.customer_rows:
                searchable=f"{customer['customer_name']} {customer['vehicle_name']} {customer['phone_last5']}".casefold()
                if query in searchable: matches.append(customer)
        self.customer.blockSignals(True); self.customer.clear()
        if not query: self.customer.addItem("Type in the search box above…",None)
        elif not matches: self.customer.addItem("No matching customers",None)
        else:
            self.customer.addItem(f"Choose from {len(matches)} matching customer{'s' if len(matches)!=1 else ''}…",None)
            for customer in matches:
                stage="Inspection" if customer["pipeline_stage"]=="inspection" else "Caller"
                self.customer.addItem(f"{customer['customer_name']} · {customer_vehicle_year(customer['vehicle_age_years'])} {customer['vehicle_name']} · ••••• {customer['phone_last5']} · {stage}",customer["id"])
        self.customer.setCurrentIndex(0); self.customer.setEnabled(bool(matches)); self.customer.blockSignals(False); self.show_selected()
        if len(matches)>1: self.customer.showPopup()

    def add_template(self)->None:
        dialog=MessageTemplateDialog(parent=self)
        if dialog.exec(): values=dialog.values(); self.db.save_message_template(values["title"],values["message_text"]); self.refresh(); self.changed.emit()

    def edit_template(self)->None:
        template=self.selected_template()
        if not template: QMessageBox.information(self,"Select a template","Select the message template you want to edit."); return
        dialog=MessageTemplateDialog(template,self)
        if dialog.exec(): values=dialog.values(); self.db.save_message_template(values["title"],values["message_text"],template["id"]); self.refresh(); self.changed.emit()

    def delete_template(self)->None:
        template=self.selected_template()
        if not template: QMessageBox.information(self,"Select a template","Select the message template you want to delete."); return
        if QMessageBox.question(self,"Delete template",f"Delete “{template['title']}”?")==QMessageBox.StandardButton.Yes: self.db.delete_message_template(template["id"]); self.refresh(); self.changed.emit()

    def copy_message(self)->None:
        message=self.preview.toPlainText().strip()
        if not message: return
        QApplication.clipboard().setText(message); QMessageBox.information(self,"Copied","Message copied to your clipboard.\n\nIt is ready to paste into WhatsApp.")


class TodayTodoPage(Page):
    def __init__(self, db: Database):
        super().__init__(db)
        layout=QVBoxLayout(self); layout.setContentsMargins(24,22,24,24); layout.setSpacing(14)
        self.header=SectionHeader("Today's to-do list","A fresh list appears automatically every day; previous days stay safely stored."); layout.addWidget(self.header)
        entry_card=Card(); entry_layout=QHBoxLayout(entry_card); entry_layout.setContentsMargins(16,14,16,14)
        self.entry=QLineEdit(); self.entry.setPlaceholderText("Add something to do today…"); self.entry.returnPressed.connect(self.add_task); entry_layout.addWidget(self.entry,1)
        add=QPushButton("＋ Add task"); add.setProperty("primary",True); add.clicked.connect(self.add_task); entry_layout.addWidget(add); layout.addWidget(entry_card)
        metrics=QGridLayout(); metrics.setSpacing(12); self.metrics={}
        for i,(key,label,color) in enumerate([("total","Today's tasks",COLORS["cyan"]),("remaining","Still to do",COLORS["amber"]),("completed","Completed",COLORS["green"])]):
            card=MetricCard(label,accent=color); self.metrics[key]=card; metrics.addWidget(card,0,i)
        layout.addLayout(metrics)
        card=Card(); card_layout=QVBoxLayout(card); card_layout.setContentsMargins(16,15,16,15)
        actions=QHBoxLayout(); self.day_label=QLabel(); self.day_label.setStyleSheet("font-size:16px;font-weight:800"); actions.addWidget(self.day_label); actions.addStretch(); delete=QPushButton("Delete selected"); delete.clicked.connect(self.delete_selected); actions.addWidget(delete); card_layout.addLayout(actions)
        self.table=QTableWidget(0,2); self.table.setHorizontalHeaderLabels(["DONE","TASK"]); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); self.table.itemChanged.connect(self.task_changed); card_layout.addWidget(self.table); layout.addWidget(card,1)
        self.refresh()

    def refresh(self)->None:
        today=date.today(); rows=self.db.daily_tasks(today.isoformat()); completed=sum(int(row["completed"]) for row in rows); remaining=len(rows)-completed
        self.day_label.setText(today.strftime("%A, %d %B %Y")); self.metrics["total"].set_value(str(len(rows)),"Only today's list"); self.metrics["remaining"].set_value(str(remaining),"Waiting for you"); self.metrics["completed"].set_value(str(completed),"Finished today")
        self.table.blockSignals(True); self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            self.table.setRowHeight(i,48); done=QTableWidgetItem(); done.setData(Qt.ItemDataRole.UserRole,row["id"]); done.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable|Qt.ItemFlag.ItemIsUserCheckable); done.setCheckState(Qt.CheckState.Checked if row["completed"] else Qt.CheckState.Unchecked); self.table.setItem(i,0,done)
            task=table_item(row["title"],Qt.AlignmentFlag.AlignVCenter,COLORS["muted"] if row["completed"] else None); font=task.font(); font.setStrikeOut(bool(row["completed"])); task.setFont(font); self.table.setItem(i,1,task)
        self.table.setColumnWidth(0,72); self.table.blockSignals(False)

    def add_task(self)->None:
        title=self.entry.text().strip()
        if not title: return
        self.db.add_daily_task(title); self.entry.clear(); self.refresh(); self.changed.emit(); self.entry.setFocus()

    def task_changed(self,item:QTableWidgetItem)->None:
        if item.column()!=0: return
        task_id=item.data(Qt.ItemDataRole.UserRole)
        if task_id is None: return
        self.db.set_daily_task_completed(int(task_id),item.checkState()==Qt.CheckState.Checked); self.refresh(); self.changed.emit()

    def delete_selected(self)->None:
        row=self.table.currentRow()
        if row<0 or not self.table.item(row,0): QMessageBox.information(self,"Select a task","Select the task you want to delete first."); return
        self.db.delete_daily_task(int(self.table.item(row,0).data(Qt.ItemDataRole.UserRole))); self.refresh(); self.changed.emit()


class KPITrackerPage(Page):
    CALL_TARGET=240
    def __init__(self, db: Database):
        super().__init__(db)
        layout=QVBoxLayout(self); layout.setContentsMargins(24,22,24,24); layout.setSpacing(14)
        top=QHBoxLayout(); top.addWidget(SectionHeader("KPI tracker","Monthly targets from your KPI schedule. Each achieved KPI contributes 0.50%.")); top.addStretch(); self.month=QComboBox(); self.configure_months(); self.month.currentIndexChanged.connect(self.refresh); top.addWidget(self.month); layout.addLayout(top)
        inputs=QGridLayout(); inputs.setSpacing(12)
        call_card=Card(); call_l=QVBoxLayout(call_card); call_l.setContentsMargins(16,14,16,14); call_l.addWidget(QLabel("LOG CALLS",objectName="eyebrow")); call_row=QHBoxLayout(); self.phone=QLineEdit(); self.phone.setPlaceholderText("Phone number called"); call_row.addWidget(self.phone,1); self.call_count=QSpinBox(); self.call_count.setRange(1,100); self.call_count.setValue(1); self.call_count.setSuffix(" call" ); call_row.addWidget(self.call_count); self.call_date=QDateEdit(QDate.currentDate()); self.call_date.setCalendarPopup(True); self.call_date.setDisplayFormat("dd MMM"); call_row.addWidget(self.call_date); add_call=QPushButton("＋ Log"); add_call.setProperty("primary",True); add_call.clicked.connect(self.log_call); call_row.addWidget(add_call); call_l.addLayout(call_row); inputs.addWidget(call_card,0,0)
        hours_card=Card(); hours_l=QVBoxLayout(hours_card); hours_l.setContentsMargins(16,14,16,14); hours_l.addWidget(QLabel("LOG HOURS WORKED",objectName="eyebrow")); hours_row=QHBoxLayout(); self.work_date=QDateEdit(QDate.currentDate()); self.work_date.setCalendarPopup(True); self.work_date.setDisplayFormat("dddd, dd MMM"); hours_row.addWidget(self.work_date,1); self.hours=QDoubleSpinBox(); self.hours.setRange(0,24); self.hours.setDecimals(1); self.hours.setValue(10); self.hours.setSuffix(" hours"); hours_row.addWidget(self.hours); save_hours=QPushButton("Save day"); save_hours.clicked.connect(self.save_hours); hours_row.addWidget(save_hours); hours_l.addLayout(hours_row); inputs.addWidget(hours_card,0,1); layout.addLayout(inputs)
        call_progress=Card(); progress_l=QVBoxLayout(call_progress); progress_l.setContentsMargins(16,14,16,14); progress_top=QHBoxLayout(); self.call_title=QLabel(); self.call_title.setStyleSheet("font-size:18px;font-weight:800"); progress_top.addWidget(self.call_title); progress_top.addStretch(); self.call_status=QLabel(); self.call_status.setStyleSheet("font-size:16px;font-weight:800"); progress_top.addWidget(self.call_status); progress_l.addLayout(progress_top); self.call_detail=QLabel(); self.call_detail.setObjectName("muted"); progress_l.addWidget(self.call_detail); self.call_bar=QProgressBar(); progress_l.addWidget(self.call_bar)
        pace_grid=QGridLayout(); pace_grid.setSpacing(10); self.pace_cards={}
        for index,(key,label,color) in enumerate([("pace","Pace today",COLORS["cyan"]),("remaining","Calls remaining",COLORS["purple"]),("average","Average needed",COLORS["amber"]),("current","Current daily average",COLORS["green"])]):
            card=MetricCard(label,accent=color); self.pace_cards[key]=card; pace_grid.addWidget(card,0,index)
        progress_l.addLayout(pace_grid); layout.addWidget(call_progress)
        body=QHBoxLayout(); body.setSpacing(12); summary_card=Card(); summary_l=QVBoxLayout(summary_card); summary_l.setContentsMargins(16,15,16,15); summary_l.addWidget(SectionHeader("Monthly KPI scorecard","Green means the full monthly target has been achieved.")); self.summary=QTableWidget(0,5); self.summary.setHorizontalHeaderLabels(["KPI","TARGET","CURRENT","STATUS","IMPACT"]); self.summary.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.summary.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection); self.summary.verticalHeader().hide(); self.summary.horizontalHeader().setStretchLastSection(True); summary_l.addWidget(self.summary); body.addWidget(summary_card,3)
        log_card=Card(); log_l=QVBoxLayout(log_card); log_l.setContentsMargins(16,15,16,15); log_head=QHBoxLayout(); log_head.addWidget(SectionHeader("Call log","Every number logged for the selected month.")); log_head.addStretch(); remove=QPushButton("Delete selected"); remove.clicked.connect(self.delete_call); log_head.addWidget(remove); log_l.addLayout(log_head); self.calls=QTableWidget(0,3); self.calls.setHorizontalHeaderLabels(["DATE","PHONE","CALLS"]); self.calls.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.calls.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.calls.verticalHeader().hide(); self.calls.horizontalHeader().setStretchLastSection(True); log_l.addWidget(self.calls); body.addWidget(log_card,2); layout.addLayout(body,1); self.refresh()

    def configure_months(self)->None:
        today=date.today(); options=[]
        for offset in range(-12,13):
            total=today.year*12+today.month-1+offset; year,month=divmod(total,12); key=f"{year:04d}-{month+1:02d}"; options.append((key,f"{calendar.month_name[month+1]} {year}"))
        for key,label in options: self.month.addItem(label,key)
        self.month.setCurrentIndex(12)

    def selected_month(self)->str:
        return str(self.month.currentData() or date.today().strftime("%Y-%m"))

    def results(self)->list[tuple[str,str,str,bool]]:
        return monthly_kpi_results(self.db,self.selected_month(),self.CALL_TARGET)

    def refresh(self)->None:
        month=self.selected_month(); call_rows=self.db.kpi_calls(month); total=sum(int(row["call_count"]) for row in call_rows); percent=int(total/self.CALL_TARGET*100); remaining=max(0,self.CALL_TARGET-total); self.call_bar.setRange(0,100); self.call_bar.setValue(min(100,percent)); self.call_title.setText(f"Call Maestro · {total} / {self.CALL_TARGET}"); achieved=total>=self.CALL_TARGET; self.call_status.setText("✓ KPI HIT" if achieved else f"{remaining} remaining"); self.call_status.setStyleSheet(f"font-size:16px;font-weight:800;color:{COLORS['green'] if achieved else COLORS['amber']}"); self.call_detail.setText("Monthly total · uneven days are fine; this tracker recalculates the pace you need from today.")
        pace=call_month_pace(total,month,self.CALL_TARGET); state=str(pace["state"]); delta=int(pace["pace_delta"]); days_left=int(pace["days_left"])
        pace_value={"hit":"✓ KPI HIT","missed":"KPI MISSED","not_started":"NOT STARTED","ahead":f"AHEAD BY {delta}","behind":f"BEHIND BY {abs(delta)}"}[state]
        pace_detail={"hit":"Completed month","missed":"Completed month","not_started":"Future month","ahead":"On track today","behind":"Extra calls needed to recover"}[state]
        self.pace_cards["pace"].set_value(pace_value,pace_detail,accent=COLORS["green"] if state in {"hit","ahead"} else COLORS["red"] if state in {"missed","behind"} else COLORS["muted"])
        self.pace_cards["remaining"].set_value(str(pace["remaining"]),"To reach 240 calls")
        average_text="0" if achieved else f"{float(pace['average_needed']):.1f} / day" if days_left else "No days left"
        self.pace_cards["average"].set_value(average_text,f"Across {days_left} day{'s' if days_left!=1 else ''} remaining")
        self.pace_cards["current"].set_value(f"{float(pace['current_average']):.1f} / day","Calls logged ÷ elapsed month days")
        results=self.results(); self.summary.setRowCount(len(results))
        for i,(name,target,current,hit) in enumerate(results):
            values=[name,target,current,"✓ HIT" if hit else "IN PROGRESS","+0.50%" if hit else "—"]
            for j,value in enumerate(values): self.summary.setItem(i,j,table_item(value,Qt.AlignmentFlag.AlignVCenter,COLORS["green"] if hit and j>=3 else None))
            self.summary.setRowHeight(i,44)
        self.summary.setColumnWidth(0,145); self.summary.setColumnWidth(1,150); self.summary.setColumnWidth(2,170); self.summary.setColumnWidth(3,110)
        self.calls.setRowCount(len(call_rows))
        for i,row in enumerate(call_rows):
            first=table_item(display_call_date(row["called_at"])); first.setData(Qt.ItemDataRole.UserRole,row["id"]); self.calls.setItem(i,0,first); self.calls.setItem(i,1,table_item(row["phone_number"])); self.calls.setItem(i,2,table_item(str(row["call_count"]),Qt.AlignmentFlag.AlignCenter)); self.calls.setRowHeight(i,42)
        self.calls.setColumnWidth(0,125); self.calls.setColumnWidth(1,155)

    def log_call(self)->None:
        try: self.db.add_kpi_calls(self.phone.text(),self.call_count.value(),self.call_date.date().toPython())
        except ValueError as error: QMessageBox.warning(self,"Cannot log call",str(error)); return
        self.phone.clear(); self.call_count.setValue(1); self.refresh(); self.changed.emit(); self.phone.setFocus()

    def save_hours(self)->None:
        self.db.save_kpi_work_day(self.work_date.date().toString("yyyy-MM-dd"),self.hours.value()); self.refresh(); self.changed.emit()

    def delete_call(self)->None:
        row=self.calls.currentRow()
        if row<0: QMessageBox.information(self,"Select a call","Select a call log first."); return
        self.db.delete_kpi_call(int(self.calls.item(row,0).data(Qt.ItemDataRole.UserRole))); self.refresh(); self.changed.emit()


class SuccessChecklistPage(Page):
    """Automatic monthly actions that connect stock, profit and KPI data to Tier 1."""
    def __init__(self,db:Database):
        super().__init__(db)
        outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); layout=QVBoxLayout(content); layout.setContentsMargins(24,22,24,28); layout.setSpacing(14)
        self.header=SectionHeader("Checklist to success","Your live monthly route to Tier 1. Every item updates automatically from the rest of DXB RUNWAY."); layout.addWidget(self.header)
        metrics=QGridLayout(); metrics.setSpacing(12); self.metrics={}
        for column,(key,label,color) in enumerate([("readiness","Tier 1 readiness",COLORS["green"]),("target","Tier 1 profit target",COLORS["purple"]),("projected","Projected month profit",COLORS["cyan"]),("gap","Profit gap",COLORS["amber"])]):
            card=MetricCard(label,accent=color); self.metrics[key]=card; metrics.addWidget(card,0,column)
        layout.addLayout(metrics)
        progress_card=Card(); progress_layout=QVBoxLayout(progress_card); progress_layout.setContentsMargins(18,16,18,16); progress_top=QHBoxLayout(); self.progress_title=QLabel(); self.progress_title.setStyleSheet("font-size:18px;font-weight:800"); progress_top.addWidget(self.progress_title); progress_top.addStretch(); self.progress_status=QLabel(); self.progress_status.setStyleSheet("font-size:16px;font-weight:800"); progress_top.addWidget(self.progress_status); progress_layout.addLayout(progress_top); self.progress_detail=QLabel(); self.progress_detail.setObjectName("muted"); self.progress_detail.setWordWrap(True); progress_layout.addWidget(self.progress_detail); self.progress_bar=QProgressBar(); progress_layout.addWidget(self.progress_bar); layout.addWidget(progress_card)
        checklist_card=Card(); checklist_layout=QVBoxLayout(checklist_card); checklist_layout.setContentsMargins(16,15,16,15); checklist_layout.addWidget(SectionHeader("Live checklist","The first three are the Tier 1 foundation. Every KPI below can remove another 0.50% from the profit percentage you need."))
        self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(["DONE","ACTION","TARGET","CURRENT","WHY IT MATTERS","STATUS"]); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); self.table.setWordWrap(True); self.table.setMinimumHeight(560); checklist_layout.addWidget(self.table); layout.addWidget(checklist_card); outer.addWidget(page_scroll(content)); self.refresh()

    def refresh(self)->None:
        today=date.today(); month=today.strftime("%Y-%m"); budget=self.db.performance_budget(month); cash_used=self.db.active_cash_stock_total(); spend_pct=(cash_used/budget*Decimal("100")) if budget>0 else Decimal("0")
        sold=self.db.sold_vehicles(month); realised=sum((Decimal(str(row["realised_profit_aed"])) for row in sold),Decimal("0")); expected=sum((Decimal(str(row["expected_profit_aed"])) for row in self.db.stock_vehicles()),Decimal("0")); projected=money(realised+expected)
        kpi_hits,kpi_reduction=monthly_kpi_adjustment(self.db,month); tier1_rate=max(Decimal("0"),TARGET_PERCENTAGES[today.month][2]-kpi_reduction); tier1_target=money(budget*tier1_rate); gap=max(Decimal("0"),money(tier1_target-projected))
        foundations=[
            ("Keep cash budget deployed","95% of budget",f"{spend_pct:.1f}% · AED {cash_used:,.0f}","Keeps enough cars working and activates Big Spender.",spend_pct>=Decimal("95")),
            ("Build a Tier 1 profit pipeline",f"AED {tier1_target:,.0f}",f"AED {projected:,.0f}","Sold profit plus expected profit from every car currently in stock.",projected>=tier1_target),
            ("Bank the Tier 1 profit",f"AED {tier1_target:,.0f}",f"AED {realised:,.0f}","Tier is awarded from realised eligible profit, not projected profit.",realised>=tier1_target),
        ]
        kpi_rows=[]
        for name,target,current,hit in monthly_kpi_results(self.db,month,KPITrackerPage.CALL_TARGET):
            if name=="Big Spender": continue
            kpi_rows.append((name,target,current,"Removes 0.50% from every tier goal when achieved.",hit))
        rows=foundations+kpi_rows; self.table.setRowCount(len(rows))
        for row_index,(action,target,current,reason,hit) in enumerate(rows):
            status="✓ COMPLETE" if hit else "TO DO"; values=["✓" if hit else "○",action,target,current,reason,status]
            for column,value in enumerate(values): self.table.setItem(row_index,column,table_item(value,Qt.AlignmentFlag.AlignVCenter,COLORS["green"] if hit and column in {0,5} else None))
            self.table.setRowHeight(row_index,52)
        for column,width in enumerate([58,190,170,175,360]): self.table.setColumnWidth(column,width)
        foundation_hits=sum(1 for *_,hit in foundations if hit); readiness=int(foundation_hits/len(foundations)*100); self.progress_bar.setRange(0,100); self.progress_bar.setValue(readiness)
        self.progress_title.setText(f"{calendar.month_name[today.month]} Tier 1 plan · {foundation_hits} / {len(foundations)} foundations ready")
        ready=foundation_hits==len(foundations); self.progress_status.setText("✓ TIER 1 READY" if ready else f"{len(foundations)-foundation_hits} priority action{'s' if len(foundations)-foundation_hits!=1 else ''} left"); self.progress_status.setStyleSheet(f"font-size:16px;font-weight:800;color:{COLORS['green'] if ready else COLORS['amber']}")
        self.progress_detail.setText(f"Current KPI wins: {kpi_hits} · tier target reduced by {kpi_reduction*100:g}% · live Tier 1 requirement {tier1_rate*100:g}% of AED {budget:,.0f}.")
        self.metrics["readiness"].set_value(f"{readiness}%",f"{foundation_hits} of 3 core conditions")
        self.metrics["target"].set_value(f"AED {tier1_target:,.0f}",f"{tier1_rate*100:g}% after {kpi_hits} KPI win{'s' if kpi_hits!=1 else ''}")
        self.metrics["projected"].set_value(f"AED {projected:,.0f}",f"AED {realised:,.0f} sold + AED {expected:,.0f} stock")
        self.metrics["gap"].set_value("COVERED" if gap==0 else f"AED {gap:,.0f}","Projected profit remaining" if gap else "Current pipeline covers Tier 1",COLORS["green"] if gap==0 else COLORS["amber"])


class StockResearchSignals(QObject):
    finished=Signal(int)


class StockResearchJob(QRunnable):
    """Fetch a single stock forecast without blocking the stock-save flow."""
    def __init__(self,db:Database,vehicle_id:int):
        super().__init__(); self.db=db; self.vehicle_id=vehicle_id; self.signals=StockResearchSignals()

    def run(self)->None:
        try:
            rows=self.db.query("SELECT * FROM vehicles WHERE id=? AND status='stock'",(self.vehicle_id,))
            if not rows:return
            row=rows[0]; subject=stock_research_subject(self.db,f"Research {row['vehicle_name']} in stock")
            if not subject:
                make,model,trim,parsed_year=split_vehicle(str(row["vehicle_name"] or ""))
                if not make or not model:raise DealDriveError("Add a recognisable make and model to run Deal Drive research.")
                year=int(row["market_model_year"] or parsed_year or date.today().year)
                subject={"make":make,"model":model,"trim":str(row["market_trim"] or trim or ""),"year":year,"year_to":year+1,"mileage_km":int(row["mileage_km"] or 50_000),"trim_mode":"smart"}
            else:
                year=int(row["market_model_year"] or subject.get("year") or date.today().year)
                subject.update({"year":year,"year_to":year+1,"mileage_km":int(row["mileage_km"] or subject.get("mileage_km") or 50_000),"trim":str(row["market_trim"] or subject.get("trim") or ""),"trim_mode":"smart"})
            email=self.db.get_setting("deal_drive_email").strip(); workspace=self.db.get_setting("deal_drive_workspace_id").strip(); password=KeychainCredentials().load(email) if email else None
            if not email or not password or not workspace:raise DealDriveError("Connect Deal Drive under Runway AI before automatic stock research can run.")
            client=DealDriveClient(workspace_id=workspace); client.login(email,password); client.verify_market_access()
            result=research_vehicle_now(client,subject)
            self.db.execute("""UPDATE vehicles SET deal_drive_research_status='ready',deal_drive_estimated_days=?,
                deal_drive_archive_samples=?,deal_drive_confidence=?,deal_drive_median_asking_aed=?,
                deal_drive_research_json=?,deal_drive_researched_at=CURRENT_TIMESTAMP WHERE id=?""",
                (result.get("estimated_days_to_sell"),result.get("archive_samples"),result.get("confidence"),result.get("median_asking_aed"),json.dumps(result,default=str),self.vehicle_id))
        except Exception as error:
            self.db.execute("""UPDATE vehicles SET deal_drive_research_status='failed',deal_drive_research_json=?,
                deal_drive_researched_at=CURRENT_TIMESTAMP WHERE id=?""",(json.dumps({"error":str(error)}),self.vehicle_id))
        finally:self.signals.finished.emit(self.vehicle_id)


class StockLevelPage(Page):
    def __init__(self, db: Database):
        super().__init__(db)
        self._research_jobs:dict[int,StockResearchJob]={}; self._researching_ids:set[int]=set(); self._research_after_current:set[int]=set(); self.db.execute("UPDATE vehicles SET deal_drive_research_status='pending' WHERE status='stock' AND deal_drive_research_status='researching'")
        outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0)
        content=QWidget(); layout=QVBoxLayout(content); layout.setContentsMargins(24,22,24,24); layout.setSpacing(14)
        top=QHBoxLayout(); top.addWidget(SectionHeader("Stock level","Every vehicle currently held, including cash purchases and consignments.")); top.addStretch()
        add=QPushButton("＋ Add car"); add.setProperty("primary",True); add.clicked.connect(self.add_vehicle); top.addWidget(add)
        edit=QPushButton("Edit selected"); edit.clicked.connect(self.edit_selected); top.addWidget(edit)
        consignment=QPushButton("Mark as consignment"); consignment.clicked.connect(self.mark_consignment); top.addWidget(consignment)
        sold=QPushButton("Mark selected as sold"); sold.clicked.connect(self.sell_selected); top.addWidget(sold)
        remove=QPushButton("Remove / return to owner"); remove.clicked.connect(self.remove_selected); top.addWidget(remove); layout.addLayout(top)
        budget_card=Card(); budget_layout=QVBoxLayout(budget_card); budget_layout.setContentsMargins(18,15,18,15); budget_top=QHBoxLayout(); self.live_budget_title=QLabel("LIVE PURCHASING BUDGET"); self.live_budget_title.setStyleSheet("font-weight:800"); budget_top.addWidget(self.live_budget_title); budget_top.addStretch(); self.live_budget_value=QLabel(); self.live_budget_value.setStyleSheet("font-size:20px;font-weight:800"); budget_top.addWidget(self.live_budget_value); budget_layout.addLayout(budget_top); self.live_budget_detail=QLabel(); self.live_budget_detail.setObjectName("muted"); budget_layout.addWidget(self.live_budget_detail); self.live_budget_bar=QProgressBar(); budget_layout.addWidget(self.live_budget_bar)
        spend_heading=QLabel("ESTIMATED CASH SPEND NEEDED AT CURRENT MARGIN"); spend_heading.setObjectName("eyebrow"); budget_layout.addWidget(spend_heading); spend_grid=QGridLayout(); spend_grid.setSpacing(10); self.spend_targets={}
        for column,(key,label,color) in enumerate([("tier3","T3 spend guide",COLORS["cyan"]),("tier2","T2 spend guide",COLORS["purple"]),("tier1","T1 spend guide",COLORS["green"])]):
            card=MetricCard(label,accent=color); card.setMinimumHeight(168); card.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed); card.detail.setMinimumHeight(38); self.spend_targets[key]=card; spend_grid.addWidget(card,0,column)
        budget_layout.addLayout(spend_grid); self.spend_note=QLabel("Tier is profit-based, not spend-based. These estimates use your current expected cash-stock margin and exclude consignments. Maintain 95% spend to activate the Big Spender KPI."); self.spend_note.setObjectName("muted"); self.spend_note.setWordWrap(True); budget_layout.addWidget(self.spend_note); layout.addWidget(budget_card)
        metrics=QGridLayout(); metrics.setSpacing(12); self.metrics={}
        for i,(key,label,color) in enumerate([("total","Cars in stock",COLORS["cyan"]),("cash","Cash purchases",COLORS["green"]),("consignment","Consignments",COLORS["purple"]),("value","Total stock value",COLORS["cyan"]),("profit","Expected stock profit",COLORS["amber"])]):
            card=MetricCard(label,accent=color); self.metrics[key]=card; metrics.addWidget(card,0,i)
        layout.addLayout(metrics)
        potential=QGridLayout(); potential.setSpacing(12)
        self.metrics["realistic_potential"]=MetricCard("Realistic potential · 80%",accent=COLORS["green"])
        self.metrics["maximum_potential"]=MetricCard("Maximum potential · 100%",accent=COLORS["amber"])
        potential.addWidget(self.metrics["realistic_potential"],0,0); potential.addWidget(self.metrics["maximum_potential"],0,1)
        potential_note=QLabel("Projection assumes every vehicle currently held sells in the current month, using your saved budget, salary and KPI-adjusted tier goals. Realistic uses 80% of expected profit; maximum uses 100%."); potential_note.setObjectName("muted"); potential_note.setWordWrap(True); potential.addWidget(potential_note,1,0,1,2); layout.addLayout(potential)
        card=Card(); card_layout=QVBoxLayout(card); card_layout.setContentsMargins(16,15,16,15)
        note=QLabel("New stock is saved instantly, then researched against Deal Drive in the background. The forecast uses archived market-exit time, sample size and confidence; it does not treat current listing age as selling time."); note.setObjectName("muted"); note.setWordWrap(True); card_layout.addWidget(note)
        self.table=QTableWidget(0,11); self.table.setHorizontalHeaderLabels(["VEHICLE","STOCK TYPE","STOCKED","COST / PAYOUT","EXPECTED SALE","EXPECTED PROFIT / MARGIN","SPEED GRADE","DEAL DRIVE FORECAST","INTELLIGENCE GRADE","STOCK NO.","KISSFLOW STATUS"]); self.table.setWordWrap(True); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.table.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed); self.table.doubleClicked.connect(self.edit_selected); card_layout.addWidget(self.table); layout.addWidget(card); outer.addWidget(page_scroll(content))
        self.refresh()

    def selected_id(self)->int|None:
        row=self.table.currentRow()
        if row<0 or not self.table.item(row,0): return None
        value=self.table.item(row,0).data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    def refresh(self)->None:
        rows=self.db.stock_vehicles(); rate=Decimal(self.db.get_setting("gbp_aed_rate","4.928313"))
        live_budget=self.db.performance_budget(date.today().strftime("%Y-%m")); cash_used=self.db.active_cash_stock_total(); remaining=money(live_budget-cash_used); remaining_aed,remaining_gbp=dual_amount(remaining,rate,signed=remaining<0); used_percent=int(cash_used/live_budget*100) if live_budget>0 else (100 if cash_used else 0); self.live_budget_bar.setRange(0,100); self.live_budget_bar.setValue(max(0,min(100,used_percent))); budget_color=COLORS["red"] if remaining<0 else COLORS["amber"] if live_budget>0 and remaining/live_budget<Decimal("0.15") else COLORS["green"]; self.live_budget_value.setText(f"{remaining_aed}  /  {remaining_gbp} remaining"); self.live_budget_value.setStyleSheet(f"font-size:20px;font-weight:800;color:{budget_color}"); self.live_budget_detail.setText(f"AED {cash_used:,.0f} tied up in unsold cash stock from a revolving AED {live_budget:,.0f} budget · consignments excluded · {used_percent}% used")
        cash=[row for row in rows if row["purchase_type"]=="cash"]; consignment=[row for row in rows if row["purchase_type"]=="consignment"]
        stock_value=sum((Decimal(str(row["expected_sale_price_aed"])) for row in rows),Decimal("0"))
        expected=sum((Decimal(str(row["expected_profit_aed"])) for row in rows),Decimal("0"))
        cash_invested=sum((Decimal(str(row["purchase_price_aed"])) for row in cash),Decimal("0")); cash_expected_profit=sum((Decimal(str(row["expected_profit_aed"])) for row in cash),Decimal("0")); cash_margin=(cash_expected_profit/cash_invested) if cash_invested>0 else Decimal("0"); spend_month=date.today().strftime("%Y-%m"); _,spend_kpi_reduction=monthly_kpi_adjustment(self.db,spend_month); _,spend_month_number=(int(value) for value in spend_month.split("-")); spend_targets=TARGET_PERCENTAGES[spend_month_number]
        for key,label,target in [("tier3","T3",spend_targets[0]),("tier2","T2",spend_targets[1]),("tier1","T1",spend_targets[2])]:
            adjusted_target=max(Decimal("0"),target-spend_kpi_reduction); target_profit=money(live_budget*adjusted_target)
            if cash_margin>0:
                spend_needed=money(target_profit/cash_margin); spend_percent=(spend_needed/live_budget*Decimal("100")) if live_budget>0 else Decimal("0"); spend_color=COLORS["green"] if spend_percent<=Decimal("95") else COLORS["amber"] if spend_percent<=Decimal("100") else COLORS["red"]; detail=f"{spend_percent:.1f}% budget · target AED {target_profit:,.0f}\n{adjusted_target*100:g}% after KPI · {cash_margin*100:.1f}% margin"; self.spend_targets[key].set_value(f"AED {spend_needed:,.0f}",detail,spend_color)
            else:
                self.spend_targets[key].set_value("—","Add cash stock to estimate spend at margin",COLORS["muted"])
        self.metrics["total"].set_value(str(len(rows)),"All unsold vehicles")
        self.metrics["cash"].set_value(str(len(cash)),f"AED {sum((Decimal(str(row['purchase_price_aed'])) for row in cash),Decimal('0')):,.0f} invested")
        self.metrics["consignment"].set_value(str(len(consignment)),"Held without using cash budget")
        stock_value_aed,stock_value_gbp=dual_amount(stock_value,rate); self.metrics["value"].set_value(stock_value_aed,f"{stock_value_gbp} · includes consignments")
        expected_aed,expected_gbp=dual_amount(expected,rate,signed=True); self.metrics["profit"].set_value(expected_aed,expected_gbp)
        month_key=date.today().strftime("%Y-%m"); year,month_number=(int(value) for value in month_key.split("-")); budget=self.db.performance_budget(month_key); salary=Decimal(self.db.get_setting("salary_aed","6000")); _,kpi_reduction=monthly_kpi_adjustment(self.db,month_key)
        expected_for_projection=max(Decimal("0"),expected)
        realistic_profit=money(expected_for_projection*Decimal("0.80")); maximum_profit=money(expected_for_projection)
        realistic_result=calculate_earnings(year=year,month=month_number,budget_aed=budget,eligible_profit_aed=realistic_profit,salary_aed=salary,target_percentage_reduction=kpi_reduction)
        maximum_result=calculate_earnings(year=year,month=month_number,budget_aed=budget,eligible_profit_aed=maximum_profit,salary_aed=salary,target_percentage_reduction=kpi_reduction)
        realistic_total_aed,realistic_total_gbp=dual_amount(realistic_result.total_earned_aed,rate); maximum_total_aed,maximum_total_gbp=dual_amount(maximum_result.total_earned_aed,rate)
        realistic_profit_aed,_=dual_amount(realistic_profit,rate,signed=True); maximum_profit_aed,_=dual_amount(maximum_profit,rate,signed=True)
        self.metrics["realistic_potential"].set_value(realistic_result.tier.value,f"{realistic_profit_aed} profit · {realistic_total_aed} total ({realistic_total_gbp})",COLORS["green"] if realistic_result.tier!=CommissionTier.BASELINE else COLORS["cyan"])
        self.metrics["maximum_potential"].set_value(maximum_result.tier.value,f"{maximum_profit_aed} profit · {maximum_total_aed} total ({maximum_total_gbp})",COLORS["green"] if maximum_result.tier!=CommissionTier.BASELINE else COLORS["cyan"])
        self.table.setRowCount(len(rows))
        pending_ids=[]
        for i,row in enumerate(rows):
            self.table.setRowHeight(i,64); first=table_item(row["vehicle_name"]); first.setData(Qt.ItemDataRole.UserRole,row["id"]); first.setToolTip(row["notes"] or f"Expected sale · AED {row['expected_sale_price_aed']:,.0f}"); self.table.setItem(i,0,first)
            cost=Decimal(str(row["purchase_price_aed"])); sale=Decimal(str(row["expected_sale_price_aed"])); profit=Decimal(str(row["expected_profit_aed"]))
            margin=vehicle_margin_percent(profit,cost); days_held=max(0,(date.today()-date.fromisoformat(str(row["purchased_date"])[:10])).days); grade=vehicle_speed_grade(days_held)
            make,model,trim,model_year=split_vehicle(row["vehicle_name"])
            intelligence=analyse_opportunity(self.db,make=make,model=model,trim=trim,model_year=model_year,purchase_price_aed=float(cost),expected_sale_price_aed=float(sale)) if make and model else {"grade":"NO GRADE","decision":"INSUFFICIENT DATA","confidence":"none","sample_size":0}
            intelligence_text=f"{intelligence['grade']} · {intelligence['decision']}\n{intelligence['confidence']} confidence · {intelligence.get('sample_size',0)} comps"
            research_status=str(row["deal_drive_research_status"] or "not_requested")
            if research_status in {"pending","researching"}:
                forecast="RESEARCHING…\nDeal Drive background check"; forecast_color=COLORS["cyan"]
                if research_status=="pending":pending_ids.append(int(row["id"]))
            elif research_status=="ready" and row["deal_drive_estimated_days"] is not None:
                forecast=f"≈ {float(row['deal_drive_estimated_days']):.0f} days\n{row['deal_drive_confidence'] or 'Low'} · {int(row['deal_drive_archive_samples'] or 0)} archive"; forecast_color=COLORS["green"] if float(row["deal_drive_estimated_days"])<45 else COLORS["amber"]
            elif research_status=="failed":
                try:error=str(json.loads(row["deal_drive_research_json"] or "{}").get("error") or "Research unavailable")
                except (ValueError,TypeError):error="Research unavailable"
                forecast=f"UNAVAILABLE\n{error[:42]}"; forecast_color=COLORS["red"]
            else:forecast="NOT RESEARCHED\nAdded before auto research";forecast_color=COLORS["muted"]
            values=["Cash purchase" if row["purchase_type"]=="cash" else "Consignment",row["purchased_date"],f"{cost:,.0f} AED\n{gbp_equivalent(cost,rate):,.0f} GBP",f"{sale:,.0f} AED\n{gbp_equivalent(sale,rate):,.0f} GBP",f"{profit:+,.0f} AED\n{gbp_equivalent(profit,rate):+,.0f} GBP\n{margin:.1f}% margin",f"{grade}\n{days_held} days held",forecast,intelligence_text]
            for j,value in enumerate(values,1):
                color=COLORS["purple"] if j==1 and row["purchase_type"]=="consignment" else COLORS["green"] if j==5 and profit>=0 else COLORS["red"] if j==5 else vehicle_grade_color(grade) if j==6 else forecast_color if j==7 else COLORS["green"] if j==8 and intelligence["decision"]=="BUY" else COLORS["amber"] if j==8 and intelligence["decision"]=="NEGOTIATE" else COLORS["red"] if j==8 and intelligence["decision"]=="AVOID" else COLORS["muted"] if j==8 else None
                item=table_item(value,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight if j>=3 else Qt.AlignmentFlag.AlignVCenter,color)
                if j==7:item.setToolTip(str(row["deal_drive_research_json"] or ""))
                self.table.setItem(i,j,item)
            stock_number=str(row["external_stock_number"] or "").strip() or "Awaiting email"
            kissflow_status=str(row["external_stock_status"] or "").strip() or "NOT LINKED"
            if row["external_live_price_aed"] is not None:kissflow_status+=f"\nLive AED {float(row['external_live_price_aed']):,.0f}"
            self.table.setItem(i,9,table_item(stock_number,Qt.AlignmentFlag.AlignVCenter,COLORS["cyan"] if stock_number!="Awaiting email" else COLORS["muted"]))
            self.table.setItem(i,10,table_item(kissflow_status,Qt.AlignmentFlag.AlignVCenter,COLORS["green"] if kissflow_status not in {"NOT LINKED","UPDATE"} else COLORS["muted"]))
        self.table.setColumnWidth(0,150); self.table.setColumnWidth(1,115); self.table.setColumnWidth(2,95); self.table.setColumnWidth(3,125); self.table.setColumnWidth(4,125); self.table.setColumnWidth(5,150); self.table.setColumnWidth(6,105); self.table.setColumnWidth(7,190); self.table.setColumnWidth(8,190); self.table.setColumnWidth(9,105)
        visible_height=self.table.horizontalHeader().height()+sum(self.table.rowHeight(index) for index in range(self.table.rowCount()))+self.table.frameWidth()*2+8
        self.table.setFixedHeight(max(420,visible_height))
        for vehicle_id in pending_ids:QTimer.singleShot(0,lambda value=vehicle_id:self._start_stock_research(value))

    def _start_stock_research(self,vehicle_id:int)->None:
        if vehicle_id in self._researching_ids:return
        rows=self.db.query("SELECT deal_drive_research_status FROM vehicles WHERE id=? AND status='stock'",(vehicle_id,))
        if not rows or rows[0]["deal_drive_research_status"]!="pending":return
        self._researching_ids.add(vehicle_id); self.db.execute("UPDATE vehicles SET deal_drive_research_status='researching' WHERE id=?",(vehicle_id,))
        job=StockResearchJob(self.db,vehicle_id); self._research_jobs[vehicle_id]=job; job.signals.finished.connect(self._stock_research_finished); QThreadPool.globalInstance().start(job); self.refresh()

    def _stock_research_finished(self,vehicle_id:int)->None:
        self._researching_ids.discard(vehicle_id); self._research_jobs.pop(vehicle_id,None)
        if vehicle_id in self._research_after_current:
            self._research_after_current.discard(vehicle_id)
            self.db.execute("UPDATE vehicles SET deal_drive_research_status='pending' WHERE id=? AND status='stock'",(vehicle_id,))
        self.refresh()

    def add_vehicle(self)->None:
        dialog=VehicleDialog(self.db,self)
        if dialog.exec():
            self.db.add_vehicle(**dialog.values()); rematch_cached_appointments(self.db); self.refresh(); self.changed.emit()

    def edit_selected(self)->None:
        vehicle_id=self.selected_id()
        if vehicle_id is None: QMessageBox.information(self,"Select a car","Select the stock vehicle you want to edit."); return
        rows=self.db.query("SELECT * FROM vehicles WHERE id=? AND status='stock'",(vehicle_id,))
        if not rows: QMessageBox.warning(self,"No longer in stock","That vehicle is no longer available in stock."); self.refresh(); return
        dialog=VehicleDialog(self.db,self,vehicle=rows[0])
        if not dialog.exec():return
        try:
            if vehicle_id in self._researching_ids:self._research_after_current.add(vehicle_id)
            self.db.update_stock_vehicle(vehicle_id,**dialog.values())
            rematched=rematch_cached_appointments(self.db)
        except ValueError as error:
            QMessageBox.warning(self,"Could not save vehicle",str(error)); return
        self.refresh(); self.changed.emit()
        QMessageBox.information(self,"Stock vehicle updated",f"Saved and rewired across Runway. {rematched} upcoming appointment{'s' if rematched!=1 else ''} rematched. A fresh Deal Drive scan is queued.")

    def sell_selected(self)->None:
        vehicle_id=self.selected_id()
        if vehicle_id is None: QMessageBox.information(self,"Select a car","Select a vehicle from stock first."); return
        rows=self.db.query("SELECT * FROM vehicles WHERE id=? AND status='stock'",(vehicle_id,))
        if not rows: QMessageBox.warning(self,"No longer in stock","That vehicle is no longer available in stock."); self.refresh(); return
        dialog=SellVehicleDialog(rows[0],self)
        if dialog.exec(): self.db.sell_vehicle(vehicle_id,**dialog.values()); self.refresh(); self.changed.emit()

    def mark_consignment(self)->None:
        vehicle_id=self.selected_id()
        if vehicle_id is None: QMessageBox.information(self,"Select a car","Select the vehicle you want to mark as consignment."); return
        vehicle=self.db.query("SELECT * FROM vehicles WHERE id=? AND status='stock'",(vehicle_id,))[0]
        if vehicle["purchase_type"]=="consignment": QMessageBox.information(self,"Already consignment","This vehicle is already marked as consignment stock."); return
        payout,ok=QInputDialog.getDouble(self,"Mark as consignment","Agreed owner payout · AED",vehicle["purchase_price_aed"],0.01,100_000_000,2)
        if ok: self.db.mark_vehicle_consignment(vehicle_id,payout); self.refresh(); self.changed.emit(); QMessageBox.information(self,"Consignment saved","This vehicle no longer uses the cash purchasing budget.")

    def remove_selected(self)->None:
        vehicle_id=self.selected_id()
        if vehicle_id is None: QMessageBox.information(self,"Select a car","Select a vehicle from stock first."); return
        name=self.table.item(self.table.currentRow(),0).text(); vehicle=self.db.query("SELECT purchase_type FROM vehicles WHERE id=?",(vehicle_id,))[0]; consignment=vehicle["purchase_type"]=="consignment"; title="Return consignment to owner" if consignment else "Remove from stock"; message=f"Return {name} to the owner and remove it from Stock Level? No sale or profit will be recorded." if consignment else f"Remove {name} from Stock Level? This does not mark it as sold."
        if QMessageBox.question(self,title,message)==QMessageBox.StandardButton.Yes:
            self.db.remove_stock_vehicle(vehicle_id); self.refresh(); self.changed.emit()


class VehicleDeskPage(Page):
    def __init__(self, db: Database):
        super().__init__(db); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); root=QVBoxLayout(content); root.setContentsMargins(24,22,24,28); root.setSpacing(15)
        top=QHBoxLayout(); top.addWidget(SectionHeader("Vehicle desk","Green is the current month; orange is the commission being paid now.")); top.addStretch(); self.month=QComboBox(); self.month.addItems(list(calendar.month_name)[1:]); self.configure_month_options(); self.month.setCurrentIndex(date.today().month-1); self.month.currentIndexChanged.connect(self.refresh); top.addWidget(self.month); root.addLayout(top)
        controls=Card(); control_grid=QGridLayout(controls); control_grid.setContentsMargins(16,14,16,14); control_grid.setHorizontalSpacing(12); self.budget=MoneyBox(); self.budget.setValue(3_000_000); save_budget=QPushButton("Save month budget"); save_budget.clicked.connect(self.save_budget); self.salary=MoneyBox(); self.salary.setValue(float(db.get_setting("salary_aed","6000"))); save_salary=QPushButton("Save monthly salary"); save_salary.clicked.connect(self.save_salary)
        control_grid.addWidget(QLabel("SELECTED MONTH PURCHASING BUDGET · AED"),0,0); self.budget_remaining=QLabel(); self.budget_remaining.setToolTip("Assigned purchasing budget minus cash purchases in the selected month. Consignment stock is excluded."); control_grid.addWidget(self.budget_remaining,0,1); control_grid.addWidget(QLabel("MONTHLY BASE SALARY · AED"),0,2); control_grid.addWidget(self.budget,1,0); control_grid.addWidget(save_budget,1,1); control_grid.addWidget(self.salary,1,2); control_grid.addWidget(save_salary,1,3); root.addWidget(controls)
        metrics=QGridLayout(); metrics.setSpacing(12); self.metrics={}
        for i,(key,label,color) in enumerate([("sold","Sold this month",COLORS["green"]),("profit","Realised profit",COLORS["green"]),("commission","Commission earned",COLORS["green"]),("total","Total earned",COLORS["purple"])]):
            card=MetricCard(label,accent=color); self.metrics[key]=card; metrics.addWidget(card,0,i)
        root.addLayout(metrics)
        tier_card=Card(); tier_layout=QVBoxLayout(tier_card); tier_layout.setContentsMargins(18,15,18,15); tier_top=QHBoxLayout(); self.tier=QLabel("BASELINE · 4%"); self.tier.setStyleSheet(f"font-size:20px;font-weight:800;color:{COLORS['cyan']}"); tier_top.addWidget(self.tier); tier_top.addStretch(); self.achievement=QLabel(); self.achievement.setObjectName("muted"); tier_top.addWidget(self.achievement); tier_layout.addLayout(tier_top); self.schedule=QLabel(); self.schedule.setObjectName("muted"); self.schedule.setWordWrap(True); tier_layout.addWidget(self.schedule); self.tier_progress=QProgressBar(); tier_layout.addWidget(self.tier_progress); root.addWidget(tier_card)
        tier_matrix=Card(); matrix_layout=QVBoxLayout(tier_matrix); matrix_layout.setContentsMargins(16,15,16,15); matrix_layout.addWidget(SectionHeader("Monthly tier percentages","Standard targets before KPI reductions, using the selected month's purchasing budget across every row. The live tracker still uses KPI-adjusted thresholds."))
        earnings_cards=QGridLayout(); earnings_cards.setSpacing(12); self.tier_earnings={}
        for column,(key,label,color) in enumerate([("tier3","Tier 3 total pay",COLORS["cyan"]),("tier2","Tier 2 total pay",COLORS["purple"]),("tier1","Tier 1 total pay",COLORS["green"])]):
            card=MetricCard(label,accent=color); self.tier_earnings[key]=card; earnings_cards.addWidget(card,0,column)
        matrix_layout.addLayout(earnings_cards)
        self.tier_table=QTableWidget(12,7); self.tier_table.setHorizontalHeaderLabels(["MONTH","BUDGET · AED","BASELINE RATE","TIER 3 PROFIT / RATE","TIER 2 PROFIT / RATE","TIER 1 PROFIT / RATE","ACHIEVED TIER / RATE"]); self.tier_table.setWordWrap(True); self.tier_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.tier_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.tier_table.verticalHeader().hide(); self.tier_table.horizontalHeader().setStretchLastSection(True); self.tier_table.setMinimumHeight(390); matrix_layout.addWidget(self.tier_table); root.addWidget(tier_matrix)
        sections=QHBoxLayout(); sections.setSpacing(12)
        sold_card=Card(); sold_layout=QVBoxLayout(sold_card); sold_layout.setContentsMargins(16,15,16,15); sold_head=QHBoxLayout(); sold_head.addWidget(SectionHeader("Sold in selected month","The view resets with each month; all earlier months remain available above.")); sold_head.addStretch(); undo=QPushButton("Return selected to stock"); undo.clicked.connect(self.return_selected); sold_head.addWidget(undo); sold_layout.addLayout(sold_head)
        self.sold_table=QTableWidget(0,5); self.sold_table.setHorizontalHeaderLabels(["VEHICLE","STOCK TYPE","SOLD","REALISED PROFIT","COMMISSION"]); self.sold_table.setWordWrap(True); self.sold_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.sold_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.sold_table.verticalHeader().hide(); self.sold_table.horizontalHeader().setStretchLastSection(True); sold_layout.addWidget(self.sold_table); sections.addWidget(sold_card,1); root.addLayout(sections,1)
        foot=QLabel("Each month name always shows its latest occurrence. Older years remain stored under Leads → Vehicle performance. Commission syncs automatically to Overview, Calendar and Reports."); foot.setObjectName("muted"); foot.setWordWrap(True); root.addWidget(foot); outer.addWidget(page_scroll(content)); self.system_month=date.today().strftime("%Y-%m"); self.month_timer=QTimer(self); self.month_timer.setInterval(60_000); self.month_timer.timeout.connect(self.check_month_rollover); self.month_timer.start(); self.refresh()

    def check_month_rollover(self)->None:
        new_month=date.today().strftime("%Y-%m")
        if new_month!=self.system_month:
            self.configure_month_options()
            self.month.setCurrentIndex(date.today().month-1)
            self.system_month=new_month
            self.refresh()

    def configure_month_options(self,today:date|None=None)->None:
        current=today or date.today(); payment_month=((current.month-3)%12)+1
        for month_number in range(1,13):
            month_key=latest_occurrence_for_month(month_number,current); year=int(month_key[:4])
            self.month.setItemText(month_number-1,f"{calendar.month_name[month_number]} {year}")
            self.month.setItemData(month_number-1,month_key,Qt.ItemDataRole.UserRole)
            background=QColor("#174f40") if month_number==current.month else QColor("#5a4316") if month_number==payment_month else QColor()
            foreground=QColor(COLORS["green"]) if month_number==current.month else QColor(COLORS["amber"]) if month_number==payment_month else QColor(COLORS["text"])
            tooltip="Current month" if month_number==current.month else "Commission paid this month · two-month delay" if month_number==payment_month else ""
            self.month.setItemData(month_number-1,background,Qt.ItemDataRole.BackgroundRole)
            self.month.setItemData(month_number-1,foreground,Qt.ItemDataRole.ForegroundRole)
            self.month.setItemData(month_number-1,tooltip,Qt.ItemDataRole.ToolTipRole)

    def selected_month(self)->str:
        return str(self.month.currentData(Qt.ItemDataRole.UserRole))

    def selected_id(self, table: QTableWidget) -> int | None:
        row=table.currentRow()
        if row<0 or not table.item(row,0): return None
        value=table.item(row,0).data(Qt.ItemDataRole.UserRole); return int(value) if value is not None else None

    def refresh(self)->None:
        month=self.selected_month(); year,month_number=(int(value) for value in month.split("-")); month_label=calendar.month_name[month_number]; rate=Decimal(self.db.get_setting("gbp_aed_rate","4.928313")); salary=Decimal(self.db.get_setting("salary_aed","6000")); budget=self.db.performance_budget(month); purchased_total=self.db.active_cash_stock_total(); remaining_budget=money(budget-purchased_total)
        self.budget.blockSignals(True); self.budget.setValue(float(budget)); self.budget.blockSignals(False)
        self.salary.blockSignals(True); self.salary.setValue(float(salary)); self.salary.blockSignals(False)
        remaining_aed,remaining_gbp=dual_amount(remaining_budget,rate); remaining_color=COLORS["red"] if remaining_budget<0 else COLORS["amber"] if budget>0 and remaining_budget/budget<Decimal("0.15") else COLORS["green"]; self.budget_remaining.setText(f"BUDGET REMAINING  ·  {remaining_aed}  /  {remaining_gbp}"); self.budget_remaining.setStyleSheet(f"color:{remaining_color};font-weight:800")
        sold=self.db.sold_vehicles(month); realised=sum((Decimal(str(row["realised_profit_aed"])) for row in sold),Decimal("0")); kpi_hits,kpi_reduction=monthly_kpi_adjustment(self.db,month); result=calculate_earnings(year=year,month=month_number,budget_aed=budget,eligible_profit_aed=max(Decimal("0"),realised),average_margin_aed=24700,salary_aed=salary,target_percentage_reduction=kpi_reduction)
        if month<=date.today().strftime("%Y-%m") and (sold or month==date.today().strftime("%Y-%m")): self.sync_earnings(result,year,month_number)
        rate_pct=f"{float(result.rate*100):g}%"; self.current_result=result; self.metrics["sold"].set_value(str(len(sold)),month_label); profit_aed,profit_gbp=dual_amount(realised,rate,signed=True); self.metrics["profit"].set_value(profit_aed,profit_gbp,COLORS["red"] if realised<0 else COLORS["green"]); commission_aed,commission_gbp=dual_amount(result.commission_aed,rate); self.metrics["commission"].set_value(commission_aed,f"{commission_gbp} · Commission only · {result.tier.value} at {rate_pct}"); total_aed,total_gbp=dual_amount(result.total_earned_aed,rate); self.metrics["total"].set_value(total_aed,f"{total_gbp} · Base AED {result.salary_aed:,.0f} + commission AED {result.commission_aed:,.0f}")
        tier_color=COLORS["green"] if result.tier!=CommissionTier.BASELINE else COLORS["cyan"]; self.tier.setText(f"{result.tier.value.upper()} · {rate_pct}"); self.tier.setStyleSheet(f"font-size:20px;font-weight:800;color:{tier_color}")
        original_t3,original_t2,original_t1=TARGET_PERCENTAGES[month_number]; t3,t2,t1=(max(Decimal("0"),target-kpi_reduction) for target in (original_t3,original_t2,original_t1)); achieved=(realised/budget*100) if budget>0 else Decimal("0"); self.achievement.setText(f"Profit achieved · {achieved:.2f}% of purchasing budget · {kpi_hits} KPI hit{'s' if kpi_hits!=1 else ''} = -{float(kpi_reduction*100):g}% from tier goals"); self.schedule.setText(f"{month_label} adjusted targets · Tier 3 {float(t3*100):g}%  ·  Tier 2 {float(t2*100):g}%  ·  Tier 1 {float(t1*100):g}%"+(f"  ·  Next tier in AED {result.distance_to_next_aed:,.0f}" if result.next_tier else "  ·  Highest tier reached")); self.tier_progress.setRange(0,max(1,int(t1*10000))); self.tier_progress.setValue(max(0,min(self.tier_progress.maximum(),int(achieved*100))))
        for key,label,target,commission_rate in [("tier3","Tier 3",original_t3,Decimal("0.05")),("tier2","Tier 2",original_t2,Decimal("0.065")),("tier1","Tier 1",original_t1,Decimal("0.08"))]:
            target_profit=money(budget*target); commission=money(target_profit*commission_rate); total=money(salary+commission); total_aed,total_gbp=dual_amount(total,rate); self.tier_earnings[key].set_value(total_aed,f"{total_gbp} · {label} profit needed AED {target_profit:,.0f} · {target*100:g}% before KPI · rate {commission_rate*100:g}% · live tracker KPI reduction -{float(kpi_reduction*100):g}%")
        self.sold_table.setRowCount(len(sold))
        for i,row in enumerate(sold):
            self.sold_table.setRowHeight(i,56); first=table_item(row["vehicle_name"]); first.setData(Qt.ItemDataRole.UserRole,row["id"]); first.setToolTip(f"Sale price · AED {row['sold_price_aed']:,.0f}"); self.sold_table.setItem(i,0,first); profit=Decimal(str(row["realised_profit_aed"])); commission=money(profit*result.rate) if realised>0 else Decimal("0"); values=[row["sold_date"],f"{profit:+,.0f} AED\n{gbp_equivalent(profit,rate):+,.0f} GBP",f"{commission:+,.0f} AED\n{gbp_equivalent(commission,rate):+,.0f} GBP"]
            values.insert(0,"Cash purchase" if row["purchase_type"]=="cash" else "Consignment")
            for j,value in enumerate(values,1): self.sold_table.setItem(i,j,table_item(value,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight,color=COLORS["purple"] if j==1 and row["purchase_type"]=="consignment" else COLORS["green"] if j in {3,4} and profit>=0 else COLORS["red"] if j in {3,4} else None))
        self.sold_table.setColumnWidth(0,140); self.sold_table.setColumnWidth(1,120); self.sold_table.setColumnWidth(2,95); self.sold_table.setColumnWidth(3,150); self.sold_table.horizontalHeader().setStretchLastSection(True)
        self.refresh_tier_table(salary,budget)

    def refresh_tier_table(self,salary:Decimal,table_budget:Decimal|None=None)->None:
        table_budget=table_budget if table_budget is not None else self.db.performance_budget(self.selected_month())
        self.tier_table.setRowCount(12)
        for row_index in range(12):
            month_number=row_index+1; month=str(self.month.itemData(row_index,Qt.ItemDataRole.UserRole)); year=int(month[:4]); sold=self.db.sold_vehicles(month); realised=sum((Decimal(str(vehicle["realised_profit_aed"])) for vehicle in sold),Decimal("0")); kpi_hits,kpi_reduction=monthly_kpi_adjustment(self.db,month); result=calculate_earnings(year=year,month=month_number,budget_aed=table_budget,eligible_profit_aed=max(Decimal("0"),realised),salary_aed=salary,target_percentage_reduction=kpi_reduction); original=TARGET_PERCENTAGES[month_number]; original_t3,original_t2,original_t1=original
            target_profits=[money(table_budget*target) for target in original]
            values=[self.month.itemText(row_index),f"{table_budget:,.0f}","4%",f"AED {target_profits[0]:,.0f}\n{float(original_t3*100):g}% / 5%",f"AED {target_profits[1]:,.0f}\n{float(original_t2*100):g}% / 6.5%",f"AED {target_profits[2]:,.0f}\n{float(original_t1*100):g}% / 8%",f"{result.tier.value} / {float(result.rate*100):g}% · {kpi_hits} KPI"]
            for column,value in enumerate(values):
                item=table_item(str(value),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight if column else Qt.AlignmentFlag.AlignVCenter,COLORS["green"] if column==6 and result.tier!=CommissionTier.BASELINE else COLORS["cyan"] if column==6 else None); self.tier_table.setItem(row_index,column,item)
            self.tier_table.setRowHeight(row_index,48)
        for column,width in enumerate([125,125,105,145,145,145]): self.tier_table.setColumnWidth(column,width)

    def sync_earnings(self,result,year:int,month_number:int)->None:
        earned_date=date(year,month_number,calendar.monthrange(year,month_number)[1]).isoformat()
        self.db.execute("INSERT INTO earnings(year,month,purchasing_budget_aed,eligible_profit_aed,average_margin_aed,deductions_aed,tier,salary_aed,commission_aed,earned_date,payment_date,received) VALUES (?,?,?,?,?,?,?,?,?,?,?,0) ON CONFLICT(year,month) DO UPDATE SET purchasing_budget_aed=excluded.purchasing_budget_aed,eligible_profit_aed=excluded.eligible_profit_aed,average_margin_aed=excluded.average_margin_aed,deductions_aed=excluded.deductions_aed,tier=excluded.tier,salary_aed=excluded.salary_aed,commission_aed=excluded.commission_aed,earned_date=excluded.earned_date,payment_date=excluded.payment_date",(year,month_number,float(result.budget_aed),float(result.eligible_profit_aed),24700,0,result.tier.value,float(result.salary_aed),float(result.commission_aed),earned_date,result.payment_date.isoformat()))

    def save_budget(self)->None:
        self.db.set_performance_budget(self.selected_month(),self.budget.value()); self.refresh(); self.changed.emit()

    def save_salary(self)->None:
        self.db.set_setting("salary_aed",f"{self.salary.value():.2f}")
        current=date.today().strftime("%Y-%m"); year,month_number=(int(value) for value in current.split("-")); budget=self.db.performance_budget(current); sold=self.db.sold_vehicles(current); realised=sum((Decimal(str(row["realised_profit_aed"])) for row in sold),Decimal("0")); _,kpi_reduction=monthly_kpi_adjustment(self.db,current); result=calculate_earnings(year=year,month=month_number,budget_aed=budget,eligible_profit_aed=max(Decimal("0"),realised),salary_aed=self.salary.value(),target_percentage_reduction=kpi_reduction); self.sync_earnings(result,year,month_number)
        self.refresh(); self.changed.emit()

    def return_selected(self)->None:
        vehicle_id=self.selected_id(self.sold_table)
        if vehicle_id is None: QMessageBox.information(self,"Select a car","Select a sold vehicle first."); return
        if QMessageBox.question(self,"Return to stock","Move this vehicle back to current stock and remove its profit from this month?")==QMessageBox.StandardButton.Yes: self.db.return_vehicle_to_stock(vehicle_id); self.refresh(); self.changed.emit()


class VehicleHistoryPage(Page):
    def __init__(self,db:Database):
        super().__init__(db); layout=QVBoxLayout(self); layout.setContentsMargins(24,22,24,24); layout.setSpacing(14)
        layout.addWidget(SectionHeader("Vehicle performance","See monthly history and which models turn into profit fastest."))
        note=QLabel("Vehicle Desk shows only the latest occurrence of each month name. Nothing is deleted when a month rolls into a new year."); note.setObjectName("muted"); note.setWordWrap(True); layout.addWidget(note)
        layout.addWidget(SectionHeader("Monthly history","Archived monthly performance stays available for year-on-year comparison."))
        self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(["MONTH","CARS SOLD","REALISED PROFIT","COMMISSION","PURCHASING BUDGET","CASH PURCHASED"]); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); self.table.setMinimumHeight(230); layout.addWidget(self.table)
        layout.addWidget(SectionHeader("Performance by vehicle","Averages include every sold vehicle; leading model years are ignored so repeated Minis and similar models are grouped together. Speed grade uses average days in stock: A+ <10 days · A ≤20 · B ≤30 · C ≤60 · C- >60."))
        self.performance_table=QTableWidget(0,8); self.performance_table.setHorizontalHeaderLabels(["MODEL","SOLD","AVG DAYS IN STOCK","GRADE","AVG PURCHASE / PAYOUT","AVG SOLD PRICE","AVG PROFIT","AVG MARGIN"]); self.performance_table.setWordWrap(True); self.performance_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.performance_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.performance_table.verticalHeader().hide(); self.performance_table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.performance_table,1); self.refresh()

    def refresh(self)->None:
        months=self.db.query(
            "SELECT month FROM performance_months UNION "
            "SELECT substr(sold_date,1,7) month FROM vehicles WHERE sold_date IS NOT NULL UNION "
            "SELECT printf('%04d-%02d',year,month) month FROM earnings ORDER BY month DESC"
        )
        rate=Decimal(self.db.get_setting("gbp_aed_rate","4.928313")); self.table.setRowCount(len(months))
        for i,item in enumerate(months):
            month=item["month"]; year,month_number=(int(value) for value in month.split("-")); sold=self.db.sold_vehicles(month)
            realised=sum((Decimal(str(row["realised_profit_aed"])) for row in sold),Decimal("0")); earnings=self.db.query("SELECT commission_aed FROM earnings WHERE year=? AND month=?",(year,month_number)); commission=Decimal(str(earnings[0]["commission_aed"])) if earnings else Decimal("0")
            budget=self.db.performance_budget(month); purchased=self.db.monthly_vehicle_purchase_total(month); label=date(year,month_number,1).strftime("%B %Y")
            values=[label,str(len(sold)),*["\n".join(dual_amount(value,rate,signed=value in {realised,commission})) for value in (realised,commission,budget,purchased)]]
            self.table.setRowHeight(i,56)
            for j,value in enumerate(values):
                color=COLORS["green"] if j in {2,3} and (realised if j==2 else commission)>=0 else COLORS["red"] if j in {2,3} else None
                self.table.setItem(i,j,table_item(value,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight if j else Qt.AlignmentFlag.AlignVCenter,color))
        self.table.setColumnWidth(0,140); self.table.setColumnWidth(1,95); self.table.setColumnWidth(2,150); self.table.setColumnWidth(3,150); self.table.setColumnWidth(4,165)
        rows=self.db.query("SELECT * FROM vehicles WHERE status='sold' AND sold_date IS NOT NULL ORDER BY sold_date DESC,id DESC")
        groups:dict[str,dict[str,object]]={}
        for row in rows:
            try:
                purchased=date.fromisoformat(str(row["purchased_date"])[:10]); sold=date.fromisoformat(str(row["sold_date"])[:10])
            except (TypeError,ValueError):
                continue
            cost=Decimal(str(row["purchase_price_aed"] or 0)); sale=Decimal(str(row["sold_price_aed"] or 0)); profit=sale-cost; key=vehicle_model_name(row["vehicle_name"]).casefold()
            group=groups.setdefault(key,{"model":vehicle_model_name(row["vehicle_name"]),"count":0,"days":Decimal("0"),"cost":Decimal("0"),"sale":Decimal("0"),"profit":Decimal("0")})
            group["count"]+=1; group["days"]+=Decimal(max(0,(sold-purchased).days)); group["cost"]+=cost; group["sale"]+=sale; group["profit"]+=profit
        ordered=sorted(groups.values(),key=lambda group:(-int(group["count"]),str(group["model"]).casefold()))
        self.performance_table.setRowCount(len(ordered))
        for row_index,group in enumerate(ordered):
            count=int(group["count"]); average_days=group["days"]/count; average_cost=group["cost"]/count; average_sale=group["sale"]/count; average_profit=group["profit"]/count; margin=vehicle_margin_percent(average_profit,average_cost); grade=vehicle_speed_grade(average_days)
            values=[str(group["model"]),str(count),f"{average_days:.1f} days",grade,f"AED {average_cost:,.0f}",f"AED {average_sale:,.0f}",f"{average_profit:+,.0f} AED",f"{margin:.1f}%"]
            self.performance_table.setRowHeight(row_index,52)
            for column,value in enumerate(values):
                color=vehicle_grade_color(grade) if column==3 else COLORS["green"] if column in {6,7} and average_profit>=0 else COLORS["red"] if column in {6,7} else None
                self.performance_table.setItem(row_index,column,table_item(value,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight if column else Qt.AlignmentFlag.AlignVCenter,color))
        for column,width in enumerate([165,65,125,75,145,135,120]): self.performance_table.setColumnWidth(column,width)


class TransactionsPage(Page):
    def __init__(self, db: Database):
        super().__init__(db); self.last_deleted: int | None = None
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 22, 24, 24); layout.setSpacing(14)
        top = QHBoxLayout(); titles = QVBoxLayout(); title = QLabel("Transactions"); title.setObjectName("pageTitle"); titles.addWidget(title); sub = QLabel("Every cash movement, with local receipts and reversible deletion."); sub.setObjectName("muted"); titles.addWidget(sub); top.addLayout(titles); top.addStretch()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search merchant, category or tag…"); self.search.setMaximumWidth(320); self.search.textChanged.connect(self.refresh); top.addWidget(self.search)
        add = QPushButton("＋ Add transaction"); add.setProperty("primary", True); add.clicked.connect(self.add); top.addWidget(add); layout.addLayout(top)
        tools = QHBoxLayout(); self.filter = QComboBox(); self.filter.addItems(["All types", "Highlighted", "Setup costs", "Expenses", "Income", "Essential", "Discretionary", "Credit card"]); self.filter.currentTextChanged.connect(self.refresh); tools.addWidget(self.filter)
        for label, callback in [("Pay credit card", self.pay_card), ("Import CSV", self.import_csv), ("Export CSV", self.export_csv), ("Highlight row", self.toggle_highlight), ("Setup cost", self.toggle_setup_cost), ("Edit", self.edit), ("Delete", self.delete), ("Undo delete", self.undo)]: btn=QPushButton(label); btn.clicked.connect(callback); tools.addWidget(btn)
        tools.addStretch(); self.summary = QLabel(); self.summary.setObjectName("muted"); tools.addWidget(self.summary); layout.addLayout(tools)
        self.table = QTableWidget(0, 8); self.table.setHorizontalHeaderLabels(["DATE", "TYPE", "MERCHANT", "CATEGORY", "METHOD", "FLAGS", "TAGS", "AMOUNT"]); self.table.setItemDelegate(TransactionHighlightDelegate(self.table)); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.doubleClicked.connect(self.edit); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.table,1); self.refresh()

    def filtered_rows(self):
        rows = self.db.transactions(self.search.text().strip(), limit=10000); mode = self.filter.currentText()
        if mode == "Highlighted": rows=[r for r in rows if r["highlighted"]]
        elif mode == "Setup costs": rows=[r for r in rows if r["budget_excluded"]]
        elif mode == "Expenses": rows=[r for r in rows if r["kind"]=="expense"]
        elif mode == "Income": rows=[r for r in rows if r["kind"]=="income"]
        elif mode == "Essential": rows=[r for r in rows if r["essential"]]
        elif mode == "Discretionary": rows=[r for r in rows if not r["essential"] and r["kind"]=="expense"]
        elif mode == "Credit card": rows=[r for r in rows if r["card_effect"]]
        return rows

    def refresh(self) -> None:
        rows=self.filtered_rows(); self.table.setRowCount(len(rows)); total=Decimal("0"); rate=Decimal(self.db.get_setting("gbp_aed_rate","4.928313"))
        for i,row in enumerate(rows):
            self.table.setRowHeight(i,52); self.table.setVerticalHeaderItem(i,QTableWidgetItem(str(row["id"])))
            flags = " · ".join(x for x in ["Setup cost" if row["budget_excluded"] else "", row["credit_card_name"] or "" if row["card_effect"] else "", "Card payment" if row["card_effect"]==-1 else "", "Recurring" if row["recurring"] else "", "Essential" if row["essential"] else "Discretionary", "Deposit" if row["refundable_deposit"] else "", "Receipt" if row["receipt_path"] else ""] if x)
            amount_aed = to_aed(row["amount"],row["currency"],rate)*(1 if row["kind"]=="income" else -1); total += amount_aed
            primary,secondary=dual_amount(amount_aed,rate,2,True)
            values=[row["occurred_at"][:16].replace("T","  "),row["kind"].title(),row["merchant"] or "—",category_label(row["category"]),row["payment_method"],flags,row["tags"],f"{primary}\n{secondary}"]
            for j,value in enumerate(values):
                item=table_item(str(value),Qt.AlignmentFlag.AlignRight if j==7 else None,COLORS["green"] if amount_aed>0 and j==7 else COLORS["text"] if j==7 else None)
                if row["highlighted"]: item.setData(Qt.ItemDataRole.UserRole,True); item.setBackground(QColor("#5a4316")); item.setToolTip("Highlighted transaction"+(f" · {row['notes']}" if row["notes"] else ""))
                self.table.setItem(i,j,item)
        self.table.resizeColumnsToContents(); self.table.horizontalHeader().setStretchLastSection(False); self.table.setColumnWidth(2,max(160,self.table.columnWidth(2))); self.table.setColumnWidth(6,120); self.table.horizontalHeader().setStretchLastSection(True); net_aed,net_gbp=dual_amount(total,rate,2,True); self.summary.setText(f"{len(rows)} transactions  ·  visible net {net_aed} / {net_gbp}")

    def selected_row(self):
        row=self.table.currentRow()
        if row<0: return None
        tx_id=int(self.table.verticalHeaderItem(row).text()); matches=self.db.query("SELECT * FROM transactions WHERE id=?",(tx_id,)); return matches[0] if matches else None
    def add(self) -> None:
        dialog=TransactionDialog(self.db,parent=self)
        if dialog.exec(): self.db.add_transaction(dialog.values()); self.refresh(); self.changed.emit()
    def pay_card(self) -> None:
        if not self.db.query("SELECT id FROM credit_cards WHERE current_balance>0 LIMIT 1"): QMessageBox.information(self,"No card balance","There is no outstanding credit-card balance to pay."); return
        dialog=PayCardDialog(self.db,self)
        if dialog.exec(): self.db.add_transaction(dialog.values()); self.refresh(); self.changed.emit()
    def edit(self) -> None:
        row=self.selected_row()
        if not row: return
        dialog=TransactionDialog(self.db,row,parent=self)
        if dialog.exec(): self.db.update_transaction(row["id"],dialog.values()); self.refresh(); self.changed.emit()
    def delete(self) -> None:
        row=self.selected_row()
        if not row: return
        if QMessageBox.question(self,"Delete transaction",f"Delete {row['merchant'] or 'this transaction'}? You can undo it during this session.")==QMessageBox.StandardButton.Yes: self.db.soft_delete_transaction(row["id"]); self.last_deleted=row["id"]; self.refresh(); self.changed.emit()
    def undo(self) -> None:
        if self.last_deleted: self.db.undo_delete(self.last_deleted); self.last_deleted=None; self.refresh(); self.changed.emit()
        else: QMessageBox.information(self,"Nothing to undo","No transaction has been deleted during this session.")
    def toggle_highlight(self) -> None:
        row=self.selected_row()
        if not row: QMessageBox.information(self,"Select a transaction","Select the transaction you want to highlight first."); return
        self.db.toggle_transaction_highlight(row["id"]); self.refresh(); self.changed.emit()
    def toggle_setup_cost(self) -> None:
        row=self.selected_row()
        if not row: QMessageBox.information(self,"Select a transaction","Select the one-off relocation or setup transaction first."); return
        self.db.execute("UPDATE transactions SET budget_excluded=? WHERE id=?",(0 if row["budget_excluded"] else 1,row["id"])); self.refresh(); self.changed.emit()
    def import_csv(self) -> None:
        path,_=QFileDialog.getOpenFileName(self,"Import transactions","","CSV files (*.csv)")
        if path: imported,skipped=self.db.import_csv(Path(path)); QMessageBox.information(self,"Import complete",f"Imported {imported}; skipped {skipped} duplicates or invalid rows."); self.refresh(); self.changed.emit()
    def export_csv(self) -> None:
        path,_=QFileDialog.getSaveFileName(self,"Export transactions",f"DXB-RUNWAY-{date.today()}.csv","CSV files (*.csv)")
        if path: self.db.export_csv(Path(path)); QMessageBox.information(self,"Export complete",f"Saved locally to:\n{path}")


class DebtPage(Page):
    def __init__(self,db:Database):
        super().__init__(db); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); self.layout=QVBoxLayout(content); self.layout.setContentsMargins(24,22,24,28); self.layout.setSpacing(16)
        self.layout.addWidget(SectionHeader("Debt control", "Credit is a liability and never appears as cash or net wealth.")); self.cards=QVBoxLayout(); self.layout.addLayout(self.cards); outer.addWidget(page_scroll(content)); self.refresh()
    def refresh(self)->None:
        clear_layout(self.cards); rows=self.db.query("SELECT * FROM credit_cards ORDER BY id")
        if not rows:
            empty=Card(); lay=QVBoxLayout(empty); lay.addWidget(QLabel("No credit cards yet")); add=QPushButton("Add first card"); add.setProperty("primary",True); add.clicked.connect(self.add_card); lay.addWidget(add); self.cards.addWidget(empty); return
        for row in rows:
            utilisation=card_utilisation(row["current_balance"],row["credit_limit"]); status,color=utilisation_status(utilisation); interest=estimate_monthly_interest(row["current_balance"],row["apr"]); months=repayment_months(row["current_balance"],row["apr"],max(row["minimum_payment"],1))
            rate=Decimal(self.db.get_setting("gbp_aed_rate","4.928313")); balance_aed=to_aed(row["current_balance"],row["currency"],rate); limit_aed=to_aed(row["credit_limit"],row["currency"],rate); available_aed=max(Decimal("0"),limit_aed-balance_aed); interest_aed=to_aed(interest,row["currency"],rate)
            card=Card(); root=QVBoxLayout(card); root.setContentsMargins(20,18,20,18)
            top=QHBoxLayout(); name=QLabel(row["name"]); name.setStyleSheet("font-size:18px;font-weight:700"); top.addWidget(name); top.addStretch(); badge=QLabel(f" {status} "); badge.setStyleSheet(f"color:{color};background:{color}22;border:1px solid {color}66;border-radius:6px;padding:5px 9px;font-weight:800"); top.addWidget(badge)
            edit=QPushButton("Edit"); edit.clicked.connect(lambda _checked=False, card_id=row["id"]: self.edit_card(card_id)); top.addWidget(edit)
            delete=QPushButton("Delete"); delete.clicked.connect(lambda _checked=False, card_id=row["id"]: self.delete_card(card_id)); top.addWidget(delete); root.addLayout(top)
            metrics=QGridLayout(); data=[("Current balance",*dual_amount(balance_aed,rate,2)),("Available credit",*dual_amount(available_aed,rate,2)),("Credit limit",*dual_amount(limit_aed,rate,2)),("Utilisation",f"{utilisation}%",f"Card currency: {row['currency']}"),("Estimated monthly interest",*dual_amount(interest_aed,rate,2)),("Minimum-payment forecast",f"{months} months" if months is not None else "Payment too low","At the current minimum"),("Statement / due",f"Day {row['statement_day']} / {row['due_day']}","Statement / payment"),("Promotional end",row['promo_end'] or "None","")]
            for i,(label,value,detail) in enumerate(data): box=MetricCard(label,value,detail,accent=color if label in {"Current balance","Utilisation"} else COLORS["text"]); metrics.addWidget(box,i//4,i%4)
            root.addLayout(metrics); progress=QProgressBar(); progress.setRange(0,100); progress.setValue(min(100,int(utilisation))); progress.setStyleSheet(f"QProgressBar::chunk{{background:{color};border-radius:4px}}"); root.addWidget(progress)
            guaranteed=Decimal(self.db.get_setting("salary_aed","6000")); debt_aed=balance_aed; danger=debt_aed>guaranteed
            warn=QLabel("DEBT DANGER · Current balance exceeds one month of guaranteed salary." if danger else "Debt coverage is within one month of guaranteed salary; keep monitoring utilisation."); warn.setWordWrap(True); warn.setStyleSheet(f"color:{COLORS['red'] if danger else COLORS['muted']};font-weight:{'700' if danger else '400'}"); root.addWidget(warn); self.cards.addWidget(card)
        add=QPushButton("＋ Add card"); add.clicked.connect(self.add_card); self.cards.addWidget(add); self.cards.addStretch()
    def add_card(self)->None:
        self.card_dialog()
    def edit_card(self, card_id:int)->None:
        rows=self.db.query("SELECT * FROM credit_cards WHERE id=?",(card_id,))
        if rows: self.card_dialog(rows[0])
    def card_dialog(self, row=None)->None:
        dialog=QDialog(self); dialog.setWindowTitle("Edit credit card" if row else "Add credit card"); form=QFormLayout(dialog)
        name=QLineEdit(row["name"] if row else "UK relocation card"); currency=QComboBox(); currency.addItems(["GBP","AED"]); currency.setCurrentText(row["currency"] if row else "GBP")
        limit=MoneyBox(); limit.setValue(float(row["credit_limit"]) if row else 5000)
        apr=MoneyBox(maximum=100); apr.setValue(float(row["apr"]) if row else 24.9); minimum=MoneyBox(); minimum.setValue(float(row["minimum_payment"]) if row else 50)
        if row:
            name.setReadOnly(True); currency.setEnabled(False); apr.setEnabled(False); minimum.setEnabled(False)
            balance=QLabel(f"{row['currency']} {row['current_balance']:,.2f} · updated only by transactions"); balance.setObjectName("muted")
            form.addRow("Card",name); form.addRow("Currency",currency); form.addRow("Card limit",limit); form.addRow("Current balance",balance)
        else:
            form.addRow("Card name",name); form.addRow("Currency",currency); form.addRow("Card limit",limit); form.addRow("APR %",apr); form.addRow("Minimum payment",minimum)
        save=QPushButton("Save changes" if row else "Save card"); save.setProperty("primary",True)
        def submit()->None:
            self.db.save_credit_card({"name":name.text(),"currency":currency.currentText(),"credit_limit":limit.value(),"minimum_payment":minimum.value(),"apr":apr.value()},row["id"] if row else None); dialog.accept()
        save.clicked.connect(submit); form.addRow(save)
        if dialog.exec(): self.refresh(); self.changed.emit()
    def delete_card(self, card_id:int)->None:
        rows=self.db.query("SELECT name FROM credit_cards WHERE id=?",(card_id,))
        if not rows: return
        if QMessageBox.question(self,"Delete credit card",f"Permanently delete {rows[0]['name']}? This will not delete any transactions.")==QMessageBox.StandardButton.Yes:
            self.db.delete_credit_card(card_id); self.refresh(); self.changed.emit()


class EarningsPage(Page):
    def __init__(self,db:Database):
        super().__init__(db); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); layout=QVBoxLayout(content); layout.setContentsMargins(24,22,24,28); layout.setSpacing(16); layout.addWidget(SectionHeader("Salary & commission engine","Alba Motors estimates. Commission is scheduled two months after the month earned and excluded from current spendable cash."))
        input_card=Card(); grid=QGridLayout(input_card); grid.setContentsMargins(18,16,18,16); self.year=QSpinBox(); self.year.setRange(2026,2100); self.year.setValue(date.today().year); self.month=QComboBox(); self.month.addItems(list(calendar.month_name)[1:]); self.month.setCurrentIndex(date.today().month-1); self.budget=MoneyBox(); self.budget.setValue(3_000_000); self.profit=MoneyBox(); self.profit.setValue(285_000); self.margin=MoneyBox(); self.margin.setValue(24_700); self.margin_currency=QComboBox(); self.margin_currency.addItems(["AED","GBP"]); self.deductions=MoneyBox(); calculate=QPushButton("Calculate estimate"); calculate.setProperty("primary",True); calculate.clicked.connect(self.calculate)
        inputs=[("YEAR",self.year),("MONTH",self.month),("PURCHASING BUDGET · AED",self.budget),("ELIGIBLE PROFIT · AED",self.profit),("AVERAGE MARGIN",self.margin),("MARGIN CURRENCY",self.margin_currency),("KPI DEDUCTIONS · AED",self.deductions)]
        for i,(label,widget) in enumerate(inputs): box=QVBoxLayout(); lab=QLabel(label); lab.setObjectName("eyebrow"); box.addWidget(lab); box.addWidget(widget); grid.addLayout(box,i//4,(i%4)*2,1,2)
        grid.addWidget(calculate,2,6,1,2); layout.addWidget(input_card)
        self.result=Card(); self.result_layout=QVBoxLayout(self.result); self.result_layout.setContentsMargins(20,18,20,18); layout.addWidget(self.result)
        layout.addWidget(SectionHeader("Earned vs received","Only received rows can enter the cash balance.")); self.history=QTableWidget(0,7); self.history.setHorizontalHeaderLabels(["MONTH","BUDGET","PROFIT","TIER","SALARY","COMMISSION","PAYMENT DATE"]); self.history.verticalHeader().hide(); self.history.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.history); outer.addWidget(page_scroll(content)); self.calculate(); self.refresh()
    def calculate(self)->None:
        rate=Decimal(self.db.get_setting("gbp_aed_rate","4.928313")); margin=to_aed(self.margin.value(),self.margin_currency.currentText(),rate); result=calculate_earnings(year=self.year.value(),month=self.month.currentIndex()+1,budget_aed=self.budget.value(),eligible_profit_aed=self.profit.value(),average_margin_aed=margin,deductions_aed=self.deductions.value()); clear_layout(self.result_layout)
        top=QHBoxLayout(); tier=QLabel(result.tier.value.upper()); tier.setStyleSheet(f"font-size:28px;font-weight:800;color:{COLORS['green'] if result.tier!=CommissionTier.BASELINE else COLORS['cyan']}"); top.addWidget(tier); top.addStretch(); estimate=QLabel("ESTIMATE"); estimate.setObjectName("eyebrow"); top.addWidget(estimate); self.result_layout.addLayout(top)
        grid=QGridLayout(); metrics=[("Basic salary",*dual_amount(result.salary_aed,rate)),("Commission",*dual_amount(result.commission_aed,rate)),("Total earned",*dual_amount(result.total_earned_aed,rate)),("Paid",result.payment_date.strftime("%d %b %Y"),"Commission receipt date"),("Rate",f"{result.rate*100:g}%","Applied to full eligible profit"),("Next tier",result.next_tier.value if result.next_tier else "Highest tier","Estimate"),("Distance",*dual_amount(result.distance_to_next_aed,rate)),("Cars needed",str(result.cars_to_next_tier),"At the stated average margin"),("Incremental value",*dual_amount(result.incremental_value_aed,rate))]
        for i,(label,value,detail) in enumerate(metrics): grid.addWidget(MetricCard(label,value,detail,accent=COLORS["green"] if label in {"Commission","Total earned","Incremental value"} else COLORS["text"]),i//5,i%5)
        self.result_layout.addLayout(grid); save=QPushButton("Save month as earned (pending receipt)"); save.clicked.connect(lambda:self.save(result)); self.result_layout.addWidget(save)
    def save(self,result)->None:
        self.db.execute("INSERT INTO earnings(year,month,purchasing_budget_aed,eligible_profit_aed,average_margin_aed,deductions_aed,tier,salary_aed,commission_aed,earned_date,payment_date,received) VALUES (?,?,?,?,?,?,?,?,?,?,?,0) ON CONFLICT(year,month) DO UPDATE SET purchasing_budget_aed=excluded.purchasing_budget_aed,eligible_profit_aed=excluded.eligible_profit_aed,average_margin_aed=excluded.average_margin_aed,deductions_aed=excluded.deductions_aed,tier=excluded.tier,salary_aed=excluded.salary_aed,commission_aed=excluded.commission_aed,payment_date=excluded.payment_date",(self.year.value(),self.month.currentIndex()+1,self.budget.value(),self.profit.value(),self.margin.value(),self.deductions.value(),result.tier.value,float(result.salary_aed),float(result.commission_aed),date(self.year.value(),self.month.currentIndex()+1,calendar.monthrange(self.year.value(),self.month.currentIndex()+1)[1]).isoformat(),result.payment_date.isoformat())); self.refresh(); self.changed.emit(); QMessageBox.information(self,"Saved","Earnings saved as pending. They have not been added to spendable cash.")
    def refresh(self)->None:
        rows=self.db.query("SELECT * FROM earnings ORDER BY year DESC,month DESC"); self.history.setRowCount(len(rows))
        for i,row in enumerate(rows):
            rate=Decimal(self.db.get_setting("gbp_aed_rate","4.928313")); dual=lambda value: f"{dual_amount(value,rate)[0]}\n{dual_amount(value,rate)[1]}"; values=[f"{calendar.month_abbr[row['month']]} {row['year']}",dual(row['purchasing_budget_aed']),dual(row['eligible_profit_aed']),row['tier'],dual(row['salary_aed']),dual(row['commission_aed']),row['payment_date']+(" · RECEIVED" if row['received'] else " · PENDING")]
            for j,value in enumerate(values): self.history.setItem(i,j,table_item(str(value),color=COLORS["green"] if "RECEIVED" in str(value) else COLORS["purple"] if "PENDING" in str(value) else None))
        self.history.resizeColumnsToContents(); self.history.horizontalHeader().setStretchLastSection(True)


class ScenarioPage(Page):
    PRESETS = {
        "No commission": {"tier": "No commission"}, "Baseline commission": {"tier": "Baseline"}, "Tier 3": {"tier": "Tier 3"},
        "Tier 2": {"tier": "Tier 2"}, "Tier 1": {"tier": "Tier 1"}, "Unexpected return to the UK": {"other": 3500},
        "One month without salary": {"salary": 0}, "Rent increases by 20%": {"rent_factor": 1.2},
        "Carpooling": {"transport_factor": .55}, "Buying / financing a car": {"other": 1800},
    }
    def __init__(self, db: Database):
        super().__init__(db); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); root=QVBoxLayout(content); root.setContentsMargins(24,22,24,28); root.setSpacing(16)
        root.addWidget(SectionHeader("Scenario lab","Stress-test the plan instantly. Every result remains an estimate and pending income stays separate from starting cash."))
        presets=QHBoxLayout(); presets.addWidget(QLabel("INSTANT SCENARIO")); self.preset=QComboBox(); self.preset.addItems(self.PRESETS); self.preset.currentTextChanged.connect(self.apply_preset); presets.addWidget(self.preset,1); compare=QPushButton("Pin as comparison"); compare.clicked.connect(self.pin); presets.addWidget(compare); root.addLayout(presets)
        body=QHBoxLayout(); inputs=Card(); form=QFormLayout(inputs); form.setContentsMargins(18,18,18,18); form.setSpacing(10); settings=db.all_settings()
        self.controls={}
        defaults=[("budget","Purchasing budget",3_000_000), ("cars","Cars sold",12), ("margin","Profit / vehicle",24_700), ("rent","Rent",float(settings.get("rent_aed",4500))), ("transport","Transport",float(settings.get("transport_aed",2000))), ("food","Food",float(settings.get("food_aed",1250))), ("other","Other expenses",650), ("repayment","Card repayment",300), ("emergency","Emergency fund",float(settings.get("emergency_fund_aed",3000))), ("cash","Starting cash",float(settings.get("uk_cash_gbp",2000))*float(settings.get("gbp_aed_rate",4.928313)))]
        for key,label,value in defaults:
            box=MoneyBox(); box.setValue(value); box.valueChanged.connect(self.calculate); self.controls[key]=box; form.addRow(label+" · AED" if key not in {"cars"} else label,box)
        self.salary=MoneyBox(); self.salary.setValue(float(settings.get("salary_aed",6000))); self.salary.valueChanged.connect(self.calculate); form.addRow("Salary · AED",self.salary)
        self.tier=QComboBox(); self.tier.addItems(["No commission","Baseline","Tier 3","Tier 2","Tier 1"]); self.tier.currentTextChanged.connect(self.calculate); form.addRow("Commission tier",self.tier)
        self.rate=MoneyBox(decimals=6); self.rate.setValue(float(settings.get("gbp_aed_rate",4.928313))); self.rate.valueChanged.connect(self.calculate); form.addRow("GBP / AED",self.rate); body.addWidget(inputs,1)
        result=QVBoxLayout(); self.hero=MetricCard("Monthly surplus / deficit","—"); result.addWidget(self.hero); self.metrics={}; grid=QGridLayout()
        for i,(key,label) in enumerate([("runway","Cash runway"),("out","Cash-out date"),("m3","Savings · 3m"),("m6","Savings · 6m"),("m12","Savings · 12m"),("m24","Savings · 24m"),("debt","Debt · 12m"),("fund","Emergency fund")]): card=MetricCard(label); self.metrics[key]=card; grid.addWidget(card,i//2,i%2)
        result.addLayout(grid); self.delta=QLabel("No comparison pinned"); self.delta.setObjectName("muted"); result.addWidget(self.delta); body.addLayout(result,2); root.addLayout(body)
        self.chart_box=QVBoxLayout(); root.addLayout(self.chart_box); outer.addWidget(page_scroll(content)); self.baseline=None; self.calculate()
    def commission(self)->float:
        profit=self.controls["cars"].value()*self.controls["margin"].value(); return profit*{"No commission":0,"Baseline":.04,"Tier 3":.05,"Tier 2":.065,"Tier 1":.08}[self.tier.currentText()]
    def calculate(self)->None:
        expenses=sum(self.controls[k].value() for k in ("rent","transport","food","other","repayment")); income=self.salary.value()+self.commission(); card=self.db.query("SELECT current_balance,apr FROM credit_cards ORDER BY id LIMIT 1"); balance=float(to_aed(card[0]["current_balance"],"GBP",self.rate.value())) if card else 0; apr=card[0]["apr"] if card else 0
        result=simulate_scenario(start_date=date.today(),starting_cash=self.controls["cash"].value(),emergency_fund=self.controls["emergency"].value(),monthly_income=income,monthly_expenses=expenses,card_balance=balance,card_apr=apr,repayment=self.controls["repayment"].value()); self.current=result; color=COLORS["green"] if result.monthly_surplus_aed>=0 else COLORS["red"]
        primary,secondary=dual_amount(result.monthly_surplus_aed,self.rate.value(),signed=True); self.hero.set_value(primary,f"{secondary} · Income AED {income:,.0f} · Expenses AED {expenses:,.0f}",color)
        values={"runway":("999+ days" if result.runway_days>=999 else f"{result.runway_days} days","Guaranteed-cash basis"),"out":(result.cash_out_date.strftime("%d %b %Y") if result.cash_out_date else "No cash-out","Estimated"),"m3":dual_amount(result.savings_3m,self.rate.value()),"m6":dual_amount(result.savings_6m,self.rate.value()),"m12":dual_amount(result.savings_12m,self.rate.value()),"m24":dual_amount(result.savings_24m,self.rate.value()),"debt":dual_amount(result.debt_12m,self.rate.value()),"fund":("BREACHED" if result.emergency_breached else "PROTECTED",f"AED {self.controls['emergency'].value():,.0f} threshold")}
        for key,(value,detail) in values.items(): self.metrics[key].set_value(value,detail,accent=COLORS["red"] if key=="fund" and result.emergency_breached else COLORS["green"] if key=="fund" else None)
        clear_layout(self.chart_box); values=[self.controls["cash"].value()+float(result.monthly_surplus_aed)*i for i in range(25)]; self.chart_box.addWidget(line_chart("Projected savings · 24 months",values,color=color))
        if self.baseline:
            monthly=dual_amount(result.monthly_surplus_aed-self.baseline.monthly_surplus_aed,self.rate.value(),signed=True); annual=dual_amount(result.savings_12m-self.baseline.savings_12m,self.rate.value(),signed=True); self.delta.setText(f"Versus pinned: {monthly[0]} / {monthly[1]} monthly · {annual[0]} / {annual[1]} after 12 months")
    def pin(self)->None: self.baseline=self.current; self.delta.setText("Comparison pinned. Adjust inputs to see the difference.")
    def apply_preset(self,name:str)->None:
        settings=self.db.all_settings(); self.salary.setValue(float(settings.get("salary_aed",6000))); self.controls["rent"].setValue(float(settings.get("rent_aed",4500))); self.controls["transport"].setValue(float(settings.get("transport_aed",2000))); self.controls["other"].setValue(650)
        preset=self.PRESETS[name]
        if "tier" in preset:self.tier.setCurrentText(preset["tier"])
        if "salary" in preset:self.salary.setValue(preset["salary"])
        if "rent_factor" in preset:self.controls["rent"].setValue(self.controls["rent"].value()*preset["rent_factor"])
        if "transport_factor" in preset:self.controls["transport"].setValue(self.controls["transport"].value()*preset["transport_factor"])
        if "other" in preset:self.controls["other"].setValue(self.controls["other"].value()+preset["other"])
        self.calculate()


class BudgetsPage(Page):
    TRACKED_CATEGORIES=("Groceries","Transport","Restaurants","Phone","Utilities","Subscriptions","Clothing","Entertainment","Miscellaneous")

    def __init__(self,db:Database):
        super().__init__(db); self.month_date=QDate.currentDate(); self.actual={}; self.rate=Decimal("1"); self.category_cards={}
        outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); root=QVBoxLayout(content); root.setContentsMargins(24,22,24,28); root.setSpacing(16)
        top=QHBoxLayout(); top.addWidget(SectionHeader("Monthly payments","See what is due, what Transactions says you have spent, and exactly what remains.")); top.addStretch()
        previous=QPushButton("‹"); previous.setObjectName("calendarNav"); previous.setFixedSize(40,40); previous.clicked.connect(lambda:self.change_month(-1)); top.addWidget(previous)
        self.month_title=QLabel(); self.month_title.setObjectName("budgetMonth"); top.addWidget(self.month_title)
        following=QPushButton("›"); following.setObjectName("calendarNav"); following.setFixedSize(40,40); following.clicked.connect(lambda:self.change_month(1)); top.addWidget(following); root.addLayout(top)

        hero=Card(); hero_l=QHBoxLayout(hero); hero_l.setContentsMargins(22,18,22,18); hero_l.setSpacing(24)
        copy=QVBoxLayout(); eyebrow=QLabel("LEFT TO SPEND THIS MONTH"); eyebrow.setObjectName("eyebrow"); copy.addWidget(eyebrow); self.hero_value=QLabel(); self.hero_value.setObjectName("budgetHero"); copy.addWidget(self.hero_value); self.hero_detail=QLabel(); self.hero_detail.setObjectName("muted"); copy.addWidget(self.hero_detail); hero_l.addLayout(copy,1)
        progress_box=QVBoxLayout(); self.hero_percent=QLabel(); self.hero_percent.setAlignment(Qt.AlignmentFlag.AlignRight); self.hero_percent.setStyleSheet(f"color:{COLORS['cyan']};font-size:18px;font-weight:750"); progress_box.addWidget(self.hero_percent); self.hero_progress=QProgressBar(); self.hero_progress.setFixedWidth(300); progress_box.addWidget(self.hero_progress); hero_l.addLayout(progress_box); root.addWidget(hero)

        root.addWidget(SectionHeader("Rent payment","Set the amount and due date once. When you log the payment, Transactions updates this page automatically."))
        rent=Card(); rent_l=QHBoxLayout(rent); rent_l.setContentsMargins(18,17,18,17); rent_l.setSpacing(18)
        rent_info=QVBoxLayout(); rent_title=QLabel("Home rent"); rent_title.setStyleSheet("font-size:17px;font-weight:730"); rent_info.addWidget(rent_title); self.rent_status=QLabel(); rent_info.addWidget(self.rent_status); self.rent_spent=QLabel(); self.rent_spent.setObjectName("muted"); rent_info.addWidget(self.rent_spent); rent_l.addLayout(rent_info,1)
        rent_amount=QVBoxLayout(); amount_label=QLabel("MONTHLY RENT"); amount_label.setObjectName("eyebrow"); rent_amount.addWidget(amount_label); self.rent_plan=MoneyBox(maximum=5_000_000); self.rent_plan.setSuffix(" AED"); self.rent_plan.setMinimumWidth(190); self.rent_plan.valueChanged.connect(self.update_totals); rent_amount.addWidget(self.rent_plan); rent_l.addLayout(rent_amount)
        due_box=QVBoxLayout(); due_label=QLabel("DUE DATE"); due_label.setObjectName("eyebrow"); due_box.addWidget(due_label); self.rent_due=QDateEdit(); self.rent_due.setCalendarPopup(True); self.rent_due.setDisplayFormat("ddd, d MMMM"); self.rent_due.setMinimumWidth(190); self.rent_due.dateChanged.connect(self.update_rent_display); due_box.addWidget(self.rent_due); rent_l.addLayout(due_box)
        log=QPushButton("Log rent payment"); log.setProperty("primary",True); log.clicked.connect(self.log_rent); rent_l.addWidget(log); root.addWidget(rent)

        root.addWidget(SectionHeader("Everyday spending","Simple monthly limits for the categories you use most. Spending is read directly from Transactions."))
        self.grid=QGridLayout(); self.grid.setSpacing(12)
        categories={row["name"]:row for row in self.db.query("SELECT * FROM categories WHERE kind='expense'")}
        for index,name in enumerate(self.TRACKED_CATEGORIES):
            category=categories.get(name)
            if not category: continue
            card=BudgetCategoryCard(name,category["color"]); card.plan.valueChanged.connect(self.update_totals); self.category_cards[category["id"]]=card; self.grid.addWidget(card,index//3,index%3)
        root.addLayout(self.grid)
        note=QLabel("One-off setup costs, deposits, relocation and card repayments stay visible in Transactions but do not reduce these everyday limits."); note.setObjectName("muted"); note.setWordWrap(True); root.addWidget(note)
        save=QPushButton("Save monthly plan"); save.setProperty("primary",True); save.clicked.connect(self.save); root.addWidget(save)
        outer.addWidget(page_scroll(content)); self.refresh()

    def change_month(self,offset:int)->None:
        self.month_date=self.month_date.addMonths(offset); self.refresh()

    def refresh(self)->None:
        month=self.month_date.toString("yyyy-MM"); self.month_title.setText(self.month_date.toString("MMMM yyyy")); self.rate=Decimal(self.db.get_setting("gbp_aed_rate","4.928313")); self.actual={}
        for row in self.db.transactions(month=month,limit=100000):
            if row["kind"]=="expense" and not row["refundable_deposit"] and not row["budget_excluded"]:
                if row["category"]=="Accommodation" and not row["recurring"] and "rent" not in row["merchant"].lower(): continue
                self.actual[row["category_id"]]=self.actual.get(row["category_id"],Decimal("0"))+to_aed(row["amount"],row["currency"],self.rate)
        plans={row["category_id"]:row for row in self.db.query("SELECT * FROM budgets WHERE month=?",(month,))}; categories={row["id"]:row for row in self.db.query("SELECT * FROM categories WHERE kind='expense'")}
        accommodation=next(row for row in categories.values() if row["name"]=="Accommodation"); self.accommodation_id=accommodation["id"]
        rent_row=plans.get(self.accommodation_id); rent_default=float(self.db.get_setting("rent_aed","4500")); due_default=QDate(self.month_date.year(),self.month_date.month(),1)
        self.rent_plan.blockSignals(True); self.rent_plan.setValue(rent_row["planned_aed"] if rent_row else rent_default); self.rent_plan.blockSignals(False)
        self.rent_due.blockSignals(True); self.rent_due.setDate(QDate.fromString(rent_row["due_date"],"yyyy-MM-dd") if rent_row and rent_row["due_date"] else due_default); self.rent_due.blockSignals(False)
        defaults={"Transport":float(self.db.get_setting("transport_aed","2000")),"Groceries":float(self.db.get_setting("food_aed","1250"))}
        for category_id,card in self.category_cards.items():
            row=plans.get(category_id); category=categories[category_id]; card.set_data(row["planned_aed"] if row else defaults.get(category["name"],category["monthly_limit_aed"]),self.actual.get(category_id,Decimal("0")),self.rate)
        self.update_totals()

    def update_rent_display(self)->None:
        if not hasattr(self,"accommodation_id"): return
        planned=Decimal(str(self.rent_plan.value())); spent=self.actual.get(self.accommodation_id,Decimal("0")); remaining=planned-spent; paid=planned>0 and remaining<=0
        due=self.rent_due.date(); days=QDate.currentDate().daysTo(due); status="PAID" if paid else "DUE TODAY" if days==0 else f"DUE IN {days} DAYS" if days>0 else f"{abs(days)} DAYS OVERDUE"
        color=COLORS["green"] if paid else COLORS["amber"] if days>=0 else COLORS["red"]
        self.rent_status.setText(status); self.rent_status.setStyleSheet(f"color:{color};font-size:12px;font-weight:750")
        spent_aed,spent_gbp=dual_amount(spent,self.rate); left_aed,left_gbp=dual_amount(remaining,self.rate,signed=True); self.rent_spent.setText(f"Paid {spent_aed} / {spent_gbp}  ·  {left_aed} / {left_gbp} remaining")

    def update_totals(self)->None:
        if not hasattr(self,"accommodation_id"): return
        for card in self.category_cards.values(): card.update_display()
        planned=Decimal(str(self.rent_plan.value()))+sum((Decimal(str(card.plan.value())) for card in self.category_cards.values()),Decimal("0")); tracked={self.accommodation_id,*self.category_cards.keys()}; spent=sum((self.actual.get(category_id,Decimal("0")) for category_id in tracked),Decimal("0")); remaining=planned-spent; used=min(100,int(spent/planned*100)) if planned else (100 if spent else 0)
        left_aed,left_gbp=dual_amount(remaining,self.rate,signed=True); spent_aed,spent_gbp=dual_amount(spent,self.rate); plan_aed,plan_gbp=dual_amount(planned,self.rate)
        self.hero_value.setText(f"{left_aed}  /  {left_gbp}"); self.hero_value.setStyleSheet(f"color:{COLORS['red'] if remaining<0 else COLORS['green']}")
        self.hero_detail.setText(f"Spent {spent_aed} / {spent_gbp} from a {plan_aed} / {plan_gbp} monthly plan")
        self.hero_percent.setText(f"{used}% used"); self.hero_progress.setValue(used); self.update_rent_display()

    def save(self)->None:
        month=self.month_date.toString("yyyy-MM"); values=[(self.accommodation_id,self.rent_plan.value(),self.rent_due.date().toString("yyyy-MM-dd"))]+[(category_id,card.plan.value(),None) for category_id,card in self.category_cards.items()]
        self.db.execute("DELETE FROM budgets WHERE month=?",(month,))
        for category_id,planned,due_date in values:
            self.db.execute("INSERT INTO budgets(month,category_id,planned_aed,rollover,due_date) VALUES (?,?,?,0,?) ON CONFLICT(month,category_id) DO UPDATE SET planned_aed=excluded.planned_aed,due_date=excluded.due_date",(month,category_id,planned,due_date))
        self.db.set_setting("rent_aed",self.rent_plan.value())
        for category_id,card in self.category_cards.items():
            if card.name=="Transport": self.db.set_setting("transport_aed",card.plan.value())
            if card.name=="Groceries": self.db.set_setting("food_aed",card.plan.value())
        QMessageBox.information(self,"Plan saved",f"Your {self.month_date.toString('MMMM yyyy')} payment plan is saved. Rent will appear in Calendar on {self.rent_due.date().toString('d MMMM')}."); self.refresh(); self.changed.emit()

    def log_rent(self)->None:
        dialog=TransactionDialog(self.db,parent=self); dialog.amount.setValue(self.rent_plan.value()); dialog.currency.setCurrentText("AED"); dialog.when.setDate(QDate.currentDate()); dialog.category.setCurrentIndex(dialog.category.findData(self.accommodation_id)); dialog.merchant.setText("Rent"); dialog.payment.setCurrentText("Bank transfer"); dialog.recurring.setChecked(True); dialog.essential.setChecked(True)
        if dialog.exec(): self.db.add_transaction(dialog.values()); self.refresh(); self.changed.emit()


class CalendarPage(Page):
    def __init__(self,db:Database):
        super().__init__(db)
        root=QVBoxLayout(self); root.setContentsMargins(24,22,24,24); root.setSpacing(16)
        root.addWidget(SectionHeader("Financial calendar","Your money timeline, at a glance. Scroll gently or use the arrows to move one month at a time."))
        body=QHBoxLayout(); body.setSpacing(16)

        calendar_card=Card(); calendar_l=QVBoxLayout(calendar_card); calendar_l.setContentsMargins(18,16,18,18); calendar_l.setSpacing(12)
        navigation=QHBoxLayout(); navigation.setSpacing(8)
        previous=QPushButton("‹"); previous.setObjectName("calendarNav"); previous.setFixedSize(40,40); previous.setToolTip("Previous month"); previous.clicked.connect(self.previous_month); navigation.addWidget(previous)
        self.month_title=QLabel(); self.month_title.setObjectName("calendarMonth"); navigation.addWidget(self.month_title)
        navigation.addStretch()
        today=QPushButton("Today"); today.setObjectName("calendarToday"); today.clicked.connect(self.go_today); navigation.addWidget(today)
        following=QPushButton("›"); following.setObjectName("calendarNav"); following.setFixedSize(40,40); following.setToolTip("Next month"); following.clicked.connect(self.next_month); navigation.addWidget(following)
        calendar_l.addLayout(navigation)

        self.calendar=PlayfulCalendar(); self.calendar.selectionChanged.connect(self.refresh_events); self.calendar.currentPageChanged.connect(self.update_month_title); calendar_l.addWidget(self.calendar,1)
        legend=QHBoxLayout(); legend.setSpacing(14); legend.addStretch()
        for label,color in [("Salary",COLORS["green"]),("Commission",COLORS["purple"]),("Inspection",COLORS["cyan"]),("Bills",COLORS["amber"]),("Cards",COLORS["red"]),("Reminder",COLORS["cyan"])]:
            item=QLabel(f"<span style='color:{color};font-size:16px'>●</span>&nbsp; {label}"); item.setObjectName("muted"); legend.addWidget(item)
        legend.addStretch(); calendar_l.addLayout(legend)
        body.addWidget(calendar_card,2)

        side=Card(); side.setMinimumWidth(310); side.setMaximumWidth(410); side_l=QVBoxLayout(side); side_l.setContentsMargins(20,20,20,20); side_l.setSpacing(12)
        selected_label=QLabel("SELECTED DAY"); selected_label.setObjectName("eyebrow"); side_l.addWidget(selected_label)
        self.day=QLabel(); self.day.setObjectName("calendarDay"); self.day.setWordWrap(True); side_l.addWidget(self.day)
        self.day_hint=QLabel("Everything due on this date appears here."); self.day_hint.setObjectName("muted"); self.day_hint.setWordWrap(True); side_l.addWidget(self.day_hint)
        divider=QFrame(); divider.setFrameShape(QFrame.Shape.HLine); divider.setObjectName("calendarDivider"); side_l.addWidget(divider)
        self.events=QVBoxLayout(); self.events.setSpacing(10); side_l.addLayout(self.events); side_l.addStretch()
        add=QPushButton("＋  Add reminder"); add.setProperty("primary",True); add.clicked.connect(self.add); side_l.addWidget(add)
        body.addWidget(side,1); root.addLayout(body,1)
        self.update_month_title(self.calendar.yearShown(),self.calendar.monthShown()); self.refresh()

    def previous_month(self)->None:
        self.calendar.showPreviousMonth()

    def next_month(self)->None:
        self.calendar.showNextMonth()

    def go_today(self)->None:
        self.calendar.setSelectedDate(QDate.currentDate()); self.calendar.showToday(); self.refresh_events()

    def update_month_title(self,year:int,month:int)->None:
        self.month_title.setText(QDate(year,month,1).toString("MMMM yyyy"))

    def inspection_events(self,on_date:str|None=None):
        where=" AND inspection_date=?" if on_date else ""
        params=(on_date,) if on_date else ()
        return self.db.query(
            "SELECT customer_name || ' · Vehicle inspection' title,inspection_date event_date,'inspection' event_type,"
            "CASE WHEN vehicle_age_years BETWEEN 2018 AND 2026 THEN vehicle_age_years ELSE MAX(2018,MIN(2026,2026-vehicle_age_years)) END || ' ' || vehicle_name || ' · phone ••••• ' || phone_last5 notes,"
            "0 completed,id FROM customer_contacts WHERE pipeline_stage='inspection' AND status='active' AND inspection_date IS NOT NULL"+where,
            params,
        )

    def refresh(self)->None:
        rows=self.db.query("SELECT * FROM reminders WHERE completed=0")+self.db.query("SELECT 'Commission payment' title,payment_date event_date,'commission' event_type,'' notes,0 completed,id FROM earnings WHERE received=0")+self.db.query("SELECT c.name || ' due' title,b.due_date event_date,'rent' event_type,'AED ' || printf('%,.2f',b.planned_aed) notes,0 completed,b.id FROM budgets b JOIN categories c ON c.id=b.category_id WHERE b.due_date IS NOT NULL AND b.planned_aed>0")+self.inspection_events()
        colors={"salary":COLORS["green"],"commission":COLORS["purple"],"inspection":COLORS["cyan"],"rent":COLORS["amber"],"card":COLORS["red"],"subscription":COLORS["cyan"]}
        event_colors={}
        for row in rows:
            qdate=QDate.fromString(row["event_date"],"yyyy-MM-dd")
            event_colors.setdefault(qdate,[]).append(colors.get(row["event_type"],COLORS["cyan"]))
        self.calendar.set_event_colors(event_colors)
        self.refresh_events()

    def refresh_events(self)->None:
        clear_layout(self.events); selected=self.calendar.selectedDate().toString("yyyy-MM-dd"); self.day.setText(self.calendar.selectedDate().toString("dddd\nd MMMM")); rows=self.db.query("SELECT * FROM reminders WHERE event_date=?",(selected,))+self.db.query("SELECT 'Commission payment' title,payment_date event_date,'commission' event_type,'' notes,0 completed,id FROM earnings WHERE payment_date=? AND received=0",(selected,))+self.db.query("SELECT c.name || ' due' title,b.due_date event_date,'rent' event_type,'AED ' || printf('%,.2f',b.planned_aed) notes,0 completed,b.id FROM budgets b JOIN categories c ON c.id=b.category_id WHERE b.due_date=? AND b.planned_aed>0",(selected,))+self.inspection_events(selected)
        if not rows:
            empty=QFrame(); empty.setObjectName("calendarEmpty"); empty_l=QVBoxLayout(empty); empty_l.setContentsMargins(16,18,16,18)
            icon=QLabel("✦"); icon.setObjectName("calendarEmptyIcon"); empty_l.addWidget(icon,0,Qt.AlignmentFlag.AlignCenter)
            label=QLabel("Nothing due — enjoy the clear space."); label.setObjectName("muted"); label.setAlignment(Qt.AlignmentFlag.AlignCenter); label.setWordWrap(True); empty_l.addWidget(label)
            self.events.addWidget(empty)
        for row in rows:
            event_type=str(row["event_type"]); accent={"salary":COLORS["green"],"commission":COLORS["purple"],"inspection":COLORS["cyan"],"rent":COLORS["amber"],"card":COLORS["red"],"subscription":COLORS["cyan"]}.get(event_type,COLORS["cyan"])
            card=QFrame(); card.setProperty("eventCard",True); card.setStyleSheet(f"QFrame[eventCard='true']{{background:#141a24;border:1px solid #202937;border-left:4px solid {accent};border-radius:10px;}}")
            lay=QVBoxLayout(card); lay.setContentsMargins(14,12,14,12); title=QLabel(row["title"]); title.setStyleSheet("font-weight:700;font-size:14px"); lay.addWidget(title); meta=QLabel(event_type.upper()); meta.setStyleSheet(f"color:{accent};font-size:10px;font-weight:700;letter-spacing:1px"); lay.addWidget(meta)
            if row["notes"]: detail=QLabel(row["notes"]); detail.setObjectName("muted"); lay.addWidget(detail)
            self.events.addWidget(card)

    def add(self)->None:
        title,ok=QInputDialog.getText(self,"New reminder","What would you like to remember?")
        if ok and title.strip():
            self.db.execute("INSERT INTO reminders(title,event_date,event_type) VALUES (?,?,?)",(title.strip(),self.calendar.selectedDate().toString("yyyy-MM-dd"),"custom")); self.refresh(); self.changed.emit()


class GoalsPage(Page):
    def __init__(self,db:Database):
        super().__init__(db); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); self.layout=QVBoxLayout(content); self.layout.setContentsMargins(24,22,24,28); self.layout.setSpacing(16); self.layout.addWidget(SectionHeader("Momentum","Tasteful milestones for the move. Important progress, without pressure or shame.")); self.quote=Card(); q=QVBoxLayout(self.quote); self.quote_text=QLabel(); self.quote_text.setWordWrap(True); self.quote_text.setStyleSheet("font-size:18px;font-style:italic"); q.addWidget(self.quote_text); self.why=QLabel(); self.why.setObjectName("muted"); self.why.setWordWrap(True); q.addWidget(self.why); self.layout.addWidget(self.quote); self.grid=QGridLayout(); self.grid.setSpacing(12); self.layout.addLayout(self.grid); outer.addWidget(page_scroll(content)); self.refresh()
    def refresh(self)->None:
        self.quote_text.setText(f'“{self.db.get_setting("quote","Protect the runway. Earn the upside.")}”'); self.why.setText("WHY I MOVED · "+self.db.get_setting("why_i_moved")); clear_layout(self.grid); goals=self.db.query("SELECT * FROM goals ORDER BY id")
        for i,row in enumerate(goals):
            value=float(row["current_value"]); target=max(1,float(row["target_value"])); pct=min(100,int(value/target*100)); card=Card(); lay=QVBoxLayout(card); lay.setContentsMargins(16,15,16,15); title=QLabel(row["name"]); title.setStyleSheet("font-weight:700"); lay.addWidget(title); progress=QProgressBar(); progress.setValue(pct); lay.addWidget(progress); label=QLabel("ACHIEVED" if row["achieved_at"] else f"{pct}% complete"); label.setStyleSheet(f"color:{COLORS['green'] if row['achieved_at'] else COLORS['muted']}"); lay.addWidget(label); card.mousePressEvent=lambda event,r=row:self.update_goal(r); self.grid.addWidget(card,i//3,i%3)
    def update_goal(self,row)->None:
        value,ok=QInputDialog.getDouble(self,"Update milestone",row["name"],row["current_value"],0,100000000,2)
        if ok: achieved=datetime.now().isoformat() if value>=row["target_value"] else None; self.db.execute("UPDATE goals SET current_value=?,achieved_at=? WHERE id=?",(value,achieved,row["id"])); self.refresh()


class ReportsPage(Page):
    def __init__(self,db:Database):
        super().__init__(db); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); root=QVBoxLayout(content); root.setContentsMargins(24,22,24,28); root.setSpacing(16); top=QHBoxLayout(); top.addWidget(SectionHeader("Reports","Local summaries for cash flow, debt, commission, categories and relocation spend.")); top.addStretch(); self.month=QDateEdit(QDate.currentDate()); self.month.setDisplayFormat("MMMM yyyy"); self.month.dateChanged.connect(self.refresh); top.addWidget(self.month); pdf=QPushButton("Export professional PDF"); pdf.setProperty("primary",True); pdf.clicked.connect(self.export_pdf); top.addWidget(pdf); root.addLayout(top)
        self.metrics={}; grid=QGridLayout()
        for i,(key,label) in enumerate([("income","Monthly income"),("expense","Monthly expenditure"),("net","Net cash flow"),("commission","Commission pending"),("debt","Card debt"),("relocation","Relocation spend")]): card=MetricCard(label); self.metrics[key]=card; grid.addWidget(card,i//3,i%3)
        root.addLayout(grid); self.charts=QHBoxLayout(); root.addLayout(self.charts); self.table=QTableWidget(0,3); self.table.setHorizontalHeaderLabels(["CATEGORY","TRANSACTIONS","SPEND · AED"]); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); root.addWidget(self.table); outer.addWidget(page_scroll(content)); self.summary={}; self.rows=[]; self.refresh()
    def refresh(self)->None:
        month=self.month.date().toString("yyyy-MM"); rate=self.db.get_setting("gbp_aed_rate","4.928313"); self.rows=self.db.transactions(month=month,limit=100000); income=sum((to_aed(r["amount"],r["currency"],rate) for r in self.rows if r["kind"]=="income"),Decimal(0)); expense=sum((to_aed(r["amount"],r["currency"],rate) for r in self.rows if r["kind"]=="expense" and not r["refundable_deposit"] and not r["budget_excluded"]),Decimal(0)); commission=sum((Decimal(str(r["commission_aed"])) for r in self.db.query("SELECT commission_aed FROM earnings WHERE received=0")),Decimal(0)); debt=sum((to_aed(r["current_balance"],r["currency"],rate) for r in self.db.query("SELECT * FROM credit_cards")),Decimal(0)); relocation=sum((to_aed(r["amount"],r["currency"],rate) for r in self.rows if r["category"] in {"Flight/relocation","Visa/administration"}),Decimal(0)); values={"income":income,"expense":expense,"net":income-expense,"commission":commission,"debt":debt,"relocation":relocation}
        for key,value in values.items(): primary,secondary=dual_amount(value,rate,signed=key=="net"); self.metrics[key].set_value(primary,secondary,accent=COLORS["red"] if key=="net" and value<0 else COLORS["green"] if key in {"income","net"} else None)
        cats={}; counts={}
        for r in self.rows:
            if r["kind"]=="expense" and not r["budget_excluded"]: cats[r["category"] or "Other"]=cats.get(r["category"] or "Other",Decimal(0))+to_aed(r["amount"],r["currency"],rate); counts[r["category"] or "Other"]=counts.get(r["category"] or "Other",0)+1
        ordered=sorted(cats.items(),key=lambda x:-x[1]); self.table.setRowCount(len(ordered))
        for i,(category,value) in enumerate(ordered): primary,secondary=dual_amount(value,rate,2); self.table.setRowHeight(i,48); self.table.setItem(i,0,table_item(category)); self.table.setItem(i,1,table_item(str(counts[category]))); self.table.setItem(i,2,table_item(f"{primary}\n{secondary}",Qt.AlignmentFlag.AlignRight))
        self.table.setColumnWidth(0,240); clear_layout(self.charts); self.charts.addWidget(bar_chart("Income vs expenditure",[float(income),float(expense)],[float(income),float(expense)],["Income","Expense"])); self.charts.addWidget(pie_chart("Category spending",[(k,float(v),[COLORS["cyan"],COLORS["purple"],COLORS["green"],COLORS["amber"],COLORS["red"]][i%5]) for i,(k,v) in enumerate(ordered[:6])] or [("No spend",1,COLORS["border2"])])); self.summary={"Income":f"AED {income:,.2f} / GBP {gbp_equivalent(income,rate):,.2f}","Expenditure":f"AED {expense:,.2f} / GBP {gbp_equivalent(expense,rate):,.2f}","Net cash flow":f"AED {income-expense:,.2f} / GBP {gbp_equivalent(income-expense,rate):,.2f}","Commission pending":f"AED {commission:,.2f} / GBP {gbp_equivalent(commission,rate):,.2f}"}
    def export_pdf(self)->None:
        path,_=QFileDialog.getSaveFileName(self,"Export report",f"DXB-RUNWAY-report-{self.month.date().toString('yyyy-MM')}.pdf","PDF files (*.pdf)")
        if path: create_financial_pdf(Path(path),month=self.month.date().toString("MMMM yyyy"),summary=self.summary,rows=[dict(r) for r in self.rows],gbp_aed_rate=self.db.get_setting("gbp_aed_rate","4.928313")); QMessageBox.information(self,"Report exported",f"PDF saved locally to:\n{path}")


class _GoogleScheduleAuthSignals(QObject):
    finished=Signal();failed=Signal(str)


class _GoogleScheduleAuthJob(QRunnable):
    def __init__(self):super().__init__();self.signals=_GoogleScheduleAuthSignals()
    def run(self):
        try:GoogleSheetsReadOnlyClient().authorize();self.signals.finished.emit()
        except Exception as error:self.signals.failed.emit(str(error))


class SettingsPage(Page):
    def __init__(self,db:Database):
        super().__init__(db); self._google_busy=False; outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); root=QVBoxLayout(content); root.setContentsMargins(24,22,24,28); root.setSpacing(16); root.addWidget(SectionHeader("Settings & data","Runway is local-first. Only services you explicitly connect can make narrowly scoped network requests.")); tabs=QTabWidget(); root.addWidget(tabs)
        finance=QWidget(); form=QFormLayout(finance); self.fields={}; settings=db.all_settings(); self.original_rate=float(settings.get("gbp_aed_rate","4.928313")); configs=[("gbp_aed_rate","GBP → AED rate",6),("monthly_spending_cap_gbp","Monthly spending cap · GBP",2),("salary_aed","Guaranteed salary · AED",2),("rent_aed","Accommodation · AED",2),("security_deposit_aed","Refundable deposit · AED",2),("transport_aed","Transport · AED",2),("food_aed","Food estimate · AED",2),("emergency_fund_aed","Protected emergency fund · AED",2)]
        for key,label,decimals in configs: box=MoneyBox(decimals=decimals); box.setValue(float(settings.get(key,0))); self.fields[key]=box; form.addRow(label,box)
        rate_info=QLabel(f"Current snapshot: 1 GBP = {self.original_rate:.6f} AED\nSource: {settings.get('gbp_aed_rate_source','Manual')} · Updated {settings.get('gbp_aed_rate_updated_at','—')}\nGBP equivalents are calculated as AED ÷ this rate."); rate_info.setObjectName("muted"); rate_info.setWordWrap(True); form.addRow("Rate details",rate_info)
        self.quote=QLineEdit(settings.get("quote","")); self.why=QTextEdit(settings.get("why_i_moved","")); self.why.setMaximumHeight(90); form.addRow("Motivational quote",self.quote); form.addRow("Why I moved",self.why); save=QPushButton("Save settings"); save.setProperty("primary",True); save.clicked.connect(self.save); form.addRow(save); tabs.addTab(finance,"Financial assumptions")
        data=QWidget(); dl=QVBoxLayout(data); dl.setContentsMargins(18,18,18,18); dl.addWidget(QLabel(f"Database\n{db.path}")); dl.addWidget(QLabel(f"Receipts\n{db.receipts_dir}"));
        for label,callback in [("Create portable backup",self.backup),("Create encrypted backup",lambda:self.backup(True)),("Restore backup",self.restore),("Database health check",self.health),("Open local data folder",self.open_folder),("Reset demo data",self.reset_demo)]: btn=QPushButton(label); btn.clicked.connect(callback); dl.addWidget(btn)
        privacy=QLabel("PRIVACY GUARANTEE\n\nYour Mac database remains the source of truth. Stock and Vehicle Desk data are mirrored over an encrypted connection to your private, owner-only phone app. DXB RUNWAY contains no analytics or telemetry. Transactions, receipts and other private records stay on this Mac unless you explicitly include them in a portable backup. Google Schedule, if connected, is isolated behind a read-only Sheets client."); privacy.setWordWrap(True); privacy.setObjectName("muted"); dl.addWidget(privacy); dl.addStretch(); tabs.addTab(data,"Local data & privacy")
        google=QWidget();gl=QVBoxLayout(google);gl.setContentsMargins(20,20,20,20);gl.setSpacing(14);gl.addWidget(SectionHeader("Google Sheets · read only","Schedule and Pipeline use the same capability-limited read-only Google connection."));self.google_state=QLabel();self.google_state.setWordWrap(True);gl.addWidget(self.google_state)
        pipeline=Card();pl=QFormLayout(pipeline);self.pipeline_url=QLineEdit(db.get_setting("pipeline_spreadsheet_id",""));self.pipeline_url.setPlaceholderText("Paste the Pipeline Google Sheet URL");self.pipeline_sheet=QLineEdit(db.get_setting("pipeline_sheet_name","Pipeline"));self.pipeline_sheet.setPlaceholderText("Pipeline");self.pipeline_reader_url=QLineEdit(db.get_setting("pipeline_reader_url",""));self.pipeline_reader_url.setPlaceholderText("https://script.google.com/macros/s/.../exec");self.pipeline_reader_key=QLineEdit();self.pipeline_reader_key.setEchoMode(QLineEdit.EchoMode.Password);self.pipeline_reader_key.setPlaceholderText("Saved securely — leave blank to keep existing key" if db.get_setting("pipeline_reader_key","") else "Enter the private Pipeline access key");pl.addRow("Pipeline spreadsheet",self.pipeline_url);pl.addRow("Sheet / tab name",self.pipeline_sheet);pl.addRow("Read-only bridge URL",self.pipeline_reader_url);pl.addRow("Private access key",self.pipeline_reader_key);save_pipeline=QPushButton("Save Pipeline connection");save_pipeline.setProperty("primary",True);save_pipeline.clicked.connect(self.save_pipeline_connection);pl.addRow(save_pipeline);gl.addWidget(pipeline)
        lock=Card();ll=QVBoxLayout(lock);title=QLabel("STRICTLY READ ONLY");title.setStyleSheet(f"color:{COLORS['green']};font-weight:900");ll.addWidget(title);copy=QLabel(f"DXB Runway can read this spreadsheet but cannot edit, delete, append or modify it.\n\nOnly OAuth scope requested:\n{SCOPE}\n\nThe Sheets transport only permits GET requests. OAuth credentials come from DXB_GOOGLE_OAUTH_CLIENT_ID and optional DXB_GOOGLE_OAUTH_CLIENT_SECRET environment variables. Tokens are stored in macOS Keychain and never shown in the UI or logs.");copy.setWordWrap(True);copy.setObjectName("muted");ll.addWidget(copy);gl.addWidget(lock)
        actions=QHBoxLayout();self.google_connect=QPushButton("Connect Google Schedule");self.google_connect.setProperty("primary",True);self.google_connect.clicked.connect(self.connect_google_schedule);actions.addWidget(self.google_connect);self.google_disconnect=QPushButton("Disconnect");self.google_disconnect.clicked.connect(self.disconnect_google_schedule);actions.addWidget(self.google_disconnect);actions.addStretch();gl.addLayout(actions);gl.addStretch();tabs.addTab(google,"Google Schedule")
        invoices=QWidget();il=QVBoxLayout(invoices);il.setContentsMargins(20,20,20,20);il.setSpacing(14);il.addWidget(SectionHeader("Sold invoice sync","Runway reads only the Google Chat INVOICES space and safely matches sold vehicles to current stock."));self.invoice_state=QLabel();self.invoice_state.setWordWrap(True);il.addWidget(self.invoice_state)
        guard=Card();guard_l=QVBoxLayout(guard);guard_title=QLabel("READ ONLY · SAFE MATCHING");guard_title.setStyleSheet(f"color:{COLORS['green']};font-weight:900");guard_l.addWidget(guard_title);guard_copy=QLabel("Runway cannot send, reply to, react to, edit or delete Google Chat messages. Exact stock numbers are preferred. A unique vehicle/year match may be sold automatically; ambiguous matches and consignments are held for review without changing stock.");guard_copy.setWordWrap(True);guard_copy.setObjectName("muted");guard_l.addWidget(guard_copy);il.addWidget(guard)
        self.invoice_events=QTableWidget(0,5);self.invoice_events.setHorizontalHeaderLabels(["TIME","VEHICLE","STOCK NO.","OUTCOME","DETAIL"]);self.invoice_events.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.invoice_events.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.invoice_events.setMinimumHeight(260);il.addWidget(self.invoice_events);il.addStretch();tabs.addTab(invoices,"Sold invoice sync")
        outer.addWidget(page_scroll(content));self.refresh_google_schedule_status();self.refresh_invoice_status()

    def refresh(self)->None:
        self.refresh_google_schedule_status();self.refresh_invoice_status()

    def refresh_invoice_status(self)->None:
        connected=bool(self.db.get_setting("invoice_sync_endpoint") and self.db.get_setting("invoice_sync_access_key"));last=self.db.get_setting("invoice_sync_last_at","Never");error=self.db.get_setting("invoice_sync_last_error")
        message=f"{'Connected — Read Only' if connected else 'Not connected'} · checks every 5 minutes · last checked {last}"
        if error:message+=f"\nLast warning: {error}"
        self.invoice_state.setText(message);self.invoice_state.setStyleSheet(f"color:{COLORS['green'] if connected else COLORS['amber']};font-size:15px;font-weight:800")
        rows=self.db.query("SELECT * FROM invoice_sync_events ORDER BY processed_at DESC,id DESC LIMIT 20") if connected else []
        self.invoice_events.setRowCount(len(rows))
        for i,row in enumerate(rows):
            values=[row["processed_at"],f"{row['model_year'] or ''} {row['vehicle_text']}".strip(),row["stock_number"],str(row["outcome"]).upper(),row["detail"]]
            for j,value in enumerate(values):self.invoice_events.setItem(i,j,table_item(value,Qt.AlignmentFlag.AlignVCenter,COLORS["green"] if j==3 and row["outcome"]=="sold" else COLORS["amber"] if j==3 and row["outcome"]=="review" else None))
        self.invoice_events.horizontalHeader().setStretchLastSection(True)
    def refresh_google_schedule_status(self)->None:
        mode="unavailable"
        try:
            client=GoogleSheetsReadOnlyClient();connected=client.connected();mode=client.connection_mode();message="Connected — Read Only · no login required" if mode=="public_readonly" else "Connected — Read Only · OAuth"
        except GoogleScheduleError as error:connected=False;message=f"Not configured — {error}"
        self.google_state.setText(message);self.google_state.setStyleSheet(f"color:{COLORS['green'] if connected else COLORS['amber']};font-size:16px;font-weight:800");oauth=connected and mode=="oauth";self.google_disconnect.setEnabled(oauth);self.google_connect.setVisible(oauth or bool(os.environ.get("DXB_GOOGLE_OAUTH_CLIENT_ID")));self.google_connect.setText("Reconnect Google Schedule" if oauth else "Connect Google Schedule")
    def connect_google_schedule(self)->None:
        if self._google_busy:return
        self._google_busy=True;self.google_connect.setEnabled(False);self.google_state.setText("Waiting for Google authorization in your browser…");job=_GoogleScheduleAuthJob();job.signals.finished.connect(self._google_connected);job.signals.failed.connect(self._google_failed);self._google_job=job;QThreadPool.globalInstance().start(job)
    def _google_connected(self)->None:
        self._google_busy=False;self.google_connect.setEnabled(True);self.refresh_google_schedule_status();QMessageBox.information(self,"Google Schedule connected","Connected — Read Only\n\nRunway can read the rota but cannot modify the management spreadsheet.");self.changed.emit()
    def _google_failed(self,message:str)->None:
        self._google_busy=False;self.google_connect.setEnabled(True);self.refresh_google_schedule_status();QMessageBox.warning(self,"Google Schedule connection failed",message)
    def disconnect_google_schedule(self)->None:
        if QMessageBox.question(self,"Disconnect Google Schedule","Remove the read-only Google token from macOS Keychain? Cached rota data will remain available.")!=QMessageBox.StandardButton.Yes:return
        try:GoogleSheetsReadOnlyClient().disconnect()
        except GoogleScheduleError as error:QMessageBox.warning(self,"Disconnect failed",str(error));return
        self.refresh_google_schedule_status();self.changed.emit()
    def save_pipeline_connection(self)->None:
        source=spreadsheet_id(self.pipeline_url.text())
        if not source:QMessageBox.warning(self,"Invalid Pipeline link","Paste the full Google Sheets Pipeline URL, or its spreadsheet ID.");return
        reader_url=self.pipeline_reader_url.text().strip();reader_key=self.pipeline_reader_key.text().strip();existing_key=self.db.get_setting("pipeline_reader_key","")
        if not reader_url.startswith("https://script.google.com/macros/s/") or not reader_url.endswith("/exec"):QMessageBox.warning(self,"Invalid read-only bridge","Paste the deployed Google Apps Script web-app URL ending in /exec.");return
        if not reader_key and not existing_key:QMessageBox.warning(self,"Access key required","Enter the private Pipeline access key. It is sent only with GET requests to the approved bridge.");return
        self.db.set_setting("pipeline_spreadsheet_id",source);self.db.set_setting("pipeline_sheet_name",self.pipeline_sheet.text().strip() or "Pipeline");self.db.set_setting("pipeline_reader_url",reader_url)
        if reader_key:self.db.set_setting("pipeline_reader_key",reader_key)
        self.pipeline_url.setText(source);self.pipeline_reader_key.clear();self.pipeline_reader_key.setPlaceholderText("Saved — leave blank to keep existing key");QMessageBox.information(self,"Pipeline connected","Saved — Strictly Read Only\n\nRunway uses only GET requests and cannot edit, append or delete anything in the management spreadsheet.");self.changed.emit()
    def save(self)->None:
        for key,box in self.fields.items(): self.db.set_setting(key,box.value())
        if abs(self.fields["gbp_aed_rate"].value()-self.original_rate)>0.0000005:
            self.db.set_setting("gbp_aed_rate_updated_at",date.today().isoformat()); self.db.set_setting("gbp_aed_rate_source","Manual entry")
        self.db.set_setting("quote",self.quote.text().strip()); self.db.set_setting("why_i_moved",self.why.toPlainText().strip()); QMessageBox.information(self,"Settings saved","Assumptions updated. Dashboard calculations will refresh immediately."); self.changed.emit()
    def backup(self,encrypted=False)->None:
        password=None
        if encrypted:
            password,ok=QInputDialog.getText(self,"Encrypted backup","Choose a backup password",QLineEdit.EchoMode.Password)
            if not ok or len(password)<8:
                if ok: QMessageBox.warning(self,"Password too short","Use at least 8 characters for an encrypted backup.")
                return
        suffix=".dxbr.enc" if encrypted else ".dxbr"; path,_=QFileDialog.getSaveFileName(self,"Create backup",f"DXB-RUNWAY-backup-{date.today()}{suffix}",f"DXB RUNWAY backups (*{suffix})")
        if path: self.db.backup(Path(path),password); QMessageBox.information(self,"Backup complete",f"Portable backup saved to:\n{path}")
    def restore(self)->None:
        path,_=QFileDialog.getOpenFileName(self,"Restore backup","","DXB RUNWAY backups (*.dxbr *.enc);;All files (*.*)")
        if path and QMessageBox.question(self,"Restore data","Current data will be preserved in a timestamped pre-restore database. Continue?")==QMessageBox.StandardButton.Yes:
            password=None
            if Path(path).read_bytes()[:6]==b"DXBR2\n":
                password,ok=QInputDialog.getText(self,"Encrypted backup","Enter the backup password",QLineEdit.EchoMode.Password)
                if not ok:return
            try:self.db.restore(Path(path),password); QMessageBox.information(self,"Restore complete","Backup restored successfully. Restart the application to reload all screens.")
            except Exception as error:QMessageBox.critical(self,"Restore failed",str(error))
    def health(self)->None: okay,message=self.db.health_check(); QMessageBox.information(self,"Database health" if okay else "Database issue",message)
    def open_folder(self)->None: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.db.path.parent)))
    def reset_demo(self)->None:
        if QMessageBox.question(self,"Reset demo data","Delete transactions, earnings and cards, then load the representative demo set?")==QMessageBox.StandardButton.Yes:
            for table in ("transactions","earnings","credit_cards","reminders","budgets","vehicles","customer_contacts","performance_months"): self.db.execute(f"DELETE FROM {table}")
            self.db.seed_demo(); self.changed.emit(); QMessageBox.information(self,"Demo reset","Representative local demo data has been loaded.")
