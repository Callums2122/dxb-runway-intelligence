from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any


def number(row: Any, key: str) -> float:
    try:
        return float(row[key] or 0)
    except (KeyError, TypeError, ValueError):
        return 0.0


def days_held(row: Any, today: date | None = None) -> int:
    today = today or date.today()
    try:
        return max(0, (today - date.fromisoformat(str(row["purchased_date"])[:10])).days)
    except (KeyError, TypeError, ValueError):
        return 0


def stock_heat(row: Any, appointment_count: int = 0, today: date | None = None) -> dict[str, Any]:
    """Transparent stock urgency score; higher means a healthier, easier exit."""
    held = days_held(row, today); forecast = number(row, "deal_drive_estimated_days")
    cost = number(row, "purchase_price_aed"); profit = number(row, "expected_profit_aed")
    margin = profit / cost if cost else 0.0; workflow = str(row["external_stock_status"] or "").casefold()
    speed = 55 if forecast <= 0 else max(0, min(100, round(110 - forecast * 1.6)))
    age = max(0, min(100, 100 - held * 1.7)); demand = min(100, appointment_count * 24)
    margin_score = max(0, min(100, round(margin / .18 * 100)))
    readiness = 35 if any(term in workflow for term in ("repair", "prep", "photoshoot")) else 100
    score = round(speed * .35 + age * .20 + demand * .20 + margin_score * .15 + readiness * .10)
    if held >= 60 or forecast >= 75: score = min(score, 29)
    elif held >= 45 or forecast >= 60: score = min(score, 44)
    if score >= 80: label, icon = "HOT", "🔥"
    elif score >= 60: label, icon = "HEALTHY", "🟢"
    elif score >= 40: label, icon = "NEEDS ACTION", "🟠"
    else: label, icon = "CAPITAL TRAPPED", "🔴"
    evidence = f"{held}d held · " + (f"≈{forecast:.0f}d market · " if forecast else "market pending · ") + f"{appointment_count} appt · {margin:.1%} margin"
    return {"score": score, "label": label, "icon": icon, "evidence": evidence, "days_held": held, "forecast": forecast, "margin": margin}


def rescue_options(row: Any, appointment_count: int = 0, today: date | None = None) -> list[dict[str, Any]]:
    sale = number(row, "expected_sale_price_aed"); cost = number(row, "purchase_price_aed")
    heat = stock_heat(row, appointment_count, today)
    if heat["label"] == "CAPITAL TRAPPED": recommended = 5000 if sale < 200000 else 10000
    elif heat["label"] == "NEEDS ACTION": recommended = 2000 if sale < 150000 else 5000
    else: recommended = 0
    output = []
    for reduction in (0, 2000, 5000, 10000):
        projected_sale = max(0.0, sale - reduction); projected_profit = projected_sale - cost
        output.append({"reduction": reduction, "sale": projected_sale, "profit": projected_profit,
                       "margin": projected_profit / cost if cost else 0.0, "recommended": reduction == recommended})
    return output


def attribution_for_vehicle(db, row: Any) -> dict[str, Any]:
    vehicle_id = int(row["id"]); purchased = str(row["purchased_date"] or "")[:10]; sold = str(row["sold_date"] or "")[:10]
    appointments = int(db.query("SELECT COUNT(*) n FROM pipeline_appointments WHERE matched_vehicle_id=? AND appointment_date BETWEEN ? AND ?", (vehicle_id, purchased, sold or "9999-12-31"))[0]["n"])
    events = db.query("SELECT event_type FROM stock_flow_events WHERE matched_vehicle_id=? ORDER BY processed_at", (vehicle_id,))
    event_types = [str(event["event_type"]) for event in events]; reductions = event_types.count("price_change")
    booked = "booked" in event_types; registered = "registered" in event_types
    forecast = number(row, "deal_drive_estimated_days")
    if appointments:
        primary = "Appointment demand"; detail = f"{appointments} matched appointment{'s' if appointments != 1 else ''} before sale"
    elif reductions:
        primary = "Price action"; detail = f"{reductions} recorded price reduction{'s' if reductions != 1 else ''} before sale"
    elif 0 < forecast < 45:
        primary = "Market demand"; detail = f"Deal Drive forecast ≈{forecast:.0f} days"
    else:
        primary = "Direct / organic"; detail = "No stronger tracked conversion signal"
    signals = [primary]
    if reductions and primary != "Price action": signals.append("Price action")
    if booked: signals.append("Booked")
    if registered: signals.append("Registered")
    return {"primary": primary, "detail": detail, "signals": signals, "appointments": appointments,
            "reductions": reductions, "booked": booked, "registered": registered}


def tier_scenarios(stock: list[Any], realised_profit: Decimal, targets: tuple[Decimal, Decimal, Decimal], budget: Decimal) -> list[dict[str, Any]]:
    ranked = sorted(stock, key=lambda row: (stock_heat(row)["score"], number(row, "expected_profit_aed")), reverse=True)
    output = []
    for name, target in zip(("Tier 3", "Tier 2", "Tier 1"), targets):
        required = (budget * target).quantize(Decimal("1")); gap = max(Decimal("0"), required - realised_profit)
        running = Decimal("0"); picks = []
        for row in ranked:
            if running >= gap: break
            profit = Decimal(str(number(row, "expected_profit_aed"))); running += max(Decimal("0"), profit); picks.append(str(row["vehicle_name"]))
        coverage = Decimal("1") if gap == 0 else min(Decimal("1"), running / gap) if gap else Decimal("1")
        likelihood = "LIKELY" if coverage >= 1 and len(picks) <= 3 else "ACHIEVABLE" if coverage >= 1 else "UNLIKELY"
        output.append({"tier": name, "target": target, "required": required, "gap": gap, "projected": running,
                       "cars": picks, "coverage": float(coverage), "likelihood": likelihood})
    return output
