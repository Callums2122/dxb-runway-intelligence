from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from enum import StrEnum
import calendar
import math


MONEY = Decimal("0.01")


def money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def to_aed(amount: Decimal | float | int | str, currency: str, gbp_aed: Decimal | float | str) -> Decimal:
    value = money(amount)
    if currency.upper() == "AED":
        return value
    if currency.upper() == "GBP":
        rate = Decimal(str(gbp_aed))
        if rate <= 0:
            raise ValueError("Exchange rate must be greater than zero")
        return money(value * rate)
    raise ValueError("Currency must be AED or GBP")


def from_aed(amount: Decimal | float | int | str, currency: str, gbp_aed: Decimal | float | str) -> Decimal:
    value = money(amount)
    if currency.upper() == "AED":
        return value
    if currency.upper() == "GBP":
        rate = Decimal(str(gbp_aed))
        if rate <= 0:
            raise ValueError("Exchange rate must be greater than zero")
        return money(value / rate)
    raise ValueError("Currency must be AED or GBP")


def gbp_equivalent(amount_aed: Decimal | float | int | str, gbp_aed: Decimal | float | str) -> Decimal:
    """Return the GBP equivalent of an AED amount using AED per GBP."""
    return from_aed(amount_aed, "GBP", gbp_aed)


def dual_amount(amount_aed: Decimal | float | int | str, gbp_aed: Decimal | float | str,
                decimals: int = 0, signed: bool = False) -> tuple[str, str]:
    """Format AED as primary and GBP as a clearly approximate secondary value."""
    value = money(amount_aed)
    gbp = gbp_equivalent(value, gbp_aed)
    sign = "+" if signed else ""
    return f"AED {value:{sign},.{decimals}f}", f"≈ GBP {gbp:{sign},.{decimals}f}"


class CommissionTier(StrEnum):
    BASELINE = "Baseline"
    TIER_3 = "Tier 3"
    TIER_2 = "Tier 2"
    TIER_1 = "Tier 1"


COMMISSION_RATES = {
    CommissionTier.BASELINE: Decimal("0.04"),
    CommissionTier.TIER_3: Decimal("0.05"),
    CommissionTier.TIER_2: Decimal("0.065"),
    CommissionTier.TIER_1: Decimal("0.08"),
}

TARGET_PERCENTAGES: dict[int, tuple[Decimal, Decimal, Decimal]] = {
    1: (Decimal("0.095"), Decimal("0.115"), Decimal("0.14")),
    2: (Decimal("0.095"), Decimal("0.115"), Decimal("0.14")),
    3: (Decimal("0.095"), Decimal("0.115"), Decimal("0.14")),
    4: (Decimal("0.085"), Decimal("0.105"), Decimal("0.125")),
    5: (Decimal("0.115"), Decimal("0.14"), Decimal("0.165")),
    6: (Decimal("0.085"), Decimal("0.105"), Decimal("0.125")),
    7: (Decimal("0.095"), Decimal("0.115"), Decimal("0.14")),
    8: (Decimal("0.095"), Decimal("0.115"), Decimal("0.14")),
    9: (Decimal("0.115"), Decimal("0.14"), Decimal("0.165")),
    10: (Decimal("0.115"), Decimal("0.14"), Decimal("0.165")),
    11: (Decimal("0.115"), Decimal("0.14"), Decimal("0.165")),
    12: (Decimal("0.095"), Decimal("0.115"), Decimal("0.14")),
}


def basic_salary(budget_aed: Decimal | float | int | str) -> Decimal:
    budget = Decimal(str(budget_aed))
    if budget < 0:
        raise ValueError("Budget cannot be negative")
    if budget < 3_000_000:
        return money(6000)
    if budget >= 10_000_000:
        return money(14000)
    return money(7000 + int((budget - Decimal("3000000")) // Decimal("1000000")) * 1000)


@dataclass(frozen=True)
class EarningsResult:
    month: int
    budget_aed: Decimal
    eligible_profit_aed: Decimal
    salary_aed: Decimal
    tier: CommissionTier
    rate: Decimal
    commission_aed: Decimal
    deductions_aed: Decimal
    total_earned_aed: Decimal
    payment_date: date
    next_tier: CommissionTier | None
    next_target_aed: Decimal | None
    distance_to_next_aed: Decimal
    cars_to_next_tier: int
    incremental_value_aed: Decimal


def add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year = day.year + index // 12
    month = index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def calculate_earnings(
    *,
    year: int,
    month: int,
    budget_aed: Decimal | float | int | str,
    eligible_profit_aed: Decimal | float | int | str,
    average_margin_aed: Decimal | float | int | str = 24700,
    deductions_aed: Decimal | float | int | str = 0,
) -> EarningsResult:
    if month not in TARGET_PERCENTAGES:
        raise ValueError("Month must be between 1 and 12")
    budget = money(budget_aed)
    profit = money(eligible_profit_aed)
    average_margin = money(average_margin_aed)
    deductions = money(deductions_aed)
    if min(budget, profit, average_margin) < 0:
        raise ValueError("Inputs cannot be negative")
    t3_pct, t2_pct, t1_pct = TARGET_PERCENTAGES[month]
    targets = [money(budget * p) for p in (t3_pct, t2_pct, t1_pct)]
    if profit >= targets[2]:
        tier = CommissionTier.TIER_1
        next_tier = None
        next_target = None
    elif profit >= targets[1]:
        tier, next_tier, next_target = CommissionTier.TIER_2, CommissionTier.TIER_1, targets[2]
    elif profit >= targets[0]:
        tier, next_tier, next_target = CommissionTier.TIER_3, CommissionTier.TIER_2, targets[1]
    else:
        tier, next_tier, next_target = CommissionTier.BASELINE, CommissionTier.TIER_3, targets[0]
    rate = COMMISSION_RATES[tier]
    commission = money(profit * rate)
    salary = basic_salary(budget)
    total = money(max(Decimal("0"), salary + commission - deductions))
    distance = money(max(Decimal("0"), (next_target or profit) - profit))
    cars = 0 if distance == 0 or average_margin == 0 else int((distance / average_margin).to_integral_value(rounding=ROUND_CEILING))
    next_rate = COMMISSION_RATES[next_tier] if next_tier else rate
    incremental = money(max(Decimal("0"), (next_target or profit) * next_rate - profit * rate))
    earned_at = date(year, month, calendar.monthrange(year, month)[1])
    return EarningsResult(month, budget, profit, salary, tier, rate, commission, deductions, total,
                          add_months(earned_at, 2), next_tier, next_target, distance, cars, incremental)


@dataclass(frozen=True)
class FinancialPosition:
    cash_aed: Decimal
    protected_fund_aed: Decimal
    deposits_aed: Decimal
    card_debt_aed: Decimal
    credit_limit_aed: Decimal
    pending_commission_aed: Decimal
    monthly_essential_aed: Decimal
    monthly_discretionary_aed: Decimal
    guaranteed_income_aed: Decimal

    @property
    def spendable_cash_aed(self) -> Decimal:
        return money(max(Decimal("0"), self.cash_aed - self.protected_fund_aed - self.deposits_aed))

    @property
    def available_credit_aed(self) -> Decimal:
        return money(max(Decimal("0"), self.credit_limit_aed - self.card_debt_aed))

    @property
    def monthly_burn_aed(self) -> Decimal:
        return money(max(Decimal("0"), self.monthly_essential_aed + self.monthly_discretionary_aed - self.guaranteed_income_aed))

    @property
    def runway_days(self) -> int:
        burn = self.monthly_burn_aed
        if burn <= 0:
            return 999
        return max(0, int(self.spendable_cash_aed / (burn / Decimal("30.4375"))))

    @property
    def safe_daily_allowance_aed(self) -> Decimal:
        essential_daily = self.monthly_essential_aed / Decimal("30.4375")
        guaranteed_daily = self.guaranteed_income_aed / Decimal("30.4375")
        reserve_for_essentials = max(Decimal("0"), essential_daily - guaranteed_daily)
        return money(max(Decimal("0"), self.spendable_cash_aed / Decimal("90") - reserve_for_essentials))

    @property
    def net_wealth_aed(self) -> Decimal:
        # Credit limit and pending commission are deliberately excluded.
        return money(self.cash_aed + self.deposits_aed - self.card_debt_aed)

    @property
    def health_score(self) -> int:
        return self.health_score_for_runway(self.runway_days)

    def health_score_for_runway(self, runway: int) -> int:
        score = 100
        if runway < 90:
            score -= min(45, int((90 - runway) / 2))
        utilisation = Decimal("0") if self.credit_limit_aed <= 0 else self.card_debt_aed / self.credit_limit_aed
        score -= int(min(Decimal("35"), utilisation * Decimal("35")))
        if self.guaranteed_income_aed < self.monthly_essential_aed:
            score -= 15
        return max(0, min(100, score))


def calculate_timed_runway(spendable_cash: Decimal | float | str, monthly_expenses: Decimal | float | str,
                           monthly_income: Decimal | float | str, as_of: date, next_income_date: date,
                           horizon_days: int = 3650) -> int:
    """Return the first day spendable cash runs out, respecting monthly pay timing."""
    balance = Decimal(str(spendable_cash))
    expenses = max(Decimal("0"), Decimal(str(monthly_expenses)))
    income = max(Decimal("0"), Decimal(str(monthly_income)))
    if expenses <= 0:
        return 999
    daily_expense = expenses / Decimal("30.4375")
    pay_date = max(as_of, next_income_date)
    for offset in range(horizon_days + 1):
        current = as_of + timedelta(days=offset)
        if current == pay_date:
            balance += income
            pay_date = add_months(pay_date, 1)
        balance -= daily_expense
        if balance < 0:
            return offset
    return 999


def card_utilisation(balance: Decimal | float | str, limit: Decimal | float | str) -> Decimal:
    balance_d, limit_d = Decimal(str(balance)), Decimal(str(limit))
    if limit_d <= 0:
        return Decimal("0")
    return (balance_d / limit_d * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def utilisation_status(percent: Decimal | float | str) -> tuple[str, str]:
    value = Decimal(str(percent))
    if value >= 90:
        return "CRITICAL", "#ff5d73"
    if value >= 75:
        return "DANGER", "#ff8a4c"
    if value >= 50:
        return "HIGH", "#f4b740"
    if value >= 30:
        return "WATCH", "#f6cc62"
    return "HEALTHY", "#31d69b"


def estimate_monthly_interest(balance: Decimal | float | str, annual_rate_pct: Decimal | float | str) -> Decimal:
    return money(Decimal(str(balance)) * Decimal(str(annual_rate_pct)) / Decimal("1200"))


def repayment_months(balance: Decimal | float | str, annual_rate_pct: Decimal | float | str,
                     monthly_payment: Decimal | float | str, cap: int = 600) -> int | None:
    debt, payment = Decimal(str(balance)), Decimal(str(monthly_payment))
    rate = Decimal(str(annual_rate_pct)) / Decimal("1200")
    if debt <= 0:
        return 0
    if payment <= debt * rate:
        return None
    for month_index in range(1, cap + 1):
        debt = debt * (Decimal("1") + rate) - payment
        if debt <= 0:
            return month_index
    return None


@dataclass(frozen=True)
class ScenarioResult:
    monthly_surplus_aed: Decimal
    runway_days: int
    cash_out_date: date | None
    savings_3m: Decimal
    savings_6m: Decimal
    savings_12m: Decimal
    savings_24m: Decimal
    emergency_breached: bool
    debt_12m: Decimal


def simulate_scenario(*, start_date: date, starting_cash: Decimal | float | str,
                      emergency_fund: Decimal | float | str, monthly_income: Decimal | float | str,
                      monthly_expenses: Decimal | float | str, card_balance: Decimal | float | str = 0,
                      card_apr: Decimal | float | str = 0, repayment: Decimal | float | str = 0) -> ScenarioResult:
    cash, emergency = money(starting_cash), money(emergency_fund)
    income, expenses = money(monthly_income), money(monthly_expenses)
    surplus = money(income - expenses)
    spendable = max(Decimal("0"), cash - emergency)
    if surplus < 0:
        days = max(0, int(spendable / (-surplus / Decimal("30.4375"))))
        cash_out = start_date.fromordinal(start_date.toordinal() + days)
    else:
        days, cash_out = 999, None
    projections = [money(cash + surplus * n) for n in (3, 6, 12, 24)]
    debt = money(card_balance)
    monthly_rate = Decimal(str(card_apr)) / Decimal("1200")
    payment = money(repayment)
    for _ in range(12):
        debt = money(max(Decimal("0"), debt * (1 + monthly_rate) - payment))
    return ScenarioResult(surplus, days, cash_out, *projections, min(projections) < emergency, debt)
