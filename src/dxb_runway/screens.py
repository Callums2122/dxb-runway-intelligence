from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QDate, QTimer, Qt, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView, QCalendarWidget, QCheckBox, QComboBox, QDateEdit, QDialog, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget
)

from .database import Database
from .dialogs import MoneyBox, PayCardDialog, SellVehicleDialog, TransactionDialog, VehicleDialog
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


def table_item(text: str, alignment: Qt.AlignmentFlag | None = None, color: str | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if alignment: item.setTextAlignment(alignment)
    if color: item.setForeground(QColor(color))
    return item


class Page(QWidget):
    changed = Signal()
    def __init__(self, db: Database): super().__init__(); self.db = db
    def refresh(self) -> None: pass


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
        return position, {"settings":settings,"rate":rate,"income":money(income),"expense":money(expense),"cash_out":money(cash_out),"tx":tx,"all":all_tx,"runway":operating_runway,"actual_runway":actual_runway,"operating_position":operating_position,"setup_adjustment":money(setup_adjustment),"next_salary":next_salary,"budget_source":budget_source,"income_source":income_source,"salary_date_source":salary_date_source,"minimum_cards":money(minimum_cards_aed)}

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
            for col, item in enumerate([row["occurred_at"][:10], row["merchant"] or "—", row["category"] or "—", f"{primary}\n{secondary}"]): self.recent.setItem(i,col,table_item(str(item), Qt.AlignmentFlag.AlignRight if col==3 else None, color if col==3 else None))
        self.recent.resizeColumnsToContents(); self.recent.horizontalHeader().setStretchLastSection(True)


class VehicleDeskPage(Page):
    def __init__(self, db: Database):
        super().__init__(db); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); root=QVBoxLayout(content); root.setContentsMargins(24,22,24,28); root.setSpacing(15)
        top=QHBoxLayout(); top.addWidget(SectionHeader("Vehicle desk","Current stock and monthly sold performance, connected directly to the commission tiers.")); top.addStretch(); self.month=QDateEdit(QDate.currentDate()); self.month.setCalendarPopup(True); self.month.setDisplayFormat("MMMM yyyy"); self.month.dateChanged.connect(self.refresh); top.addWidget(self.month); root.addLayout(top)
        controls=Card(); control_grid=QGridLayout(controls); control_grid.setContentsMargins(16,14,16,14); self.budget=MoneyBox(); self.budget.setValue(3_000_000); save_budget=QPushButton("Save month budget"); save_budget.clicked.connect(self.save_budget); self.all_stock=QCheckBox("Show all current stock, including earlier purchase months"); self.all_stock.toggled.connect(self.refresh)
        control_grid.addWidget(QLabel("ASSIGNED PURCHASING BUDGET · AED"),0,0); self.budget_remaining=QLabel(); self.budget_remaining.setToolTip("Assigned purchasing budget minus the purchase cost of every vehicle bought in the selected month, including vehicles already sold."); control_grid.addWidget(self.budget_remaining,0,1,1,2); control_grid.addWidget(self.budget,1,0); control_grid.addWidget(save_budget,1,1); control_grid.addWidget(self.all_stock,1,2); root.addWidget(controls)
        metrics=QGridLayout(); metrics.setSpacing(12); self.metrics={}
        for i,(key,label,color) in enumerate([("stock","Cars in stock",COLORS["cyan"]),("expected","Expected stock profit",COLORS["purple"]),("sold","Sold this month",COLORS["green"]),("profit","Realised profit",COLORS["green"]),("commission","Commission earned",COLORS["green"])]):
            card=MetricCard(label,accent=color); self.metrics[key]=card; metrics.addWidget(card,0,i)
        root.addLayout(metrics)
        tier_card=Card(); tier_layout=QVBoxLayout(tier_card); tier_layout.setContentsMargins(18,15,18,15); tier_top=QHBoxLayout(); self.tier=QLabel("BASELINE · 4%"); self.tier.setStyleSheet(f"font-size:20px;font-weight:800;color:{COLORS['cyan']}"); tier_top.addWidget(self.tier); tier_top.addStretch(); self.achievement=QLabel(); self.achievement.setObjectName("muted"); tier_top.addWidget(self.achievement); tier_layout.addLayout(tier_top); self.schedule=QLabel(); self.schedule.setObjectName("muted"); self.schedule.setWordWrap(True); tier_layout.addWidget(self.schedule); self.tier_progress=QProgressBar(); tier_layout.addWidget(self.tier_progress); root.addWidget(tier_card)
        sections=QHBoxLayout(); sections.setSpacing(12)
        stock_card=Card(); stock_layout=QVBoxLayout(stock_card); stock_layout.setContentsMargins(16,15,16,15); stock_head=QHBoxLayout(); stock_head.addWidget(SectionHeader("Current stock","Defaults to vehicles purchased in the selected month.")); stock_head.addStretch(); add=QPushButton("＋ Add car"); add.setProperty("primary",True); add.clicked.connect(self.add_vehicle); stock_head.addWidget(add); move=QPushButton("Move selected → Sold"); move.clicked.connect(self.sell_selected); stock_head.addWidget(move); stock_layout.addLayout(stock_head)
        self.stock_table=QTableWidget(0,4); self.stock_table.setHorizontalHeaderLabels(["VEHICLE","BOUGHT","COST","EXPECTED PROFIT"]); self.stock_table.setWordWrap(True); self.stock_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.stock_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.stock_table.verticalHeader().hide(); self.stock_table.horizontalHeader().setStretchLastSection(True); self.stock_table.doubleClicked.connect(self.sell_selected); stock_layout.addWidget(self.stock_table); sections.addWidget(stock_card,1)
        sold_card=Card(); sold_layout=QVBoxLayout(sold_card); sold_layout.setContentsMargins(16,15,16,15); sold_head=QHBoxLayout(); sold_head.addWidget(SectionHeader("Sold in selected month","The view resets with each month; all earlier months remain available above.")); sold_head.addStretch(); undo=QPushButton("Return selected to stock"); undo.clicked.connect(self.return_selected); sold_head.addWidget(undo); sold_layout.addLayout(sold_head)
        self.sold_table=QTableWidget(0,4); self.sold_table.setHorizontalHeaderLabels(["VEHICLE","SOLD","REALISED PROFIT","COMMISSION"]); self.sold_table.setWordWrap(True); self.sold_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.sold_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.sold_table.verticalHeader().hide(); self.sold_table.horizontalHeader().setStretchLastSection(True); sold_layout.addWidget(self.sold_table); sections.addWidget(sold_card,1); root.addLayout(sections,1)
        foot=QLabel("Commission is an estimate. When the month crosses a tier, the new rate is applied to the full realised eligible profit for that month immediately."); foot.setObjectName("muted"); foot.setWordWrap(True); root.addWidget(foot); outer.addWidget(page_scroll(content)); self.system_month=QDate.currentDate().toString("yyyy-MM"); self.month_timer=QTimer(self); self.month_timer.setInterval(60_000); self.month_timer.timeout.connect(self.check_month_rollover); self.month_timer.start(); self.refresh()

    def check_month_rollover(self)->None:
        new_month=QDate.currentDate().toString("yyyy-MM")
        if new_month!=self.system_month and self.month.date().toString("yyyy-MM")==self.system_month:
            self.month.setDate(QDate.currentDate())
        self.system_month=new_month

    def selected_id(self, table: QTableWidget) -> int | None:
        row=table.currentRow()
        if row<0 or not table.item(row,0): return None
        value=table.item(row,0).data(Qt.ItemDataRole.UserRole); return int(value) if value is not None else None

    def refresh(self)->None:
        month=self.month.date().toString("yyyy-MM"); year=self.month.date().year(); month_number=self.month.date().month(); rate=Decimal(self.db.get_setting("gbp_aed_rate","4.928313")); budget=self.db.performance_budget(month); purchased_total=self.db.monthly_vehicle_purchase_total(month); remaining_budget=money(budget-purchased_total)
        self.budget.blockSignals(True); self.budget.setValue(float(budget)); self.budget.blockSignals(False)
        remaining_aed,remaining_gbp=dual_amount(remaining_budget,rate); remaining_color=COLORS["red"] if remaining_budget<0 else COLORS["amber"] if budget>0 and remaining_budget/budget<Decimal("0.15") else COLORS["green"]; self.budget_remaining.setText(f"BUDGET REMAINING  ·  {remaining_aed}  /  {remaining_gbp}"); self.budget_remaining.setStyleSheet(f"color:{remaining_color};font-weight:800")
        stock=self.db.stock_vehicles(None if self.all_stock.isChecked() else month); sold=self.db.sold_vehicles(month); expected=sum((Decimal(str(row["expected_profit_aed"])) for row in stock),Decimal("0")); realised=sum((Decimal(str(row["realised_profit_aed"])) for row in sold),Decimal("0")); result=calculate_earnings(year=year,month=month_number,budget_aed=budget,eligible_profit_aed=max(Decimal("0"),realised),average_margin_aed=24700)
        rate_pct=f"{float(result.rate*100):g}%"; self.current_result=result; self.metrics["stock"].set_value(str(len(stock)),"All unsold vehicles" if self.all_stock.isChecked() else f"Purchased in {self.month.date().toString('MMMM yyyy')}"); expected_aed,expected_gbp=dual_amount(expected,rate,signed=True); self.metrics["expected"].set_value(expected_aed,expected_gbp); self.metrics["sold"].set_value(str(len(sold)),self.month.date().toString("MMMM yyyy")); profit_aed,profit_gbp=dual_amount(realised,rate,signed=True); self.metrics["profit"].set_value(profit_aed,profit_gbp,COLORS["red"] if realised<0 else COLORS["green"]); commission_aed,commission_gbp=dual_amount(result.commission_aed,rate); self.metrics["commission"].set_value(commission_aed,f"{commission_gbp} · {result.tier.value} at {rate_pct}")
        tier_color=COLORS["green"] if result.tier!=CommissionTier.BASELINE else COLORS["cyan"]; self.tier.setText(f"{result.tier.value.upper()} · {rate_pct}"); self.tier.setStyleSheet(f"font-size:20px;font-weight:800;color:{tier_color}")
        t3,t2,t1=TARGET_PERCENTAGES[month_number]; achieved=(realised/budget*100) if budget>0 else Decimal("0"); self.achievement.setText(f"Profit achieved · {achieved:.2f}% of purchasing budget"); self.schedule.setText(f"{self.month.date().toString('MMMM')} targets · Tier 3 {float(t3*100):g}%  ·  Tier 2 {float(t2*100):g}%  ·  Tier 1 {float(t1*100):g}%"+(f"  ·  Next tier in AED {result.distance_to_next_aed:,.0f}" if result.next_tier else "  ·  Highest tier reached")); self.tier_progress.setRange(0,max(1,int(t1*10000))); self.tier_progress.setValue(max(0,min(self.tier_progress.maximum(),int(achieved*100))))
        self.stock_table.setRowCount(len(stock))
        for i,row in enumerate(stock):
            self.stock_table.setRowHeight(i,56); first=table_item(row["vehicle_name"]); first.setData(Qt.ItemDataRole.UserRole,row["id"]); first.setToolTip(f"Expected sale · AED {row['expected_sale_price_aed']:,.0f}"); self.stock_table.setItem(i,0,first); purchase_aed=Decimal(str(row["purchase_price_aed"])); profit_aed=Decimal(str(row["expected_profit_aed"])); values=[row["purchased_date"],f"{purchase_aed:,.0f} AED\n{gbp_equivalent(purchase_aed,rate):,.0f} GBP",f"{profit_aed:+,.0f} AED\n{gbp_equivalent(profit_aed,rate):+,.0f} GBP"]
            for j,value in enumerate(values,1): self.stock_table.setItem(i,j,table_item(value,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight,color=COLORS["green"] if j==3 and row["expected_profit_aed"]>=0 else COLORS["red"] if j==3 else None))
        self.stock_table.setColumnWidth(0,120); self.stock_table.setColumnWidth(1,95); self.stock_table.setColumnWidth(2,125); self.stock_table.horizontalHeader().setStretchLastSection(True)
        self.sold_table.setRowCount(len(sold))
        for i,row in enumerate(sold):
            self.sold_table.setRowHeight(i,56); first=table_item(row["vehicle_name"]); first.setData(Qt.ItemDataRole.UserRole,row["id"]); first.setToolTip(f"Sale price · AED {row['sold_price_aed']:,.0f}"); self.sold_table.setItem(i,0,first); profit=Decimal(str(row["realised_profit_aed"])); commission=money(profit*result.rate) if realised>0 else Decimal("0"); values=[row["sold_date"],f"{profit:+,.0f} AED\n{gbp_equivalent(profit,rate):+,.0f} GBP",f"{commission:+,.0f} AED\n{gbp_equivalent(commission,rate):+,.0f} GBP"]
            for j,value in enumerate(values,1): self.sold_table.setItem(i,j,table_item(value,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight,color=COLORS["green"] if j in {2,3} and profit>=0 else COLORS["red"] if j in {2,3} else None))
        self.sold_table.setColumnWidth(0,120); self.sold_table.setColumnWidth(1,95); self.sold_table.setColumnWidth(2,150); self.sold_table.horizontalHeader().setStretchLastSection(True)

    def save_budget(self)->None:
        self.db.set_performance_budget(self.month.date().toString("yyyy-MM"),self.budget.value()); self.refresh(); self.changed.emit()

    def add_vehicle(self)->None:
        dialog=VehicleDialog(self.db,self)
        if dialog.exec(): self.db.add_vehicle(**dialog.values()); self.refresh(); self.changed.emit()

    def sell_selected(self)->None:
        vehicle_id=self.selected_id(self.stock_table)
        if vehicle_id is None: QMessageBox.information(self,"Select a car","Select a vehicle from current stock first."); return
        rows=self.db.query("SELECT * FROM vehicles WHERE id=? AND status='stock'",(vehicle_id,))
        if not rows: QMessageBox.warning(self,"No longer in stock","That vehicle is no longer available in stock."); self.refresh(); return
        dialog=SellVehicleDialog(rows[0],self)
        if dialog.exec(): self.db.sell_vehicle(vehicle_id,**dialog.values()); sold_date=dialog.values()["sold_date"]; self.month.setDate(QDate.fromString(sold_date,"yyyy-MM-dd")); self.refresh(); self.changed.emit()

    def return_selected(self)->None:
        vehicle_id=self.selected_id(self.sold_table)
        if vehicle_id is None: QMessageBox.information(self,"Select a car","Select a sold vehicle first."); return
        if QMessageBox.question(self,"Return to stock","Move this vehicle back to current stock and remove its profit from this month?")==QMessageBox.StandardButton.Yes: self.db.return_vehicle_to_stock(vehicle_id); self.refresh(); self.changed.emit()


class TransactionsPage(Page):
    def __init__(self, db: Database):
        super().__init__(db); self.last_deleted: int | None = None
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 22, 24, 24); layout.setSpacing(14)
        top = QHBoxLayout(); titles = QVBoxLayout(); title = QLabel("Transactions"); title.setObjectName("pageTitle"); titles.addWidget(title); sub = QLabel("Every cash movement, with local receipts and reversible deletion."); sub.setObjectName("muted"); titles.addWidget(sub); top.addLayout(titles); top.addStretch()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search merchant, category or tag…"); self.search.setMaximumWidth(320); self.search.textChanged.connect(self.refresh); top.addWidget(self.search)
        add = QPushButton("＋ Add transaction"); add.setProperty("primary", True); add.clicked.connect(self.add); top.addWidget(add); layout.addLayout(top)
        tools = QHBoxLayout(); self.filter = QComboBox(); self.filter.addItems(["All types", "Highlighted", "Setup costs", "Expenses", "Income", "Essential", "Discretionary", "Credit card"]); self.filter.currentTextChanged.connect(self.refresh); tools.addWidget(self.filter)
        for label, callback in [("Pay credit card", self.pay_card), ("Import CSV", self.import_csv), ("Export CSV", self.export_csv), ("★ Highlight", self.toggle_highlight), ("Setup cost", self.toggle_setup_cost), ("Edit", self.edit), ("Delete", self.delete), ("Undo delete", self.undo)]: btn=QPushButton(label); btn.clicked.connect(callback); tools.addWidget(btn)
        tools.addStretch(); self.summary = QLabel(); self.summary.setObjectName("muted"); tools.addWidget(self.summary); layout.addLayout(tools)
        self.table = QTableWidget(0, 8); self.table.setHorizontalHeaderLabels(["DATE", "TYPE", "MERCHANT", "CATEGORY", "METHOD", "FLAGS", "TAGS", "AMOUNT"]); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.doubleClicked.connect(self.edit); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.table,1); self.refresh()

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
            flags = " · ".join(x for x in ["★ Highlighted" if row["highlighted"] else "", "Setup cost" if row["budget_excluded"] else "", row["credit_card_name"] or "" if row["card_effect"] else "", "Card payment" if row["card_effect"]==-1 else "", "Recurring" if row["recurring"] else "", "Essential" if row["essential"] else "Discretionary", "Deposit" if row["refundable_deposit"] else "", "Receipt" if row["receipt_path"] else ""] if x)
            amount_aed = to_aed(row["amount"],row["currency"],rate)*(1 if row["kind"]=="income" else -1); total += amount_aed
            primary,secondary=dual_amount(amount_aed,rate,2,True)
            values=[row["occurred_at"][:16].replace("T","  "),row["kind"].title(),row["merchant"] or "—",row["category"] or "—",row["payment_method"],flags,row["tags"],f"{primary}\n{secondary}"]
            for j,value in enumerate(values):
                item=table_item(str(value),Qt.AlignmentFlag.AlignRight if j==7 else None,COLORS["green"] if amount_aed>0 and j==7 else COLORS["text"] if j==7 else None)
                if row["highlighted"]: item.setBackground(QColor("#382c16")); item.setToolTip("Highlighted reminder"+(f" · {row['notes']}" if row["notes"] else ""))
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
    def __init__(self,db:Database):
        super().__init__(db); layout=QVBoxLayout(self); layout.setContentsMargins(24,22,24,24); layout.setSpacing(14); top=QHBoxLayout(); top.addWidget(SectionHeader("Budget system","Monthly category plans, essential/discretionary separation and threshold warnings.")); top.addStretch(); self.month=QDateEdit(QDate.currentDate()); self.month.setDisplayFormat("MMMM yyyy"); self.month.dateChanged.connect(self.refresh); top.addWidget(self.month); survival=QPushButton("Show survival budget"); survival.clicked.connect(self.survival); top.addWidget(survival); layout.addLayout(top)
        self.table=QTableWidget(0,8); self.table.setHorizontalHeaderLabels(["CATEGORY","MODE","PLANNED · AED","≈ GBP","ACTUAL","REMAINING","USED","ROLLOVER"]); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.table,1); save=QPushButton("Save budget plan"); save.setProperty("primary",True); save.clicked.connect(self.save); layout.addWidget(save); self.refresh()
    def refresh(self)->None:
        month=self.month.date().toString("yyyy-MM"); cats=self.db.query("SELECT * FROM categories WHERE kind='expense' ORDER BY essential_default DESC,name"); rate=self.db.get_setting("gbp_aed_rate","4.928313"); tx=self.db.transactions(month=month,limit=100000); actual={}
        for row in tx:
            if row["kind"]=="expense" and not row["refundable_deposit"] and not row["budget_excluded"]: actual[row["category_id"]]=actual.get(row["category_id"],Decimal(0))+to_aed(row["amount"],row["currency"],rate)
        planned={row["category_id"]:row for row in self.db.query("SELECT * FROM budgets WHERE month=?",(month,))}; self.table.setRowCount(len(cats))
        defaults={"Accommodation":float(self.db.get_setting("rent_aed","4500")),"Transport":float(self.db.get_setting("transport_aed","2000")),"Groceries":float(self.db.get_setting("food_aed","1250"))}
        for i,cat in enumerate(cats):
            self.table.setRowHeight(i,48); self.table.setVerticalHeaderItem(i,QTableWidgetItem(str(cat["id"]))); self.table.setItem(i,0,table_item(cat["name"])); self.table.setItem(i,1,table_item("Essential" if cat["essential_default"] else "Discretionary",color=COLORS["green"] if cat["essential_default"] else COLORS["purple"])); spin=MoneyBox(); spin.setValue(planned[cat["id"]]["planned_aed"] if cat["id"] in planned else defaults.get(cat["name"],cat["monthly_limit_aed"])); self.table.setCellWidget(i,2,spin); planned_gbp=table_item(f"GBP {gbp_equivalent(spin.value(),rate):,.0f}"); self.table.setItem(i,3,planned_gbp); spin.valueChanged.connect(lambda value,item=planned_gbp,current_rate=rate:item.setText(f"GBP {gbp_equivalent(value,current_rate):,.0f}")); act=float(actual.get(cat["id"],0)); remain=spin.value()-act; used=int(act/spin.value()*100) if spin.value() else 0; actual_aed,actual_gbp=dual_amount(act,rate); remain_aed,remain_gbp=dual_amount(remain,rate,signed=True); self.table.setItem(i,4,table_item(f"{actual_aed}\n{actual_gbp}")); self.table.setItem(i,5,table_item(f"{remain_aed}\n{remain_gbp}",color=COLORS["red"] if remain<0 else COLORS["green"])); self.table.setItem(i,6,table_item(f"{used}%",color=COLORS["red"] if used>=100 else COLORS["amber"] if used>=70 else COLORS["green"])); roll=QCheckBox(); roll.setChecked(bool(planned[cat["id"]]["rollover"]) if cat["id"] in planned else False); self.table.setCellWidget(i,7,roll)
        self.table.setColumnWidth(0,160); self.table.setColumnWidth(2,145); self.table.setColumnWidth(3,100); self.table.horizontalHeader().setStretchLastSection(True)
    def save(self)->None:
        month=self.month.date().toString("yyyy-MM")
        for i in range(self.table.rowCount()): cat=int(self.table.verticalHeaderItem(i).text()); planned=self.table.cellWidget(i,2).value(); rollover=int(self.table.cellWidget(i,7).isChecked()); self.db.execute("INSERT INTO budgets(month,category_id,planned_aed,rollover) VALUES (?,?,?,?) ON CONFLICT(month,category_id) DO UPDATE SET planned_aed=excluded.planned_aed,rollover=excluded.rollover",(month,cat,planned,rollover))
        QMessageBox.information(self,"Budget saved",f"Budget plan saved for {month}."); self.refresh(); self.changed.emit()
    def survival(self)->None:
        for i in range(self.table.rowCount()):
            if self.table.item(i,1).text()=="Discretionary": self.table.cellWidget(i,2).setValue(0)
        QMessageBox.information(self,"Survival budget","All discretionary category plans have been set to zero. Save to keep this version.")


class CalendarPage(Page):
    def __init__(self,db:Database):
        super().__init__(db); layout=QHBoxLayout(self); layout.setContentsMargins(24,22,24,24); left=QVBoxLayout(); left.addWidget(SectionHeader("Financial calendar","Salary, rent, card, commission and custom reminder dates.")); self.calendar=QCalendarWidget(); self.calendar.selectionChanged.connect(self.refresh_events); left.addWidget(self.calendar,1); add=QPushButton("＋ Add reminder"); add.setProperty("primary",True); add.clicked.connect(self.add); left.addWidget(add); layout.addLayout(left,2); side=Card(); side_l=QVBoxLayout(side); side_l.setContentsMargins(18,18,18,18); self.day=QLabel(); self.day.setStyleSheet("font-size:18px;font-weight:700"); side_l.addWidget(self.day); self.events=QVBoxLayout(); side_l.addLayout(self.events); side_l.addStretch(); layout.addWidget(side,1); self.refresh()
    def refresh(self)->None:
        self.calendar.setDateTextFormat(QDate(),QTextCharFormat()); rows=self.db.query("SELECT * FROM reminders WHERE completed=0")+self.db.query("SELECT 'Commission payment' title,payment_date event_date,'commission' event_type,'' notes,0 completed,id FROM earnings WHERE received=0")
        colors={"salary":COLORS["green"],"commission":COLORS["purple"],"rent":COLORS["amber"],"card":COLORS["red"],"subscription":COLORS["cyan"]}
        for row in rows:
            qdate=QDate.fromString(row["event_date"],"yyyy-MM-dd"); fmt=QTextCharFormat(); fmt.setBackground(QColor(colors.get(row["event_type"],COLORS["cyan"]))); fmt.setForeground(QColor("#071016")); fmt.setFontWeight(QFont.Weight.Bold); self.calendar.setDateTextFormat(qdate,fmt)
        self.refresh_events()
    def refresh_events(self)->None:
        clear_layout(self.events); selected=self.calendar.selectedDate().toString("yyyy-MM-dd"); self.day.setText(self.calendar.selectedDate().toString("dddd, d MMMM")); rows=self.db.query("SELECT * FROM reminders WHERE event_date=?",(selected,))+self.db.query("SELECT 'Commission payment' title,payment_date event_date,'commission' event_type,'' notes,0 completed,id FROM earnings WHERE payment_date=? AND received=0",(selected,))
        if not rows: label=QLabel("No financial events"); label.setObjectName("muted"); self.events.addWidget(label)
        for row in rows:
            card=QFrame(); card.setProperty("card",True); lay=QVBoxLayout(card); title=QLabel(row["title"]); title.setStyleSheet("font-weight:700"); lay.addWidget(title); meta=QLabel(str(row["event_type"]).upper()); meta.setObjectName("eyebrow"); lay.addWidget(meta); self.events.addWidget(card)
    def add(self)->None:
        title,ok=QInputDialog.getText(self,"New reminder","Title")
        if ok and title.strip(): self.db.execute("INSERT INTO reminders(title,event_date,event_type) VALUES (?,?,?)",(title.strip(),self.calendar.selectedDate().toString("yyyy-MM-dd"),"custom")); self.refresh(); self.changed.emit()


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
        super().__init__(db); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); root=QVBoxLayout(content); root.setContentsMargins(24,22,24,28); root.setSpacing(16); root.addWidget(SectionHeader("Settings & data","All settings and data stay in Windows AppData. No telemetry, accounts or network requests.")); tabs=QTabWidget(); root.addWidget(tabs)
        finance=QWidget(); form=QFormLayout(finance); self.fields={}; settings=db.all_settings(); self.original_rate=float(settings.get("gbp_aed_rate","4.928313")); configs=[("gbp_aed_rate","GBP → AED rate",6),("salary_aed","Guaranteed salary · AED",2),("rent_aed","Accommodation · AED",2),("security_deposit_aed","Refundable deposit · AED",2),("transport_aed","Transport · AED",2),("food_aed","Food estimate · AED",2),("emergency_fund_aed","Protected emergency fund · AED",2)]
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
            for table in ("transactions","earnings","credit_cards","reminders","budgets","vehicles","performance_months"): self.db.execute(f"DELETE FROM {table}")
            self.db.seed_demo(); self.changed.emit(); QMessageBox.information(self,"Demo reset","Representative local demo data has been loaded.")
