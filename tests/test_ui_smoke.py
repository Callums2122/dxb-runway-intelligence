import os
from datetime import date
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtWidgets import QApplication

from dxb_runway.database import Database
from dxb_runway.dialogs import OnboardingDialog
from dxb_runway.main_window import MainWindow
from dxb_runway.screens import DashboardPage


def app():
    return QApplication.instance() or QApplication([])


def test_first_run_onboarding_constructs(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db")
    assert db.get_setting("onboarding_complete")=="0"
    dialog=OnboardingDialog(db)
    assert dialog.pages.count()==4
    assert dialog.fields["uk_cash_gbp"].value()==2000
    dialog.close()


def test_every_major_screen_constructs_and_navigates(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); db.seed_demo()
    window=MainWindow(db)
    assert set(window.pages)=={"dashboard","vehicles","transactions","debt","earnings","scenarios","budgets","calendar","goals","reports","settings"}
    for key,page in window.pages.items():
        window.navigate(key)
        assert window.stack.currentWidget() is page
    window.close()


def test_overview_runway_uses_budget_salary_calendar_and_card_minimums(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); db.set_setting("onboarding_complete","1")
    accommodation=db.query("SELECT id FROM categories WHERE name='Accommodation'")[0]["id"]
    restaurants=db.query("SELECT id FROM categories WHERE name='Restaurants'")[0]["id"]
    db.execute("INSERT INTO budgets(month,category_id,planned_aed) VALUES ('2026-07',?,4000)",(accommodation,))
    db.execute("INSERT INTO budgets(month,category_id,planned_aed) VALUES ('2026-07',?,500)",(restaurants,))
    db.execute("INSERT INTO credit_cards(name,currency,credit_limit,current_balance,minimum_payment) VALUES ('UK card','GBP',5000,1000,100)")
    db.execute("INSERT INTO earnings(year,month,purchasing_budget_aed,eligible_profit_aed,tier,salary_aed,commission_aed,earned_date,payment_date) VALUES (2026,7,3000000,0,'baseline',7000,0,'2026-07-31','2026-09-30')")
    db.execute("INSERT INTO reminders(title,event_date,event_type) VALUES ('Salary payment','2026-07-26','salary')")
    page=DashboardPage(db); position,data=page.position(date(2026,7,16))
    assert position.monthly_essential_aed==Decimal("4492.83")
    assert position.monthly_discretionary_aed==Decimal("500.00")
    assert position.guaranteed_income_aed==Decimal("7000.00")
    assert data["next_salary"]==date(2026,7,26)
    assert data["budget_source"]=="saved budget" and data["income_source"]=="salary engine"
    page.close()
