from datetime import date

from dxb_runway.stock_action_plan import calculate_stock_action_plan


def vehicle(name, price, sale, purchased, forecast=None, purchase_type="cash"):
    return {"vehicle_name": name, "purchase_price_aed": price, "expected_sale_price_aed": sale,
            "expected_profit_aed": sale-price, "purchased_date": purchased, "purchase_type": purchase_type,
            "deal_drive_estimated_days": forecast}


def test_plan_prioritises_aged_stock_and_budget_gap():
    rows = [vehicle("Audi Q8", 200_000, 230_000, "2026-06-01", 62),
            vehicle("Audi Q7", 150_000, 180_000, "2026-07-20", 30)]
    plan = calculate_stock_action_plan(rows, 2_000_000, date(2026, 8, 20))
    assert len(plan["actions"]) == 3
    assert "Audi Q8" in plan["actions"][0]["title"]
    assert "Deploy budget" in plan["actions"][1]["title"]
    assert plan["slow_count"] == 1 and plan["critical_count"] == 1


def test_plan_counts_fast_as_strictly_below_45_days():
    rows = [vehicle("BMW X5", 100_000, 120_000, "2026-08-01", 44.9),
            vehicle("BMW X6", 120_000, 145_000, "2026-08-01", 45)]
    plan = calculate_stock_action_plan(rows, 500_000, date(2026, 8, 20))
    assert plan["fast_count"] == 1
    assert plan["slow_count"] == 1
