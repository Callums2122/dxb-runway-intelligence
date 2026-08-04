import os
from datetime import date
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from dxb_runway.database import Database
from dxb_runway.dialogs import CustomerContactDialog, OnboardingDialog, SellVehicleDialog, VehicleDialog
from dxb_runway.main_window import MainWindow, NAV_SECTIONS
from dxb_runway.domain import TARGET_PERCENTAGES, money
from dxb_runway.screens import BudgetsPage, CalendarPage, DashboardPage, PlayfulCalendar, category_label, contact_countdown, customer_vehicle_year, latest_occurrence_for_month
from dxb_runway.screens import WhatsAppTemplatesPage


def app():
    return QApplication.instance() or QApplication([])


def test_first_run_onboarding_constructs(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db")
    assert db.get_setting("onboarding_complete")=="0"
    dialog=OnboardingDialog(db)
    assert dialog.pages.count()==4
    assert dialog.fields["uk_cash_gbp"].value()==2000
    dialog.close()


def test_customer_contact_uses_model_year_dropdown(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db")
    dialog=CustomerContactDialog(db)
    assert [dialog.year.itemData(i) for i in range(dialog.year.count())]==list(range(2018,2027))
    assert dialog.year.currentData()==2026
    dialog.year.setCurrentIndex(dialog.year.findData(2021))
    assert dialog.values()["vehicle_age_years"]==2021
    assert customer_vehicle_year(2021)==2021
    assert customer_vehicle_year(5)==2021
    dialog.close()


def test_inspection_purchase_dialog_prefills_verified_prices(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); customer_id=db.add_customer_contact({"customer_name":"Seller","vehicle_name":"Jeep Wrangler","vehicle_age_years":2021,"phone_last5":"12345","cash_offer_aed":125000,"vehicle_price_aed":150000}); customer=db.query("SELECT * FROM customer_contacts WHERE id=?",(customer_id,))[0]
    dialog=VehicleDialog(db,source_customer=customer); values=dialog.values()
    assert values["vehicle_name"]=="2021 Jeep Wrangler" and values["purchase_price_aed"]==125000 and values["expected_sale_price_aed"]==150000
    dialog.close()


def test_consignment_sale_dialog_tracks_final_owner_payout(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); vehicle_id=db.add_vehicle(vehicle_name="Range Rover",purchase_type="consignment",purchase_price_aed=270000,expected_sale_price_aed=280000,purchased_date="2026-08-01"); vehicle=db.query("SELECT * FROM vehicles WHERE id=?",(vehicle_id,))[0]
    dialog=SellVehicleDialog(vehicle); dialog.owner_payout.setValue(265000); values=dialog.values()
    assert values["sold_price_aed"]==280000 and values["final_owner_payout_aed"]==265000 and "15,000.00" in dialog.profit.text() and "+5,000.00" in dialog.profit.text()
    dialog.close()


def test_whatsapp_template_copy_uses_clipboard_and_confirms(tmp_path: Path,monkeypatch):
    application=app(); db=Database(tmp_path/"data.db"); db.save_message_template("Follow-up","Hi, is your car still available?")
    page=WhatsAppTemplatesPage(db); confirmations=[]; monkeypatch.setattr("dxb_runway.screens.QMessageBox.information",lambda *args: confirmations.append(args[2]))
    page.copy_message()
    assert application.clipboard().text()=="Hi, is your car still available?"
    assert confirmations==["Message copied to your clipboard.\n\nIt is ready to paste into WhatsApp."]
    page.close()


def test_whatsapp_template_autofills_customer_and_vehicle(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); db.add_customer_contact({"customer_name":"Sam","vehicle_name":"Jeep Wrangler","vehicle_age_years":2021,"phone_last5":"12345"}); db.save_message_template("Personal","Hi {{customer_name}}, is your {{vehicle}} still available?")
    page=WhatsAppTemplatesPage(db); assert page.customer_search.text()=="" and not page.copy_button.isEnabled(); page.customer_search.setText("Sam"); page.customer.setCurrentIndex(1)
    assert page.preview.toPlainText()=="Hi Sam, is your 2021 Jeep Wrangler still available?"
    assert page.copy_button.isEnabled(); page.close()


def test_whatsapp_customer_picker_searches_large_lists_safely(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db")
    for index in range(30): db.add_customer_contact({"customer_name":f"Customer {index:02d}","vehicle_name":"Jeep Wrangler" if index==23 else "BMW M4","vehicle_age_years":2021,"phone_last5":f"{index:05d}"})
    db.save_message_template("Personal","Hi {{customer_name}}, is your {{vehicle}} available?"); page=WhatsAppTemplatesPage(db)
    assert page.customer_search.text()=="" and page.customer.maxVisibleItems()==12
    page.customer_search.setText("00023"); assert page.customer.count()==2 and page.customer.currentIndex()==0 and not page.copy_button.isEnabled()
    page.customer.setCurrentIndex(1)
    assert "Hi Customer 23" in page.preview.toPlainText() and "2021 Jeep Wrangler" in page.preview.toPlainText()
    page.customer_search.setText("Customer"); assert page.customer.count()==31 and page.customer.itemText(1).startswith("Customer 00")
    page.close()


def test_sold_elsewhere_action_deletes_selected_customer(tmp_path: Path,monkeypatch):
    application=app(); db=Database(tmp_path/"data.db"); customer_id=db.add_customer_contact({"customer_name":"Gone seller","vehicle_name":"Audi S3","vehicle_age_years":2022,"phone_last5":"54321"}); window=MainWindow(db); page=window.pages["contacts"]; page.tables["today"].selectRow(0)
    monkeypatch.setattr("dxb_runway.screens.QMessageBox.question",lambda *args: QMessageBox.StandardButton.Yes)
    page.sold_elsewhere()
    assert db.query("SELECT id FROM customer_contacts WHERE id=?",(customer_id,))==[] and page.tables["today"].rowCount()==0
    window.close()


def test_every_major_screen_constructs_and_navigates(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); db.seed_demo()
    window=MainWindow(db)
    assert set(window.pages)=={"dashboard","todo","kpi","contacts","inspection","templates","stock","vehicles","transactions","debt","scenarios","budgets","calendar","goals","vehicle_history","reports","settings"}
    assert [[item[0] for item in section[3]] for section in NAV_SECTIONS]==[["todo","kpi","contacts","inspection","templates","stock","vehicles","calendar","scenarios"],["transactions","debt","budgets"],["goals","vehicle_history","reports","settings"]]
    assert window.nav_buttons["dashboard"].property("section")=="overview"
    assert window.nav_buttons["vehicles"].property("section")=="leads"
    assert window.nav_buttons["stock"].property("section")=="leads"
    assert window.nav_buttons["contacts"].property("section")=="leads"
    assert window.nav_buttons["transactions"].property("section")=="money"
    assert window.nav_buttons["goals"].property("section")=="other"
    assert category_label("Transport").endswith("Transport")
    assert category_label("Unknown category").endswith("Unknown category")
    for key,page in window.pages.items():
        window.navigate(key)
        assert window.stack.currentWidget() is page
    db.toggle_transaction_highlight(db.transactions()[0]["id"]); transactions=window.pages["transactions"]; transactions.refresh()
    assert transactions.table.item(0,0).background().color().name()=="#5a4316"
    assert transactions.table.item(0,0).data(Qt.ItemDataRole.UserRole) is True
    assert "★" not in transactions.table.item(0,5).text()
    vehicles=window.pages["vehicles"]
    stock=window.pages["stock"]
    contacts=window.pages["contacts"]
    inspection=window.pages["inspection"]
    templates=window.pages["templates"]
    history=window.pages["vehicle_history"]
    assert vehicles.month.count()==12
    assert vehicles.tier_table.rowCount()==12 and vehicles.tier_table.columnCount()==7
    july_budget=db.performance_budget(vehicles.selected_month()); july_t3=TARGET_PERCENTAGES[7][0]; expected_t3=money(Decimal(db.get_setting("salary_aed"))+money(july_budget*july_t3)*Decimal("0.05"))
    assert vehicles.tier_earnings["tier3"].value.text()==f"AED {expected_t3:,.0f}"
    vehicles.configure_month_options(date(2026,7,30))
    assert vehicles.month.itemText(6)=="July 2026"
    assert vehicles.month.itemText(7)=="August 2025"
    assert vehicles.month.itemData(6,Qt.ItemDataRole.BackgroundRole).name()=="#174f40"
    assert vehicles.month.itemData(4,Qt.ItemDataRole.BackgroundRole).name()=="#5a4316"
    vehicles.month.setCurrentIndex(4)
    assert vehicles.selected_month()=="2026-05"
    vehicles.configure_month_options()
    vehicles.month.setCurrentIndex(date.today().month-1)
    vehicles.refresh()
    assert history.table.columnCount()==6
    assert set(contacts.tables)=={"today","tomorrow","all"} and contacts.tables["today"].columnCount()==7
    todo=window.pages["todo"]; todo.entry.setText("Follow up with seller"); todo.add_task(); assert todo.table.rowCount()==1 and todo.table.item(0,1).text()=="Follow up with seller"; todo.table.item(0,0).setCheckState(Qt.CheckState.Checked); application.processEvents(); assert todo.metrics["completed"].value.text()=="1"
    kpi=window.pages["kpi"]; kpi.phone.setText("0501234567"); kpi.call_count.setValue(6); kpi.log_call(); assert kpi.calls.rowCount()==1 and "6 / 240" in kpi.call_title.text() and kpi.summary.rowCount()==8
    db.add_customer_contact({"customer_name":"Notes test","vehicle_name":"Audi RS6","phone_last5":"54321","vehicle_age_years":2021})
    contacts.refresh(); contacts.tables["today"].selectRow(0); application.processEvents()
    assert contacts.tables["today"].item(0,1).text()=="2021 Audi RS6"
    assert not contacts.notes_card.isHidden()
    contacts.close_notes()
    assert contacts.notes_card.isHidden() and contacts.tables["today"].selectedItems()==[]
    customer_id=db.query("SELECT id FROM customer_contacts WHERE customer_name='Notes test'")[0]["id"]; db.move_customer_to_inspection(customer_id,"2026-08-05"); contacts.refresh(); inspection.refresh()
    assert contacts.tables["today"].rowCount()==0 and inspection.table.rowCount()==1
    assert inspection.table.item(0,0).text()=="2026-08-05" and inspection.table.item(0,2).text()=="2021 Audi RS6"
    db.save_message_template("First message","Hi, is your vehicle still available?"); templates.refresh()
    assert templates.table.rowCount()==1 and templates.preview.toPlainText()=="Hi, is your vehicle still available?" and templates.copy_button.isEnabled()
    assert stock.table.columnCount()==6
    assert "remaining" in stock.live_budget_value.text() and "revolving" in stock.live_budget_detail.text()
    assert "value" in stock.metrics and "includes consignments" in stock.metrics["value"].detail.text()
    assert "stock" not in vehicles.metrics and "expected" not in vehicles.metrics
    assert "total" in vehicles.metrics and "Commission only" in vehicles.metrics["commission"].detail.text()
    assert f"Base AED {vehicles.current_result.salary_aed:,.0f}" in vehicles.metrics["total"].detail.text()
    vehicles.salary.setValue(9250); vehicles.save_salary(); assert db.get_setting("salary_aed")=="9250.00" and vehicles.current_result.salary_aed==Decimal("9250.00")
    synced=db.query("SELECT salary_aed,commission_aed FROM earnings WHERE year=? AND month=?",(date.today().year,date.today().month))[0]
    assert Decimal(str(synced["salary_aed"]))==vehicles.current_result.salary_aed
    assert Decimal(str(synced["commission_aed"]))==vehicles.current_result.commission_aed
    window.toggle_sidebar(); assert window.section_headers["leads"][1].text()=="●" and window.section_headers["leads"][2].isHidden()
    window.toggle_sidebar(); assert window.section_headers["leads"][1].text()=="●  LEADS"
    window.show(); application.processEvents(); window.navigate("transactions")
    assert window.pages["transactions"].graphicsEffect() is None
    window.close()


def test_vehicle_desk_month_names_roll_to_latest_occurrence_without_deleting_history():
    assert latest_occurrence_for_month(8,date(2026,7,31))=="2025-08"
    assert latest_occurrence_for_month(8,date(2026,8,1))=="2026-08"
    assert latest_occurrence_for_month(7,date(2026,8,1))=="2026-07"


def test_customer_contact_countdown_keeps_date_timing_clear():
    today=date(2026,7,30)
    assert contact_countdown("2026-08-02",today)=="3 days left"
    assert contact_countdown("2026-07-31",today)=="1 day left"
    assert contact_countdown("2026-07-30",today)=="Due today"
    assert contact_countdown("2026-07-28",today)=="Overdue by 2 days"


def test_calendar_wheel_moves_only_once_per_gesture():
    application=app(); calendar=PlayfulCalendar(); start=QDate(calendar.yearShown(),calendar.monthShown(),1)
    assert calendar.handle_wheel(-120,10.0) is True
    assert QDate(calendar.yearShown(),calendar.monthShown(),1)==start.addMonths(1)
    assert calendar.handle_wheel(-120,10.1) is False
    assert QDate(calendar.yearShown(),calendar.monthShown(),1)==start.addMonths(1)
    assert calendar.handle_wheel(-120,10.7) is True
    assert QDate(calendar.yearShown(),calendar.monthShown(),1)==start.addMonths(2)
    calendar.close()


def test_budget_tracks_transactions_and_places_rent_due_in_calendar(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); db.set_setting("gbp_aed_rate","4.8")
    accommodation=db.query("SELECT id FROM categories WHERE name='Accommodation'")[0]["id"]
    groceries=db.query("SELECT id FROM categories WHERE name='Groceries'")[0]["id"]
    db.execute("INSERT INTO budgets(month,category_id,planned_aed,due_date) VALUES ('2026-07',?,4500,'2026-07-25')",(accommodation,))
    db.execute("INSERT INTO budgets(month,category_id,planned_aed) VALUES ('2026-07',?,1000)",(groceries,))
    for amount,category,merchant in [(4000,accommodation,"Rent"),(250,groceries,"Food shop")]:
        db.add_transaction({"amount":amount,"currency":"AED","occurred_at":"2026-07-18T12:00:00","kind":"expense","category_id":category,"merchant":merchant,"payment_method":"Bank transfer","recurring":0,"notes":"","receipt_path":None,"refundable_deposit":0,"essential":1,"tags":""})
    budget=BudgetsPage(db); budget.month_date=QDate(2026,7,1); budget.refresh()
    assert budget.rent_plan.value()==4500 and budget.rent_due.date()==QDate(2026,7,25)
    assert "AED 4,000" in budget.rent_spent.text()
    assert "AED +750" in budget.category_cards[groceries].remaining.text()
    calendar=CalendarPage(db)
    assert QDate(2026,7,25) in calendar.calendar.event_colors
    customer_id=db.add_customer_contact({"customer_name":"Calendar seller","vehicle_name":"Jeep Wrangler","vehicle_age_years":2021,"phone_last5":"12345"}); db.move_customer_to_inspection(customer_id,"2026-08-05"); calendar.refresh()
    assert QDate(2026,8,5) in calendar.calendar.event_colors
    inspection_event=calendar.inspection_events("2026-08-05")[0]
    assert inspection_event["title"]=="Calendar seller · Vehicle inspection" and "2021 Jeep Wrangler" in inspection_event["notes"]
    db.return_customer_to_callers(customer_id); calendar.refresh(); assert calendar.inspection_events("2026-08-05")==[]
    budget.close(); calendar.close()


def test_overview_runway_uses_budget_salary_calendar_and_card_minimums(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); db.set_setting("onboarding_complete","1")
    accommodation=db.query("SELECT id FROM categories WHERE name='Accommodation'")[0]["id"]
    restaurants=db.query("SELECT id FROM categories WHERE name='Restaurants'")[0]["id"]
    db.execute("INSERT INTO budgets(month,category_id,planned_aed) VALUES ('2026-07',?,4000)",(accommodation,))
    db.execute("INSERT INTO budgets(month,category_id,planned_aed) VALUES ('2026-07',?,500)",(restaurants,))
    db.execute("INSERT INTO credit_cards(name,currency,credit_limit,current_balance,minimum_payment) VALUES ('UK card','GBP',5000,1000,100)")
    db.execute("INSERT INTO earnings(year,month,purchasing_budget_aed,eligible_profit_aed,tier,salary_aed,commission_aed,earned_date,payment_date) VALUES (2026,7,3000000,0,'baseline',7000,0,'2026-07-31','2026-09-30')")
    db.execute("INSERT INTO reminders(title,event_date,event_type) VALUES ('Salary payment','2026-07-26','salary')")
    category=db.query("SELECT id FROM categories WHERE name='Flight/relocation'")[0]["id"]
    db.add_transaction({"amount":4500,"currency":"AED","occurred_at":"2026-07-02T12:00:00","kind":"expense","category_id":category,"merchant":"Relocation setup","payment_method":"Debit card","recurring":0,"notes":"","receipt_path":None,"refundable_deposit":0,"essential":1,"tags":"","budget_excluded":1})
    page=DashboardPage(db); position,data=page.position(date(2026,7,16))
    assert position.monthly_essential_aed==Decimal("4492.83")
    assert position.monthly_discretionary_aed==Decimal("500.00")
    assert position.guaranteed_income_aed==Decimal("7000.00")
    assert data["next_salary"]==date(2026,7,26)
    assert data["budget_source"]=="saved budget" and data["income_source"]=="salary engine"
    assert data["expense"]==Decimal("0.00") and data["cash_out"]==Decimal("4500.00")
    assert data["setup_adjustment"]==Decimal("4500.00")
    assert data["operating_position"].spendable_cash_aed==position.spendable_cash_aed+Decimal("4500.00")
    assert data["runway"]>data["actual_runway"]
    assert db.transactions()[0]["budget_excluded"]==1
    db.add_transaction({"amount":100,"currency":"AED","occurred_at":"2026-07-16T13:00:00","kind":"expense","category_id":restaurants,"merchant":"Lunch and taxi","payment_method":"Debit card","recurring":0,"notes":"","receipt_path":None,"refundable_deposit":0,"essential":0,"tags":""})
    _,updated=page.position(date(2026,7,16))
    assert updated["spent_today"]==Decimal("100.00")
    assert updated["monthly_cap_gbp"]==Decimal("1700.00")
    assert updated["monthly_cap_aed"]==Decimal("8378.13")
    assert updated["daily_limit"]==Decimal("517.38")
    assert updated["daily_left"]==Decimal("417.38")
    page.close()
