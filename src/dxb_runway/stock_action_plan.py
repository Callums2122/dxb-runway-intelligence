from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .database import Database
from .screens import Page, page_scroll
from .style import COLORS
from .widgets import Card, MetricCard, RingWidget, SectionHeader, clear_layout


def _number(row: Any, key: str) -> float:
    try:
        return float(row[key] or 0)
    except (KeyError, TypeError, ValueError):
        return 0.0


def _days_held(row: Any, today: date) -> int:
    try:
        return max(0, (today - date.fromisoformat(str(row["purchased_date"])[:10])).days)
    except (KeyError, TypeError, ValueError):
        return 0


def _make(vehicle: str) -> str:
    words = str(vehicle).replace("-", " ").split()
    if words and words[0].isdigit() and len(words) > 1:
        words = words[1:]
    return words[0].title() if words else "Unknown"


def _bracket(price: float) -> str:
    if price < 100_000: return "Under AED 100k"
    if price < 200_000: return "AED 100–200k"
    if price < 350_000: return "AED 200–350k"
    return "AED 350k+"


def calculate_stock_action_plan(rows: Iterable[Any], budget_aed: float, today: date | None = None) -> dict[str, Any]:
    """Build a transparent, deterministic action plan from current stock only."""
    today = today or date.today(); stock = list(rows); budget = max(0.0, float(budget_aed))
    cash = [r for r in stock if str(r["purchase_type"]) == "cash"]
    invested = sum(_number(r, "purchase_price_aed") for r in cash)
    expected_profit = sum(_number(r, "expected_profit_aed") for r in stock)
    expected_sales = sum(_number(r, "expected_sale_price_aed") for r in stock)
    utilisation = invested / budget if budget else 0.0

    researched = [r for r in stock if _number(r, "deal_drive_estimated_days") > 0]
    fast = [r for r in researched if _number(r, "deal_drive_estimated_days") < 45]
    slow = [r for r in researched if _number(r, "deal_drive_estimated_days") >= 45]
    ageing = [r for r in stock if _days_held(r, today) >= 30]
    critical = [r for r in stock if _days_held(r, today) >= 45]
    unknown = [r for r in stock if _number(r, "deal_drive_estimated_days") <= 0]

    makes = Counter(_make(r["vehicle_name"]) for r in stock)
    brackets = Counter(_bracket(_number(r, "expected_sale_price_aed")) for r in stock)
    top_make, top_make_count = makes.most_common(1)[0] if makes else ("—", 0)
    top_bracket, top_bracket_count = brackets.most_common(1)[0] if brackets else ("—", 0)
    make_share = top_make_count / len(stock) if stock else 0.0
    bracket_share = top_bracket_count / len(stock) if stock else 0.0
    margin = expected_profit / expected_sales if expected_sales else 0.0

    budget_score = 100 if .65 <= utilisation <= .90 else max(20, int(100 - abs(utilisation - .78) * 180))
    turnover_score = int(100 * len(fast) / len(researched)) if researched else 45
    ageing_score = max(0, 100 - len(ageing) * 18 - len(critical) * 17)
    concentration_score = max(0, int(100 - max(0, make_share - .35) * 130 - max(0, bracket_share - .50) * 90))
    margin_score = max(0, min(100, int(margin / .15 * 100)))
    score = round(turnover_score * .30 + ageing_score * .25 + concentration_score * .20 + budget_score * .15 + margin_score * .10)

    candidates: list[dict[str, str]] = []
    def action(priority: str, title: str, detail: str, accent: str) -> None:
        candidates.append({"priority": priority, "title": title, "detail": detail, "accent": accent})

    if critical:
        worst = max(critical, key=lambda r: _days_held(r, today)); days = _days_held(worst, today)
        action("DO NOW", f"Reprice or exit {worst['vehicle_name']}", f"{days} days held. Review price, advert and exit route today.", COLORS["red"])
    elif slow:
        worst = max(slow, key=lambda r: _number(r, "deal_drive_estimated_days"))
        action("HIGH IMPACT", f"Review {worst['vehicle_name']}", f"Deal Drive forecasts about {_number(worst, 'deal_drive_estimated_days'):.0f} days. Tighten the price before it ages.", COLORS["amber"])
    elif ageing:
        worst = max(ageing, key=lambda r: _days_held(r, today))
        action("WATCH", f"Protect the exit on {worst['vehicle_name']}", f"{_days_held(worst, today)} days held; prepare a price action before day 45.", COLORS["amber"])

    if utilisation < .65:
        gap = max(0.0, budget * .75 - invested)
        action("OPPORTUNITY", "Deploy budget into fast stock", f"Only {utilisation:.0%} deployed. Aim roughly AED {gap:,.0f} at proven sub-45-day cars.", COLORS["green"])
    elif utilisation > .95:
        action("PROTECT", "Pause cash buying until an exit", f"{utilisation:.0%} of budget is tied up. Preserve liquidity; use consignment or sell first.", COLORS["red"])
    else:
        action("ON TRACK", "Maintain live budget deployment", f"{utilisation:.0%} deployed. Keep replacing sold cash stock with proven fast movers.", COLORS["green"])

    if make_share > .40:
        action("BALANCE", f"Diversify away from {top_make}", f"{top_make_count} of {len(stock)} vehicles are {top_make}. Make the next buy a different proven brand.", COLORS["purple"])
    elif bracket_share > .55:
        action("BALANCE", f"Reduce {top_bracket} concentration", f"{top_bracket_count} of {len(stock)} vehicles share this price bracket. Spread the next buy.", COLORS["purple"])
    elif unknown:
        action("EVIDENCE", f"Research {unknown[0]['vehicle_name']}", f"{len(unknown)} stock vehicle(s) still lack a Deal Drive speed forecast.", COLORS["cyan"])
    else:
        action("SOURCE", "Add another proven fast mover", f"{len(fast)} researched vehicle(s) are forecast below 45 days. Source from the strongest cohort.", COLORS["cyan"])

    while len(candidates) < 3:
        action("DISCIPLINE", "Protect expected margin", f"Current expected portfolio margin is {margin:.1%}. Avoid buying volume without enough exit profit.", COLORS["cyan"])

    return {
        "score": max(0, min(100, score)), "stock_count": len(stock), "cash_count": len(cash),
        "invested": invested, "expected_profit": expected_profit, "utilisation": utilisation,
        "fast_count": len(fast), "slow_count": len(slow), "unknown_count": len(unknown),
        "ageing_count": len(ageing), "critical_count": len(critical), "margin": margin,
        "top_make": top_make, "top_make_share": make_share, "top_bracket": top_bracket,
        "consignment_count": len(stock) - len(cash), "actions": candidates[:3],
        "factors": [
            ("Turnover mix", turnover_score, f"{len(fast)} fast · {len(slow)} slow · {len(unknown)} awaiting evidence"),
            ("Ageing risk", ageing_score, f"{len(ageing)} at 30+ days · {len(critical)} at 45+ days"),
            ("Stock balance", concentration_score, f"Largest brand share {make_share:.0%} · {top_bracket}"),
            ("Budget deployment", budget_score, f"{utilisation:.0%} of revolving budget deployed"),
            ("Expected margin", margin_score, f"{margin:.1%} of expected selling value"),
        ],
    }


class StockActionPlanPage(Page):
    def __init__(self, db: Database):
        super().__init__(db)
        content = QWidget(); self.layout = QVBoxLayout(content); self.layout.setContentsMargins(20, 18, 20, 28); self.layout.setSpacing(14)
        title = QHBoxLayout(); title.addWidget(SectionHeader("Stock Action Plan", "Live portfolio health plus the three highest-impact moves to make now.")); title.addStretch()
        refresh = QPushButton("↻ Recalculate"); refresh.setProperty("primary", True); refresh.clicked.connect(self.refresh); title.addWidget(refresh); self.layout.addLayout(title)
        hero = Card(); hero_l = QHBoxLayout(hero); hero_l.setContentsMargins(20, 18, 20, 18); hero_l.setSpacing(22)
        self.ring = RingWidget(0, "PORTFOLIO SCORE", COLORS["green"]); hero_l.addWidget(self.ring)
        hero_copy = QVBoxLayout(); self.verdict = QLabel("Calculating…"); self.verdict.setObjectName("heroValue"); hero_copy.addWidget(self.verdict)
        explain = QLabel("The score weighs turnover 30%, ageing 25%, concentration 20%, budget use 15% and margin 10%."); explain.setObjectName("muted"); explain.setWordWrap(True); hero_copy.addWidget(explain); hero_copy.addStretch(); hero_l.addLayout(hero_copy, 1); self.layout.addWidget(hero)
        metrics = QHBoxLayout(); self.metrics = {
            "budget": MetricCard("Budget deployed", accent=COLORS["green"]), "fast": MetricCard("Fast stock", accent=COLORS["cyan"]),
            "slow": MetricCard("Needs action", accent=COLORS["amber"]), "profit": MetricCard("Expected profit", accent=COLORS["purple"]),
        }
        for card in self.metrics.values(): metrics.addWidget(card)
        self.layout.addLayout(metrics)
        self.layout.addWidget(SectionHeader("Today’s 3 priority actions", "Your three highest-impact moves, recalculated from live stock and forecasts."))
        self.actions_host = QWidget(); self.actions_layout = QHBoxLayout(self.actions_host); self.actions_layout.setContentsMargins(0,0,0,0); self.actions_layout.setSpacing(12); self.layout.addWidget(self.actions_host)
        self.layout.addWidget(SectionHeader("Portfolio balance", "Every score shows the evidence behind it—no black box."))
        factors = Card(); self.factor_layout = QVBoxLayout(factors); self.factor_layout.setContentsMargins(18,16,18,16); self.factor_layout.setSpacing(12); self.layout.addWidget(factors)
        self.layout.addStretch(); outer = QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.addWidget(page_scroll(content)); self.refresh()

    def refresh(self) -> None:
        rows = self.db.stock_vehicles(); budget = float(self.db.performance_budget(date.today().strftime("%Y-%m"))); plan = calculate_stock_action_plan(rows, budget)
        score = plan["score"]; color = COLORS["green"] if score >= 75 else COLORS["cyan"] if score >= 60 else COLORS["amber"] if score >= 40 else COLORS["red"]
        label = "TIER 1 READY" if score >= 85 else "STRONG PORTFOLIO" if score >= 70 else "NEEDS ATTENTION" if score >= 50 else "AT RISK"
        self.ring.color = QColor(color); self.ring.set_value(score); self.verdict.setText(label); self.verdict.setStyleSheet(f"color:{color}")
        self.metrics["budget"].set_value(f"{plan['utilisation']:.0%}", f"AED {plan['invested']:,.0f} in unsold cash stock", COLORS["green"] if .65 <= plan["utilisation"] <= .90 else COLORS["amber"])
        self.metrics["fast"].set_value(str(plan["fast_count"]), "Deal Drive forecast below 45 days")
        self.metrics["slow"].set_value(str(plan["slow_count"] + plan["critical_count"]), f"{plan['slow_count']} slow forecast · {plan['critical_count']} held 45+ days", COLORS["red"] if plan["critical_count"] else COLORS["amber"])
        self.metrics["profit"].set_value(f"AED {plan['expected_profit']:,.0f}", f"Expected portfolio margin {plan['margin']:.1%}")
        clear_layout(self.actions_layout)
        for index, item in enumerate(plan["actions"], 1):
            card = Card(); box = QVBoxLayout(card); box.setContentsMargins(16,14,16,16); box.setSpacing(7)
            badge = QLabel(f"#{index}  {item['priority']}"); badge.setObjectName("eyebrow"); badge.setStyleSheet(f"color:{item['accent']};font-weight:800"); box.addWidget(badge)
            heading = QLabel(item["title"]); heading.setObjectName("sectionTitle"); heading.setWordWrap(True); box.addWidget(heading)
            detail = QLabel(item["detail"]); detail.setObjectName("muted"); detail.setWordWrap(True); box.addWidget(detail); box.addStretch(); self.actions_layout.addWidget(card)
        clear_layout(self.factor_layout)
        for name, value, detail in plan["factors"]:
            row = QHBoxLayout(); name_label = QLabel(name); name_label.setMinimumWidth(145); row.addWidget(name_label)
            bar = QProgressBar(); bar.setRange(0,100); bar.setValue(value); bar.setTextVisible(False); row.addWidget(bar,1)
            score_label = QLabel(f"{value}/100"); score_label.setMinimumWidth(55); score_label.setAlignment(Qt.AlignmentFlag.AlignRight); row.addWidget(score_label)
            detail_label = QLabel(detail); detail_label.setObjectName("muted"); detail_label.setMinimumWidth(330); row.addWidget(detail_label); self.factor_layout.addLayout(row)
