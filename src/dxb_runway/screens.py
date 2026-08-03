from __future__ import annotations

import calendar
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QDate, QEvent, QTimer, Qt, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCalendarWidget, QCheckBox, QComboBox, QDateEdit, QDialog, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox, QStyledItemDelegate, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget
)

from .database import Database
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


def customer_vehicle_year(stored_value: int) -> int:
    value=int(stored_value)
    return value if 2018<=value<=2026 else max(2018,min(2026,2026-value))


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
        tools=QHBoxLayout()
        for label,callback in [("Edit selected",self.edit_template),("Delete selected",self.delete_template)]:
            button=QPushButton(label); button.clicked.connect(callback); tools.addWidget(button)
        tools.addStretch(); layout.addLayout(tools)
        body=QHBoxLayout(); body.setSpacing(14); list_card=Card(); list_layout=QVBoxLayout(list_card); list_layout.setContentsMargins(16,15,16,15); list_layout.addWidget(QLabel("SAVED TEMPLATES")); self.table=QTableWidget(0,1); self.table.setHorizontalHeaderLabels(["TEMPLATE"]); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); self.table.itemSelectionChanged.connect(self.show_selected); list_layout.addWidget(self.table); body.addWidget(list_card,1)
        preview_card=Card(); preview_layout=QVBoxLayout(preview_card); preview_layout.setContentsMargins(18,16,18,16); self.preview_title=QLabel("SELECT A TEMPLATE"); self.preview_title.setStyleSheet("font-size:18px;font-weight:800"); preview_layout.addWidget(self.preview_title)
        search_row=QHBoxLayout(); search_row.addWidget(QLabel("SEARCH CUSTOMER")); self.customer_search=QLineEdit(); self.customer_search.setPlaceholderText("Type a name, vehicle or last 5 phone digits…"); self.customer_search.setClearButtonEnabled(True); self.customer_search.textChanged.connect(self.filter_customers); search_row.addWidget(self.customer_search,1); preview_layout.addLayout(search_row)
        result_row=QHBoxLayout(); result_row.addWidget(QLabel("MATCHING CUSTOMERS")); self.customer=QComboBox(); self.customer.setMaxVisibleItems(12); self.customer.setMinimumWidth(420); self.customer.currentIndexChanged.connect(self.show_selected); result_row.addWidget(self.customer,1); preview_layout.addLayout(result_row)
        self.customer_hint=QLabel("Search across active callers and inspections, then choose the correct customer by vehicle and phone suffix."); self.customer_hint.setObjectName("muted"); preview_layout.addWidget(self.customer_hint); self.preview=QTextEdit(); self.preview.setReadOnly(True); self.preview.setPlaceholderText("Your selected WhatsApp message will appear here."); preview_layout.addWidget(self.preview,1); self.copy_button=QPushButton("Copy personalised message"); self.copy_button.setProperty("primary",True); self.copy_button.clicked.connect(self.copy_message); self.copy_button.setEnabled(False); preview_layout.addWidget(self.copy_button); body.addWidget(preview_card,2); layout.addLayout(body,1); self.customer_rows=[]; self.refresh()

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


class StockLevelPage(Page):
    def __init__(self, db: Database):
        super().__init__(db)
        layout=QVBoxLayout(self); layout.setContentsMargins(24,22,24,24); layout.setSpacing(14)
        top=QHBoxLayout(); top.addWidget(SectionHeader("Stock level","Every vehicle currently held, including cash purchases and consignments.")); top.addStretch()
        add=QPushButton("＋ Add car"); add.setProperty("primary",True); add.clicked.connect(self.add_vehicle); top.addWidget(add)
        consignment=QPushButton("Mark as consignment"); consignment.clicked.connect(self.mark_consignment); top.addWidget(consignment)
        sold=QPushButton("Mark selected as sold"); sold.clicked.connect(self.sell_selected); top.addWidget(sold)
        remove=QPushButton("Remove / return to owner"); remove.clicked.connect(self.remove_selected); top.addWidget(remove); layout.addLayout(top)
        budget_card=Card(); budget_layout=QVBoxLayout(budget_card); budget_layout.setContentsMargins(18,15,18,15); budget_top=QHBoxLayout(); self.live_budget_title=QLabel("LIVE PURCHASING BUDGET"); self.live_budget_title.setStyleSheet("font-weight:800"); budget_top.addWidget(self.live_budget_title); budget_top.addStretch(); self.live_budget_value=QLabel(); self.live_budget_value.setStyleSheet("font-size:20px;font-weight:800"); budget_top.addWidget(self.live_budget_value); budget_layout.addLayout(budget_top); self.live_budget_detail=QLabel(); self.live_budget_detail.setObjectName("muted"); budget_layout.addWidget(self.live_budget_detail); self.live_budget_bar=QProgressBar(); budget_layout.addWidget(self.live_budget_bar); layout.addWidget(budget_card)
        metrics=QGridLayout(); metrics.setSpacing(12); self.metrics={}
        for i,(key,label,color) in enumerate([("total","Cars in stock",COLORS["cyan"]),("cash","Cash purchases",COLORS["green"]),("consignment","Consignments",COLORS["purple"]),("value","Total stock value",COLORS["cyan"]),("profit","Expected stock profit",COLORS["amber"])]):
            card=MetricCard(label,accent=color); self.metrics[key]=card; metrics.addWidget(card,0,i)
        layout.addLayout(metrics)
        card=Card(); card_layout=QVBoxLayout(card); card_layout.setContentsMargins(16,15,16,15)
        note=QLabel("Consignment cost is the agreed owner payout. It contributes to expected and realised profit, but does not use the cash purchasing budget."); note.setObjectName("muted"); note.setWordWrap(True); card_layout.addWidget(note)
        self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(["VEHICLE","STOCK TYPE","STOCKED","COST / PAYOUT","EXPECTED SALE","EXPECTED PROFIT"]); self.table.setWordWrap(True); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); self.table.doubleClicked.connect(self.sell_selected); card_layout.addWidget(self.table); layout.addWidget(card,1)
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
        self.metrics["total"].set_value(str(len(rows)),"All unsold vehicles")
        self.metrics["cash"].set_value(str(len(cash)),f"AED {sum((Decimal(str(row['purchase_price_aed'])) for row in cash),Decimal('0')):,.0f} invested")
        self.metrics["consignment"].set_value(str(len(consignment)),"Held without using cash budget")
        stock_value_aed,stock_value_gbp=dual_amount(stock_value,rate); self.metrics["value"].set_value(stock_value_aed,f"{stock_value_gbp} · includes consignments")
        expected_aed,expected_gbp=dual_amount(expected,rate,signed=True); self.metrics["profit"].set_value(expected_aed,expected_gbp)
        self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            self.table.setRowHeight(i,58); first=table_item(row["vehicle_name"]); first.setData(Qt.ItemDataRole.UserRole,row["id"]); first.setToolTip(row["notes"] or f"Expected sale · AED {row['expected_sale_price_aed']:,.0f}"); self.table.setItem(i,0,first)
            cost=Decimal(str(row["purchase_price_aed"])); sale=Decimal(str(row["expected_sale_price_aed"])); profit=Decimal(str(row["expected_profit_aed"]))
            values=["Cash purchase" if row["purchase_type"]=="cash" else "Consignment",row["purchased_date"],f"{cost:,.0f} AED\n{gbp_equivalent(cost,rate):,.0f} GBP",f"{sale:,.0f} AED\n{gbp_equivalent(sale,rate):,.0f} GBP",f"{profit:+,.0f} AED\n{gbp_equivalent(profit,rate):+,.0f} GBP"]
            for j,value in enumerate(values,1):
                color=COLORS["purple"] if j==1 and row["purchase_type"]=="consignment" else COLORS["green"] if j==5 and profit>=0 else COLORS["red"] if j==5 else None
                self.table.setItem(i,j,table_item(value,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight if j>=3 else Qt.AlignmentFlag.AlignVCenter,color))
        self.table.setColumnWidth(0,150); self.table.setColumnWidth(1,120); self.table.setColumnWidth(2,100); self.table.setColumnWidth(3,130); self.table.setColumnWidth(4,130)

    def add_vehicle(self)->None:
        dialog=VehicleDialog(self.db,self)
        if dialog.exec(): self.db.add_vehicle(**dialog.values()); self.refresh(); self.changed.emit()

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
        tier_matrix=Card(); matrix_layout=QVBoxLayout(tier_matrix); matrix_layout.setContentsMargins(16,15,16,15); matrix_layout.addWidget(SectionHeader("Monthly tier percentages","Every live month, its purchasing budget, target percentages and achieved commission rate."))
        earnings_cards=QGridLayout(); earnings_cards.setSpacing(12); self.tier_earnings={}
        for column,(key,label,color) in enumerate([("tier3","Tier 3 total pay",COLORS["cyan"]),("tier2","Tier 2 total pay",COLORS["purple"]),("tier1","Tier 1 total pay",COLORS["green"])]):
            card=MetricCard(label,accent=color); self.tier_earnings[key]=card; earnings_cards.addWidget(card,0,column)
        matrix_layout.addLayout(earnings_cards)
        self.tier_table=QTableWidget(12,7); self.tier_table.setHorizontalHeaderLabels(["MONTH","BUDGET · AED","BASELINE RATE","TIER 3 TARGET / RATE","TIER 2 TARGET / RATE","TIER 1 TARGET / RATE","ACHIEVED TIER / RATE"]); self.tier_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.tier_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.tier_table.verticalHeader().hide(); self.tier_table.horizontalHeader().setStretchLastSection(True); self.tier_table.setMinimumHeight(390); matrix_layout.addWidget(self.tier_table); root.addWidget(tier_matrix)
        sections=QHBoxLayout(); sections.setSpacing(12)
        sold_card=Card(); sold_layout=QVBoxLayout(sold_card); sold_layout.setContentsMargins(16,15,16,15); sold_head=QHBoxLayout(); sold_head.addWidget(SectionHeader("Sold in selected month","The view resets with each month; all earlier months remain available above.")); sold_head.addStretch(); undo=QPushButton("Return selected to stock"); undo.clicked.connect(self.return_selected); sold_head.addWidget(undo); sold_layout.addLayout(sold_head)
        self.sold_table=QTableWidget(0,5); self.sold_table.setHorizontalHeaderLabels(["VEHICLE","STOCK TYPE","SOLD","REALISED PROFIT","COMMISSION"]); self.sold_table.setWordWrap(True); self.sold_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.sold_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.sold_table.verticalHeader().hide(); self.sold_table.horizontalHeader().setStretchLastSection(True); sold_layout.addWidget(self.sold_table); sections.addWidget(sold_card,1); root.addLayout(sections,1)
        foot=QLabel("Each month name always shows its latest occurrence. Older years remain stored under Misc → Vehicle history. Commission syncs automatically to Overview, Calendar and Reports."); foot.setObjectName("muted"); foot.setWordWrap(True); root.addWidget(foot); outer.addWidget(page_scroll(content)); self.system_month=date.today().strftime("%Y-%m"); self.month_timer=QTimer(self); self.month_timer.setInterval(60_000); self.month_timer.timeout.connect(self.check_month_rollover); self.month_timer.start(); self.refresh()

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
        sold=self.db.sold_vehicles(month); realised=sum((Decimal(str(row["realised_profit_aed"])) for row in sold),Decimal("0")); result=calculate_earnings(year=year,month=month_number,budget_aed=budget,eligible_profit_aed=max(Decimal("0"),realised),average_margin_aed=24700,salary_aed=salary)
        if month<=date.today().strftime("%Y-%m") and (sold or month==date.today().strftime("%Y-%m")): self.sync_earnings(result,year,month_number)
        rate_pct=f"{float(result.rate*100):g}%"; self.current_result=result; self.metrics["sold"].set_value(str(len(sold)),month_label); profit_aed,profit_gbp=dual_amount(realised,rate,signed=True); self.metrics["profit"].set_value(profit_aed,profit_gbp,COLORS["red"] if realised<0 else COLORS["green"]); commission_aed,commission_gbp=dual_amount(result.commission_aed,rate); self.metrics["commission"].set_value(commission_aed,f"{commission_gbp} · Commission only · {result.tier.value} at {rate_pct}"); total_aed,total_gbp=dual_amount(result.total_earned_aed,rate); self.metrics["total"].set_value(total_aed,f"{total_gbp} · Base AED {result.salary_aed:,.0f} + commission AED {result.commission_aed:,.0f}")
        tier_color=COLORS["green"] if result.tier!=CommissionTier.BASELINE else COLORS["cyan"]; self.tier.setText(f"{result.tier.value.upper()} · {rate_pct}"); self.tier.setStyleSheet(f"font-size:20px;font-weight:800;color:{tier_color}")
        t3,t2,t1=TARGET_PERCENTAGES[month_number]; achieved=(realised/budget*100) if budget>0 else Decimal("0"); self.achievement.setText(f"Profit achieved · {achieved:.2f}% of purchasing budget"); self.schedule.setText(f"{month_label} targets · Tier 3 {float(t3*100):g}%  ·  Tier 2 {float(t2*100):g}%  ·  Tier 1 {float(t1*100):g}%"+(f"  ·  Next tier in AED {result.distance_to_next_aed:,.0f}" if result.next_tier else "  ·  Highest tier reached")); self.tier_progress.setRange(0,max(1,int(t1*10000))); self.tier_progress.setValue(max(0,min(self.tier_progress.maximum(),int(achieved*100))))
        for key,label,target,commission_rate in [("tier3","Tier 3",t3,Decimal("0.05")),("tier2","Tier 2",t2,Decimal("0.065")),("tier1","Tier 1",t1,Decimal("0.08"))]:
            target_profit=money(budget*target); commission=money(target_profit*commission_rate); total=money(salary+commission); total_aed,total_gbp=dual_amount(total,rate); self.tier_earnings[key].set_value(total_aed,f"{total_gbp} · {label} commission AED {commission:,.0f} + salary AED {salary:,.0f}")
        self.sold_table.setRowCount(len(sold))
        for i,row in enumerate(sold):
            self.sold_table.setRowHeight(i,56); first=table_item(row["vehicle_name"]); first.setData(Qt.ItemDataRole.UserRole,row["id"]); first.setToolTip(f"Sale price · AED {row['sold_price_aed']:,.0f}"); self.sold_table.setItem(i,0,first); profit=Decimal(str(row["realised_profit_aed"])); commission=money(profit*result.rate) if realised>0 else Decimal("0"); values=[row["sold_date"],f"{profit:+,.0f} AED\n{gbp_equivalent(profit,rate):+,.0f} GBP",f"{commission:+,.0f} AED\n{gbp_equivalent(commission,rate):+,.0f} GBP"]
            values.insert(0,"Cash purchase" if row["purchase_type"]=="cash" else "Consignment")
            for j,value in enumerate(values,1): self.sold_table.setItem(i,j,table_item(value,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight,color=COLORS["purple"] if j==1 and row["purchase_type"]=="consignment" else COLORS["green"] if j in {3,4} and profit>=0 else COLORS["red"] if j in {3,4} else None))
        self.sold_table.setColumnWidth(0,140); self.sold_table.setColumnWidth(1,120); self.sold_table.setColumnWidth(2,95); self.sold_table.setColumnWidth(3,150); self.sold_table.horizontalHeader().setStretchLastSection(True)
        self.refresh_tier_table(salary)

    def refresh_tier_table(self,salary:Decimal)->None:
        self.tier_table.setRowCount(12)
        for row_index in range(12):
            month_number=row_index+1; month=str(self.month.itemData(row_index,Qt.ItemDataRole.UserRole)); year=int(month[:4]); budget=self.db.performance_budget(month); sold=self.db.sold_vehicles(month); realised=sum((Decimal(str(vehicle["realised_profit_aed"])) for vehicle in sold),Decimal("0")); result=calculate_earnings(year=year,month=month_number,budget_aed=budget,eligible_profit_aed=max(Decimal("0"),realised),salary_aed=salary); t3,t2,t1=TARGET_PERCENTAGES[month_number]
            values=[self.month.itemText(row_index),f"{budget:,.0f}","4%",f"{t3*100:g}% / 5%",f"{t2*100:g}% / 6.5%",f"{t1*100:g}% / 8%",f"{result.tier.value} / {result.rate*100:g}%"]
            for column,value in enumerate(values):
                item=table_item(str(value),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight if column else Qt.AlignmentFlag.AlignVCenter,COLORS["green"] if column==6 and result.tier!=CommissionTier.BASELINE else COLORS["cyan"] if column==6 else None); self.tier_table.setItem(row_index,column,item)
            self.tier_table.setRowHeight(row_index,40)
        for column,width in enumerate([125,125,105,145,145,145]): self.tier_table.setColumnWidth(column,width)

    def sync_earnings(self,result,year:int,month_number:int)->None:
        earned_date=date(year,month_number,calendar.monthrange(year,month_number)[1]).isoformat()
        self.db.execute("INSERT INTO earnings(year,month,purchasing_budget_aed,eligible_profit_aed,average_margin_aed,deductions_aed,tier,salary_aed,commission_aed,earned_date,payment_date,received) VALUES (?,?,?,?,?,?,?,?,?,?,?,0) ON CONFLICT(year,month) DO UPDATE SET purchasing_budget_aed=excluded.purchasing_budget_aed,eligible_profit_aed=excluded.eligible_profit_aed,average_margin_aed=excluded.average_margin_aed,deductions_aed=excluded.deductions_aed,tier=excluded.tier,salary_aed=excluded.salary_aed,commission_aed=excluded.commission_aed,earned_date=excluded.earned_date,payment_date=excluded.payment_date",(year,month_number,float(result.budget_aed),float(result.eligible_profit_aed),24700,0,result.tier.value,float(result.salary_aed),float(result.commission_aed),earned_date,result.payment_date.isoformat()))

    def save_budget(self)->None:
        self.db.set_performance_budget(self.selected_month(),self.budget.value()); self.refresh(); self.changed.emit()

    def save_salary(self)->None:
        self.db.set_setting("salary_aed",f"{self.salary.value():.2f}")
        current=date.today().strftime("%Y-%m"); year,month_number=(int(value) for value in current.split("-")); budget=self.db.performance_budget(current); sold=self.db.sold_vehicles(current); realised=sum((Decimal(str(row["realised_profit_aed"])) for row in sold),Decimal("0")); result=calculate_earnings(year=year,month=month_number,budget_aed=budget,eligible_profit_aed=max(Decimal("0"),realised),salary_aed=self.salary.value()); self.sync_earnings(result,year,month_number)
        self.refresh(); self.changed.emit()

    def return_selected(self)->None:
        vehicle_id=self.selected_id(self.sold_table)
        if vehicle_id is None: QMessageBox.information(self,"Select a car","Select a sold vehicle first."); return
        if QMessageBox.question(self,"Return to stock","Move this vehicle back to current stock and remove its profit from this month?")==QMessageBox.StandardButton.Yes: self.db.return_vehicle_to_stock(vehicle_id); self.refresh(); self.changed.emit()


class VehicleHistoryPage(Page):
    def __init__(self,db:Database):
        super().__init__(db); layout=QVBoxLayout(self); layout.setContentsMargins(24,22,24,24); layout.setSpacing(14)
        layout.addWidget(SectionHeader("Vehicle history","Archived monthly performance stays available for year-on-year comparison."))
        note=QLabel("Vehicle Desk shows only the latest occurrence of each month name. Nothing is deleted when a month rolls into a new year."); note.setObjectName("muted"); note.setWordWrap(True); layout.addWidget(note)
        self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(["MONTH","CARS SOLD","REALISED PROFIT","COMMISSION","PURCHASING BUDGET","CASH PURCHASED"]); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.table,1); self.refresh()

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


class SettingsPage(Page):
    def __init__(self,db:Database):
        super().__init__(db); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); root=QVBoxLayout(content); root.setContentsMargins(24,22,24,28); root.setSpacing(16); root.addWidget(SectionHeader("Settings & data","All settings and data stay in this computer's local application-data folder. No telemetry, accounts or network requests.")); tabs=QTabWidget(); root.addWidget(tabs)
        finance=QWidget(); form=QFormLayout(finance); self.fields={}; settings=db.all_settings(); self.original_rate=float(settings.get("gbp_aed_rate","4.928313")); configs=[("gbp_aed_rate","GBP → AED rate",6),("monthly_spending_cap_gbp","Monthly spending cap · GBP",2),("salary_aed","Guaranteed salary · AED",2),("rent_aed","Accommodation · AED",2),("security_deposit_aed","Refundable deposit · AED",2),("transport_aed","Transport · AED",2),("food_aed","Food estimate · AED",2),("emergency_fund_aed","Protected emergency fund · AED",2)]
        for key,label,decimals in configs: box=MoneyBox(decimals=decimals); box.setValue(float(settings.get(key,0))); self.fields[key]=box; form.addRow(label,box)
        rate_info=QLabel(f"Current snapshot: 1 GBP = {self.original_rate:.6f} AED\nSource: {settings.get('gbp_aed_rate_source','Manual')} · Updated {settings.get('gbp_aed_rate_updated_at','—')}\nGBP equivalents are calculated as AED ÷ this rate."); rate_info.setObjectName("muted"); rate_info.setWordWrap(True); form.addRow("Rate details",rate_info)
        self.quote=QLineEdit(settings.get("quote","")); self.why=QTextEdit(settings.get("why_i_moved","")); self.why.setMaximumHeight(90); form.addRow("Motivational quote",self.quote); form.addRow("Why I moved",self.why); save=QPushButton("Save settings"); save.setProperty("primary",True); save.clicked.connect(self.save); form.addRow(save); tabs.addTab(finance,"Financial assumptions")
        data=QWidget(); dl=QVBoxLayout(data); dl.setContentsMargins(18,18,18,18); dl.addWidget(QLabel(f"Database\n{db.path}")); dl.addWidget(QLabel(f"Receipts\n{db.receipts_dir}"));
        for label,callback in [("Create portable backup",self.backup),("Create encrypted backup",lambda:self.backup(True)),("Restore backup",self.restore),("Database health check",self.health),("Open local data folder",self.open_folder),("Reset demo data",self.reset_demo)]: btn=QPushButton(label); btn.clicked.connect(callback); dl.addWidget(btn)
        privacy=QLabel("PRIVACY GUARANTEE\n\nDXB RUNWAY contains no analytics, telemetry, account system or network code. Manual exchange rates prevent hidden external requests. Receipt files never leave this machine unless you explicitly include them in a portable backup."); privacy.setWordWrap(True); privacy.setObjectName("muted"); dl.addWidget(privacy); dl.addStretch(); tabs.addTab(data,"Local data & privacy"); outer.addWidget(page_scroll(content))
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
