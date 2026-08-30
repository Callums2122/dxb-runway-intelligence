from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTableWidget, QVBoxLayout, QWidget

from .database import Database
from .domain import TARGET_PERCENTAGES
from .growth_logic import attribution_for_vehicle, rescue_options, stock_heat, tier_scenarios
from .screens import Page, monthly_kpi_adjustment, page_scroll, table_item, vehicle_margin_percent, vehicle_model_name, vehicle_speed_grade, vehicle_grade_color
from .style import COLORS
from .widgets import Card, MetricCard, SectionHeader


class ProfitRescuePage(Page):
    def __init__(self, db: Database):
        super().__init__(db); content=QWidget(); root=QVBoxLayout(content); root.setContentsMargins(24,22,24,28); root.setSpacing(14)
        head=QHBoxLayout(); head.addWidget(SectionHeader("Profit Rescue Engine","Find the smallest price action that protects margin while releasing trapped budget.")); head.addStretch(); button=QPushButton("↻ Recalculate"); button.setProperty("primary",True); button.clicked.connect(self.refresh); head.addWidget(button); root.addLayout(head)
        metrics=QGridLayout(); self.metrics={"urgent":MetricCard("Needs rescue",accent=COLORS["red"]),"protected":MetricCard("Healthy / hot",accent=COLORS["green"]),"release":MetricCard("Potential budget release",accent=COLORS["cyan"])}
        for index,card in enumerate(self.metrics.values()): metrics.addWidget(card,0,index)
        root.addLayout(metrics)
        root.addWidget(SectionHeader("Recommended action","Recommendations use stock age, Deal Drive exit forecast, appointment demand and expected margin. They never change a price automatically."))
        self.table=QTableWidget(0,9); self.table.setHorizontalHeaderLabels(["VEHICLE","HEAT","DAYS HELD","CURRENT PRICE","ACTION","NEW PRICE","PROFIT AFTER","MARGIN AFTER","WHY"]); self.table.setWordWrap(True); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); root.addWidget(self.table)
        outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.addWidget(page_scroll(content)); self.refresh()

    def refresh(self)->None:
        rows=self.db.stock_vehicles(); appointment_counts={int(row["matched_vehicle_id"]):int(row["n"]) for row in self.db.query("SELECT matched_vehicle_id,COUNT(*) n FROM pipeline_appointments WHERE matched_vehicle_id IS NOT NULL AND appointment_date>=date('now') GROUP BY matched_vehicle_id")}
        results=[]
        for row in rows:
            count=appointment_counts.get(int(row["id"]),0); heat=stock_heat(row,count); options=rescue_options(row,count); chosen=next(option for option in options if option["recommended"]); results.append((row,heat,chosen))
        results.sort(key=lambda item:(item[1]["score"],-item[1]["days_held"])); urgent=sum(item[1]["label"] in {"NEEDS ACTION","CAPITAL TRAPPED"} for item in results); protected=len(results)-urgent; release=sum(float(item[0]["purchase_price_aed"] or 0) for item in results if item[1]["label"]=="CAPITAL TRAPPED" and item[0]["purchase_type"]=="cash")
        self.metrics["urgent"].set_value(str(urgent),"Orange/red stock requiring a decision",COLORS["red"] if urgent else COLORS["green"]); self.metrics["protected"].set_value(str(protected),"No immediate reduction recommended"); self.metrics["release"].set_value(f"AED {release:,.0f}","Cash unlocked if trapped vehicles exit")
        self.table.setRowCount(len(results))
        for i,(row,heat,option) in enumerate(results):
            reduction=option["reduction"]; action="HOLD PRICE" if reduction==0 else f"TEST -AED {reduction:,.0f}"
            values=[row["vehicle_name"],f"{heat['icon']} {heat['score']}/100\n{heat['label']}",str(heat["days_held"]),f"AED {float(row['expected_sale_price_aed']):,.0f}",action,f"AED {option['sale']:,.0f}",f"AED {option['profit']:+,.0f}",f"{option['margin']:.1%}",heat["evidence"]]
            self.table.setRowHeight(i,62)
            for j,value in enumerate(values): self.table.setItem(i,j,table_item(str(value),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight if j in {2,3,5,6,7} else Qt.AlignmentFlag.AlignVCenter,COLORS["green"] if j==1 and heat["score"]>=60 else COLORS["amber"] if j in {1,4} and heat["score"]>=40 else COLORS["red"] if j in {1,4} else None))
        for column,width in enumerate([160,125,80,115,120,115,115,90]): self.table.setColumnWidth(column,width)


class TierOneSimulatorPage(Page):
    def __init__(self, db: Database):
        super().__init__(db); content=QWidget(); root=QVBoxLayout(content); root.setContentsMargins(24,22,24,28); root.setSpacing(14)
        head=QHBoxLayout(); head.addWidget(SectionHeader("Tier 1 Simulator","A live route from realised profit and current stock to each commission tier.")); head.addStretch(); button=QPushButton("↻ Run simulation"); button.setProperty("primary",True); button.clicked.connect(self.refresh); head.addWidget(button); root.addLayout(head)
        self.summary=QLabel(); self.summary.setObjectName("muted"); self.summary.setWordWrap(True); root.addWidget(self.summary)
        self.cards=QGridLayout(); self.tier_cards={}
        for index,(key,label,color) in enumerate((("t3","Tier 3 route",COLORS["cyan"]),("t2","Tier 2 route",COLORS["purple"]),("t1","Tier 1 route",COLORS["green"]))): card=MetricCard(label,accent=color); self.tier_cards[key]=card; self.cards.addWidget(card,0,index)
        root.addLayout(self.cards)
        route=Card(); box=QVBoxLayout(route); box.setContentsMargins(18,16,18,16); box.addWidget(SectionHeader("Best route using current stock","Vehicles are ordered by heat score and expected profit. This is a planning scenario—not a promise that every car sells.")); self.table=QTableWidget(0,7); self.table.setHorizontalHeaderLabels(["TIER","TARGET %","PROFIT REQUIRED","GAP NOW","STOCK PROFIT USED","LIKELIHOOD","CARS NEEDED"]); self.table.setWordWrap(True); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True); box.addWidget(self.table); root.addWidget(route)
        outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.addWidget(page_scroll(content)); self.refresh()

    def refresh(self)->None:
        month=date.today().strftime("%Y-%m"); budget=self.db.performance_budget(month); sold=self.db.sold_vehicles(month); realised=sum((Decimal(str(row["realised_profit_aed"])) for row in sold),Decimal("0")); hits,reduction=monthly_kpi_adjustment(self.db,month); targets=tuple(max(Decimal("0"),target-reduction) for target in TARGET_PERCENTAGES[date.today().month]); scenarios=tier_scenarios(self.db.stock_vehicles(),realised,targets,budget)
        expected=sum(Decimal(str(row["expected_profit_aed"])) for row in self.db.stock_vehicles()); self.summary.setText(f"AED {realised:,.0f} realised · AED {expected:,.0f} expected in live stock · AED {budget:,.0f} budget · {hits} KPI hit{'s' if hits!=1 else ''} reduce live tier goals by {reduction*100:g}%")
        for key,scenario in zip(("t3","t2","t1"),scenarios):
            color=COLORS["green"] if scenario["likelihood"]=="LIKELY" else COLORS["amber"] if scenario["likelihood"]=="ACHIEVABLE" else COLORS["red"]
            self.tier_cards[key].set_value(scenario["likelihood"],f"AED {scenario['gap']:,.0f} gap · {scenario['target']*100:g}% adjusted target",color)
        self.table.setRowCount(3)
        for i,scenario in enumerate(scenarios):
            cars=" → ".join(scenario["cars"]) if scenario["cars"] else "Already achieved"
            values=[scenario["tier"],f"{scenario['target']*100:g}%",f"AED {scenario['required']:,.0f}",f"AED {scenario['gap']:,.0f}",f"AED {scenario['projected']:,.0f}",scenario["likelihood"],cars]
            self.table.setRowHeight(i,62)
            for j,value in enumerate(values): self.table.setItem(i,j,table_item(str(value),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight if j in {1,2,3,4} else Qt.AlignmentFlag.AlignVCenter,COLORS["green"] if j==5 and scenario["likelihood"]=="LIKELY" else COLORS["amber"] if j==5 and scenario["likelihood"]=="ACHIEVABLE" else COLORS["red"] if j==5 else None))
        for column,width in enumerate([80,85,125,115,135,105]): self.table.setColumnWidth(column,width)
