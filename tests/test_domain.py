from datetime import date
from decimal import Decimal

import pytest

from dxb_runway.domain import (
    CommissionTier, FinancialPosition, basic_salary, calculate_earnings, calculate_timed_runway, card_utilisation,
    dual_amount, estimate_monthly_interest, gbp_equivalent, repayment_months, simulate_scenario, to_aed
)


@pytest.mark.parametrize("budget,expected", [
    (0,6000),(2_999_999,6000),(3_000_000,7000),(3_999_999,7000),(4_000_000,8000),
    (5_000_000,9000),(6_000_000,10000),(7_000_000,11000),(8_000_000,12000),
    (9_000_000,13000),(10_000_000,14000),(20_000_000,14000),
])
def test_salary_bands(budget,expected):
    assert basic_salary(budget)==Decimal(f"{expected}.00")


def test_january_targets_and_full_profit_rates():
    baseline=calculate_earnings(year=2026,month=1,budget_aed=3_000_000,eligible_profit_aed=284_999)
    t3=calculate_earnings(year=2026,month=1,budget_aed=3_000_000,eligible_profit_aed=285_000)
    t2=calculate_earnings(year=2026,month=1,budget_aed=3_000_000,eligible_profit_aed=345_000)
    t1=calculate_earnings(year=2026,month=1,budget_aed=3_000_000,eligible_profit_aed=420_000)
    assert [x.tier for x in (baseline,t3,t2,t1)]==[CommissionTier.BASELINE,CommissionTier.TIER_3,CommissionTier.TIER_2,CommissionTier.TIER_1]
    assert t3.commission_aed==Decimal("14250.00")
    assert t2.commission_aed==Decimal("22425.00")
    assert t2.salary_aed==Decimal("7000.00") and t2.total_earned_aed==Decimal("29425.00")
    assert t1.commission_aed==Decimal("33600.00")


def test_commission_is_paid_exactly_two_months_later():
    jan=calculate_earnings(year=2026,month=1,budget_aed=3_000_000,eligible_profit_aed=285_000)
    nov=calculate_earnings(year=2026,month=11,budget_aed=3_000_000,eligible_profit_aed=345_000)
    assert jan.payment_date==date(2026,3,31)
    assert nov.payment_date==date(2027,1,30)


def test_cars_to_next_tier_at_example_margin():
    result=calculate_earnings(year=2026,month=1,budget_aed=3_000_000,eligible_profit_aed=0,average_margin_aed=24_700)
    assert result.next_target_aed==Decimal("285000.00")
    assert result.cars_to_next_tier==12


def test_live_vehicle_profit_uses_the_selected_month_target_schedule():
    april=calculate_earnings(year=2026,month=4,budget_aed=3_000_000,eligible_profit_aed=260_000)
    may=calculate_earnings(year=2026,month=5,budget_aed=3_000_000,eligible_profit_aed=260_000)
    assert april.tier==CommissionTier.TIER_3 and april.rate==Decimal("0.05")
    assert may.tier==CommissionTier.BASELINE and may.rate==Decimal("0.04")


def test_gbp_aed_conversion():
    assert to_aed("2000","GBP","4.75")==Decimal("9500.00")
    assert to_aed("2000","AED","4.75")==Decimal("2000.00")
    with pytest.raises(ValueError): to_aed(10,"USD",4.75)


def test_current_snapshot_dual_currency_formatting():
    assert gbp_equivalent("4928.313", "4.928313") == Decimal("1000.00")
    assert dual_amount("4928.313", "4.928313", 2) == ("AED 4,928.31", "≈ GBP 1,000.00")


def test_credit_and_pending_commission_never_count_as_cash_or_wealth():
    position=FinancialPosition(Decimal("10000"),Decimal("3000"),Decimal("1000"),Decimal("2000"),Decimal("19000"),Decimal("50000"),Decimal("7500"),Decimal("500"),Decimal("6000"))
    assert position.spendable_cash_aed==Decimal("6000.00")
    assert position.available_credit_aed==Decimal("17000.00")
    assert position.net_wealth_aed==Decimal("9000.00")
    assert position.pending_commission_aed==Decimal("50000")


def test_runway_excludes_protected_fund_and_deposit():
    position=FinancialPosition(Decimal("10000"),Decimal("3000"),Decimal("1000"),Decimal("0"),Decimal("0"),Decimal("0"),Decimal("8000"),Decimal("0"),Decimal("6000"))
    assert 91 <= position.runway_days <= 92


def test_timed_runway_respects_gap_until_next_salary():
    assert calculate_timed_runway(1000,8000,6000,date(2026,7,16),date(2026,7,31))==3
    assert calculate_timed_runway(10000,4000,6000,date(2026,7,16),date(2026,7,31))==999


def test_credit_utilisation_warnings_and_interest():
    assert card_utilisation(1200,4000)==Decimal("30.0")
    assert estimate_monthly_interest(1200,24)==Decimal("24.00")
    assert repayment_months(1000,0,100)==10
    assert repayment_months(1000,24,10) is None


def test_scenario_projection_and_emergency_breach():
    result=simulate_scenario(start_date=date(2026,7,23),starting_cash=9500,emergency_fund=3000,monthly_income=6000,monthly_expenses=8500)
    assert result.monthly_surplus_aed==Decimal("-2500.00")
    assert 79 <= result.runway_days <= 80
    assert result.cash_out_date is not None
    assert result.savings_3m==Decimal("2000.00")
    assert result.emergency_breached
