from datetime import date
from decimal import Decimal

from dxb_runway.growth_logic import rescue_options, stock_heat, tier_scenarios


def vehicle(**changes):
    row={"vehicle_name":"Audi Q8","purchase_price_aed":200000,"expected_sale_price_aed":240000,"expected_profit_aed":40000,"purchased_date":"2026-08-20","deal_drive_estimated_days":25,"external_stock_status":"STOCK","purchase_type":"cash"}
    row.update(changes); return row


def test_stock_heat_rewards_demand_and_penalises_slow_ageing_stock():
    hot=stock_heat(vehicle(),3,date(2026,8,30)); trapped=stock_heat(vehicle(purchased_date="2026-05-01",deal_drive_estimated_days=90),0,date(2026,8,30))
    assert hot["score"]>trapped["score"]
    assert hot["label"] in {"HOT","HEALTHY"}
    assert trapped["label"]=="CAPITAL TRAPPED"


def test_rescue_options_never_hide_profit_effect():
    options=rescue_options(vehicle(purchased_date="2026-05-01",deal_drive_estimated_days=90),0,date(2026,8,30))
    recommended=next(option for option in options if option["recommended"])
    assert recommended["reduction"]>0
    assert recommended["profit"]==recommended["sale"]-200000


def test_tier_route_orders_hot_profitable_stock_and_reports_coverage():
    stock=[vehicle(vehicle_name="Audi Q8"),vehicle(vehicle_name="RAM 1500",purchase_price_aed=150000,expected_sale_price_aed=185000,expected_profit_aed=35000,deal_drive_estimated_days=35)]
    scenarios=tier_scenarios(stock,Decimal("100000"),(Decimal(".08"),Decimal(".10"),Decimal(".125")),Decimal("2000000"))
    assert scenarios[0]["required"]==Decimal("160000")
    assert scenarios[0]["gap"]==Decimal("60000")
    assert scenarios[0]["likelihood"] in {"LIKELY","ACHIEVABLE"}
