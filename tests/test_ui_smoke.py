import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtCore import QDate, QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea, QWidget

from dxb_runway.database import Database, SCHEMA_VERSION
from dxb_runway.app import place_on_secondary_display
from dxb_runway.dialogs import CustomerContactDialog, OnboardingDialog, SellVehicleDialog, VehicleDialog
from dxb_runway.main_window import MainWindow, NAV_SECTIONS
from dxb_runway.intelligence_screen import market_pace_bucket, openclaw_answer, openclaw_request, watchlist_match_from_question
from dxb_runway.pipeline_screen import PipelinePage
from dxb_runway.gym import GymNutritionPage
from dxb_runway.domain import CommissionTier, TARGET_PERCENTAGES, money
from dxb_runway.screens import BudgetsPage, CalendarPage, DashboardPage, PlayfulCalendar, call_month_pace, category_label, contact_countdown, customer_vehicle_year, display_call_date, latest_occurrence_for_month, monthly_kpi_adjustment, next_tier_progress, offer_message_steps, offer_route
from dxb_runway.screens import WhatsAppTemplatesPage
from dxb_runway.style import COLORS


def app():
    return QApplication.instance() or QApplication([])


def test_launch_window_prefers_named_secondary_display():
    class Screen:
        def __init__(self,name,area):self._name=name;self._area=area
        def name(self):return self._name
        def availableGeometry(self):return self._area
    class Screens:
        def __init__(self,primary,secondary):self.primary=primary;self.secondary=secondary
        def primaryScreen(self):return self.primary
        def screens(self):return [self.primary,*self.secondary]
    class Window:
        def __init__(self):self._width=1480;self._height=920;self.position=None
        def width(self):return self._width
        def height(self):return self._height
        def resize(self,width,height):self._width=width;self._height=height
        def move(self,x,y):self.position=(x,y)
    primary=Screen("Built-in",QRect(0,0,1512,982))
    left=Screen("Studio Display",QRect(-1920,0,1920,1080))
    right=Screen("Office TV",QRect(1512,0,2560,1440))
    window=Window()
    assert place_on_secondary_display(window,Screens(primary,[left,right]),"Office TV")=="Office TV"
    assert window.position==(2052,260)


def test_launch_window_stays_put_when_only_primary_display_exists():
    class Screen:pass
    class Screens:
        def __init__(self):self.primary=Screen()
        def primaryScreen(self):return self.primary
        def screens(self):return [self.primary]
    class Window:pass
    assert place_on_secondary_display(Window(),Screens())==""


def test_market_watchlist_exposes_manual_sync(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); window=MainWindow(db)
    intelligence=window.pages["intelligence"]
    assert intelligence.watch_sync.text()=="↻ Sync now"
    assert intelligence.watch_sync.isEnabled()
    assert "Ready to sync" in intelligence.watch_sync_status.text()
    window.close()


def test_market_radar_uses_owner_45_day_pace_line():
    assert market_pace_bucket(44.9)=="fast"
    assert market_pace_bucket(45)=="slow"
    assert market_pace_bucket(61)=="slow"
    assert market_pace_bucket(None)=="unknown"


def test_chat_detects_exact_approved_watchlist_vehicle():
    items=[{"make":"Audi","model":"Q8","trim":"S line"},{"make":"Audi","model":"Q7","trim":"S line"}]
    assert watchlist_match_from_question("Rate a 2022 Audi Q8 S-line at 165k",items)==items[0]
    assert watchlist_match_from_question("What about a BMW X5?",items) is None


def test_first_run_onboarding_constructs(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db")
    assert db.get_setting("onboarding_complete")=="0"
    dialog=OnboardingDialog(db)
    assert dialog.pages.count()==4
    assert dialog.fields["uk_cash_gbp"].value()==2000
    assert not dialog.fields["demo"].isChecked()
    dialog.close()


def test_mobile_sync_snapshot_contains_only_vehicle_desk_data(tmp_path: Path):
    db=Database(tmp_path/"data.db")
    db.add_vehicle(vehicle_name="2024 Porsche 911",purchase_type="cash",purchase_price_aed=400000,expected_sale_price_aed=440000,purchased_date="2026-08-01")
    db.set_performance_budget("2026-08",2_000_000)
    db.execute("INSERT INTO earnings(year,month,purchasing_budget_aed,eligible_profit_aed,tier,salary_aed,commission_aed,earned_date,payment_date) VALUES (2026,8,2000000,180000,'Tier 3',6000,9000,'2026-08-31','2026-10-31')")
    snapshot=db.mobile_sync_snapshot()
    assert snapshot["vehicles"][0]["vehicle_name"]=="2024 Porsche 911"
    assert snapshot["months"][0]["purchasing_budget_aed"]==2_000_000
    assert snapshot["earnings"][0]["tier"]=="Tier 3"
    assert set(snapshot)=={"vehicles","months","earnings","schedule","kpiCalls","kpiWork"}


def test_hit_kpi_reduces_vehicle_desk_tier_goal(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); month=date.today().strftime("%Y-%m"); db.add_kpi_calls("0501234567",240,date.today().isoformat()); hits,reduction=monthly_kpi_adjustment(db,month); assert hits==1 and reduction==Decimal("0.005")
    window=MainWindow(db); desk=window.pages["vehicles"]; desk.month.setCurrentIndex(date.today().month-1); desk.refresh(); assert desk.current_result.rate==Decimal("0.04") and "-0.5% from tier goals" in desk.achievement.text() and "Tier 3 9%" in desk.schedule.text(); window.close()


def test_vehicle_desk_progress_uses_next_tier_target():
    maximum,value,label=next_tier_progress(Decimal("7.60"),CommissionTier.TIER_3,(Decimal("0.08"),Decimal("0.10"),Decimal("0.125")))
    assert (maximum,value,label)==(800,760,"%p% to Tier 3")
    assert round(value/maximum*100)==95


def test_call_log_date_is_readable():
    assert display_call_date("2026-08-05")=="05 Aug 2026"


def test_call_tracker_pace_and_required_average():
    pace=call_month_pace(40,"2026-08",240,date(2026,8,7))
    assert pace["state"]=="behind" and pace["pace_delta"]==-7
    assert pace["remaining"]==200 and pace["days_left"]==25 and pace["average_needed"]==8
    ahead=call_month_pace(55,"2026-08",240,date(2026,8,7))
    assert ahead["state"]=="ahead" and ahead["pace_delta"]==8


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


def test_stock_vehicle_edit_dialog_prefills_matching_fields(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); vehicle_id=db.add_vehicle(vehicle_name="2024 Audi Q8",purchase_type="cash",purchase_price_aed=227000,expected_sale_price_aed=285000,purchased_date="2026-08-14",market_model_year=2024,market_trim="S line",mileage_km=15000,external_stock_number="13833")
    vehicle=db.query("SELECT * FROM vehicles WHERE id=?",(vehicle_id,))[0]; dialog=VehicleDialog(db,vehicle=vehicle); values=dialog.values()
    assert values["vehicle_name"]=="2024 Audi Q8" and values["market_trim"]=="S line"
    assert values["external_stock_number"]=="13833" and values["mileage_km"]==15000
    dialog.close()


def test_pipeline_exact_stock_number_is_visibly_green(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); vehicle_id=db.add_vehicle(vehicle_name="2024 Audi Q8",purchase_type="cash",purchase_price_aed=227000,expected_sale_price_aed=285000,purchased_date="2026-08-14",external_stock_number="13833")
    today=date.today().isoformat(); db.execute("""INSERT INTO pipeline_appointments(appointment_date,source_row_key,stock_number,customer_name,vehicle_text,matched_vehicle_id,match_grade,match_detail)
        VALUES (?,?,?,?,?,?,?,?)""",(today,"today-1","13833","Buyer","Audi Q8 2024",vehicle_id,"green","Exact stock number 13833"))
    page=PipelinePage(db); profit_item=page.table.item(0,5); stock_number_item=page.table.item(0,6)
    assert page.table.item(0,3).text()=="Audi Q8 2024" and page.table.item(0,4).text()=="2024 Audi Q8"
    assert page.table.columnWidth(3)>=200 and page.table.columnWidth(4)>=180
    assert profit_item.text()=="AED +58,000" and profit_item.foreground().color().name()==COLORS["green"]
    assert stock_number_item.text()=="✓ 13833"
    assert stock_number_item.foreground().color().name()==COLORS["green"]
    assert "Matched to your Runway stock by SN" in stock_number_item.toolTip()
    page.close()


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


def test_offer_route_uses_three_percentage_bands():
    assert offer_route(100_000,90_000)["key"]=="strong"
    assert offer_route(100_000,89_999)["key"]=="flexibility"
    assert offer_route(100_000,80_000)["key"]=="flexibility"
    assert offer_route(100_000,79_999)["key"]=="qualify"


def test_offer_route_calculator_generates_copyable_sequence(tmp_path: Path,monkeypatch):
    application=app(); db=Database(tmp_path/"data.db"); page=WhatsAppTemplatesPage(db); confirmations=[]
    monkeypatch.setattr("dxb_runway.screens.QMessageBox.information",lambda *args: confirmations.append(args[2]))
    page.route_listing.setValue(82_000); page.route_offer.setValue(70_000); page.route_vehicle.setText("2021 Volkswagen Tiguan")
    assert page.route_percent.text()=="85.4% of asking" and page.route_title.text()=="Ask flexibility first"
    assert page.route_step.count()==3 and page.route_step.itemText(0)=="1 · Confirm availability"
    page.route_step.setCurrentIndex(1); assert "AED 82,000" in page.route_preview.toPlainText()
    page.copy_route_message(); assert application.clipboard().text()==page.route_preview.toPlainText()
    assert confirmations==["Recommended message copied.\n\nIt is ready to paste into WhatsApp."]
    page.close()


def test_offer_route_messages_match_recommended_order():
    strong=offer_message_steps("strong","Tiguan",115_000,105_000); low=offer_message_steps("qualify","",100_000,70_000)
    assert len(strong)==2 and "AED 105,000" in strong[1][1]
    assert len(low)==4 and "quick sale" in low[1][1] and "best figure" in low[2][1]


def test_sold_elsewhere_action_deletes_selected_customer(tmp_path: Path,monkeypatch):
    application=app(); db=Database(tmp_path/"data.db"); customer_id=db.add_customer_contact({"customer_name":"Gone seller","vehicle_name":"Audi S3","vehicle_age_years":2022,"phone_last5":"54321"}); window=MainWindow(db); page=window.pages["contacts"]; page.tables["today"].selectRow(0)
    monkeypatch.setattr("dxb_runway.screens.QMessageBox.question",lambda *args: QMessageBox.StandardButton.Yes)
    page.sold_elsewhere()
    assert db.query("SELECT id FROM customer_contacts WHERE id=?",(customer_id,))==[] and page.tables["today"].rowCount()==0
    window.close()


def test_every_major_screen_constructs_and_navigates(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); db.seed_demo()
    window=MainWindow(db)
    assert set(window.pages)=={"dashboard","todo","success","kpi","contacts","inspection","templates","stock","stock_action","vehicles","gym_today","gym_training","gym_nutrition","gym_progress","gym_meals","transactions","debt","scenarios","budgets","calendar","schedule","pipeline","goals","vehicle_history","reports","intelligence","ask_runway","settings"}
    assert [[item[0] for item in section[3]] for section in NAV_SECTIONS]==[["dashboard"],["stock","vehicles","kpi","schedule","stock_action","vehicle_history","pipeline","todo","success","calendar"],["intelligence","ask_runway"],["contacts","inspection","templates","settings"]]
    assert window.nav_buttons["success"].property("section")=="leads"
    assert window.nav_buttons["vehicles"].property("section")=="leads"
    assert window.nav_buttons["vehicle_history"].property("section")=="leads"
    assert window.nav_buttons["stock"].property("section")=="leads"
    assert window.nav_buttons["schedule"].property("section")=="leads"
    assert window.nav_buttons["pipeline"].property("section")=="leads"
    assert window.nav_buttons["contacts"].property("section")=="other"
    assert window.nav_buttons["inspection"].property("section")=="other"
    assert window.nav_buttons["templates"].property("section")=="other"
    assert window.nav_buttons["intelligence"].property("section")=="ai"
    assert window.nav_buttons["ask_runway"].property("section")=="ai"
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
    success=window.pages["success"]
    contacts=window.pages["contacts"]
    inspection=window.pages["inspection"]
    templates=window.pages["templates"]
    history=window.pages["vehicle_history"]
    assert vehicles.month.count()==12
    assert vehicles.tier_table.rowCount()==12 and vehicles.tier_table.columnCount()==7
    assert "AED" in vehicles.tier_table.item(0,3).text() and "AED" in vehicles.tier_table.item(0,5).text()
    assert "Factory" in vehicles.tier_table.item(0,3).text() and "Pay 5%" in vehicles.tier_table.item(0,3).text()
    assert "KPI" not in vehicles.tier_table.item(0,3).text()
    assert vehicles.tier_table.rowHeight(0)>=62 and vehicles.tier_table.columnWidth(3)>=215
    selected_table_budget=db.performance_budget(vehicles.selected_month())
    assert vehicles.tier_table.item(0,1).text()==f"{selected_table_budget:,.0f}" and vehicles.tier_table.item(6,1).text()==f"{selected_table_budget:,.0f}"
    july_budget=db.performance_budget(vehicles.selected_month()); july_t3=TARGET_PERCENTAGES[7][0]; expected_t3=money(Decimal(db.get_setting("salary_aed"))+money(july_budget*july_t3)*Decimal("0.05"))
    assert vehicles.tier_earnings["tier3"].value.text()==f"AED {expected_t3:,.0f}"
    assert "before KPI" in vehicles.tier_earnings["tier3"].detail.text()
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
    assert history.table.columnCount()==6 and history.performance_table.columnCount()==8
    assert history.performance_table.rowCount()==1 and history.performance_table.item(0,3).text() in {"A+","A","B","C","C-"}
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
    assert stock.table.columnCount()==11 and "SPEED GRADE" in stock.table.horizontalHeaderItem(6).text() and "DEAL DRIVE" in stock.table.horizontalHeaderItem(7).text() and "INTELLIGENCE" in stock.table.horizontalHeaderItem(8).text()
    assert "STOCK NO" in stock.table.horizontalHeaderItem(9).text() and "KISSFLOW" in stock.table.horizontalHeaderItem(10).text()
    assert stock.table.verticalScrollBarPolicy()==Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert stock.table.height()>=420
    assert success.table.rowCount()==10 and success.table.item(0,1).text()=="Keep cash budget deployed"
    assert "AED" in success.metrics["target"].value.text() and "sold" in success.metrics["projected"].detail.text()
    assert set(stock.spend_targets)=={"tier3","tier2","tier1"} and "budget" in stock.spend_targets["tier3"].detail.text()
    assert stock.findChild(QScrollArea) is not None
    window.resize(1480,920); window.navigate("stock"); window.show(); application.processEvents()
    spend_card=stock.spend_targets["tier3"]
    assert spend_card.mapTo(stock,QPoint(0,spend_card.height())).y() <= stock.spend_note.mapTo(stock,QPoint(0,0)).y()
    assert "remaining" in stock.live_budget_value.text() and "revolving" in stock.live_budget_detail.text()
    assert "value" in stock.metrics and "includes consignments" in stock.metrics["value"].detail.text()
    assert "realistic_potential" in stock.metrics and "maximum_potential" in stock.metrics
    assert "profit" in stock.metrics["realistic_potential"].detail.text() and "total" in stock.metrics["maximum_potential"].detail.text()
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


def test_openclaw_json_envelope_displays_only_assistant_text():
    payload={"status":"ok","result":{"payloads":[{"text":"BUY — the evidence is strong."}],"meta":{"finalAssistantVisibleText":"BUY — the evidence is strong."}}}
    assert openclaw_answer(payload)=="BUY — the evidence is strong."


def test_large_openclaw_evidence_is_serialised_for_stdin_not_shell_arguments():
    prompt="stock evidence "*100_000
    request=json.loads(openclaw_request(prompt))
    assert request["input"][0]["content"][0]["text"]==prompt
    assert request["model"]=="openclaw/dxb-runway"


def test_intelligence_page_can_store_and_forget_manual_memory(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); window=MainWindow(db)
    page=window.pages["intelligence"]; page.memory_input.setText("Always explain seasonal demand")
    page._sync_ai_context=lambda: None
    page.add_memory()
    assert db.query("SELECT memory_text FROM intelligence_memories WHERE active=1")[0][0]=="Always explain seasonal demand"
    page.memory_table.selectRow(0); page.forget_selected_memory()
    assert db.query("SELECT COUNT(*) FROM intelligence_memories WHERE active=1")[0][0]==0
    window.close()


def test_ask_runway_is_separate_and_animates_received_answer(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); window=MainWindow(db)
    intelligence=window.pages["intelligence"]
    assert [intelligence.tabs.tabText(index) for index in range(intelligence.tabs.count())]==["Opportunity check","Historical data","Vehicle grades","Market Watchlist","Market Radar","Dealer Trust","Deal Drive","Memory"]
    chat=window.pages["ask_runway"]; chat._busy=True; chat._chat_answer("Evidence first. Buy only at the right margin."); chat.typing_timer.stop()
    assert len(chat.findChildren(QWidget, "agentAvatar"))>=2
    while chat._typing_index < len(chat._typing_answer): chat._typing_step()
    assert chat.state.text()=="●  Ready"
    chat._follow_latest=False;chat.refresh();application.processEvents()
    assert chat._follow_latest and chat.chat_scroll.verticalScrollBar().value()==chat.chat_scroll.verticalScrollBar().maximum()
    assert db.query("SELECT message FROM intelligence_chat_messages WHERE role='assistant'")[0][0].startswith("Evidence first")
    window.navigate("ask_runway"); assert window.context.text()=="ASK RUNWAY"
    window.close()


def test_gym_defaults_food_habits_and_measurements(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); profile=db.gym_profile()
    assert profile["weight_kg"]==70 and profile["height_cm"]==175
    assert profile["calorie_target"]==2200 and profile["protein_target_g"]==140 and profile["fibre_target_g"]==30
    meal_id=db.add_gym_food({"meal_name":"Chicken bowl","calories":500,"protein_g":45,"carbs_g":50,"fat_g":14,"fibre_g":8})
    totals=db.gym_daily_totals(); assert totals["calories"]==500 and totals["protein_g"]==45 and totals["fibre_g"]==8
    db.save_gym_habit(water_ml=1250,bowel_movement=True,stool_score=4); habit=db.gym_habit(); assert habit["water_ml"]==1250 and habit["bowel_movement"]==1 and habit["stool_score"]==4
    db.add_gym_measurement({"weight_kg":69.8,"waist_cm":84}); assert db.gym_profile()["weight_kg"]==69.8
    db.delete_gym_food(meal_id); assert db.gym_daily_totals()["calories"]==0


def test_nutrition_can_review_and_backfill_yesterday(tmp_path: Path,monkeypatch):
    application=app(); db=Database(tmp_path/"data.db"); page=GymNutritionPage(db); yesterday=QDate.currentDate().addDays(-1)
    monkeypatch.setattr("dxb_runway.gym.QMessageBox.information",lambda *args: None)
    page.log_date.setDate(yesterday); page.meal_name.setText("Forgotten chicken bowl"); page.meal_values["protein_g"].setValue(45); page.add_meal(); page.refresh()
    rows=db.gym_food_entries(yesterday.toString("yyyy-MM-dd"))
    assert len(rows)==1 and rows[0]["meal_name"]=="Forgotten chicken bowl" and rows[0]["protein_g"]==45
    assert page.entries.rowCount()==1 and page.entries.item(0,0).text()=="Forgotten chicken bowl"
    page.close()


def test_gym_migration_recovers_interrupted_schema_stamp(tmp_path: Path):
    application=app(); path=tmp_path/"data.db"; db=Database(path)
    with db.connect() as connection:
        for table in ("gym_exercise_logs","gym_workouts","gym_food_entries","gym_measurements","gym_habits","gym_water_entries","gym_meals","gym_profile"):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("PRAGMA user_version=19")
    recovered=Database(path)
    assert recovered.query("PRAGMA user_version")[0][0]==SCHEMA_VERSION
    assert recovered.gym_profile()["weight_kg"]==70 and len(recovered.gym_meals())>=10


def test_gym_workout_and_meal_library_pages(tmp_path: Path,monkeypatch):
    application=app(); db=Database(tmp_path/"data.db"); window=MainWindow(db)
    monkeypatch.setattr("dxb_runway.gym.QMessageBox.information",lambda *args: None)
    training=window.pages["gym_training"]; assert training.exercise_table.rowCount()==7 and training.exercise_table.columnCount()==7
    assert training.exercise_table.item(0,1).text()=="3 × 8–12" and training.exercise_table.item(0,2).text()=="First session"
    training.exercise_table.cellWidget(0,5).setValue(80); training.log_workout(); assert len(db.gym_workouts())==1 and db.gym_workouts()[0]["volume_kg"]>0
    training.load_template(); assert "80 kg" in training.exercise_table.item(0,2).text() and db.gym_last_exercise("Leg press")["weight_kg"]==80
    meals=window.pages["gym_meals"]; assert meals.table.rowCount()>=10 and "protein" in meals.bowl_result.text()
    initial=db.gym_daily_totals()["calories"]; meals.add_selected(); assert db.gym_daily_totals()["calories"]>initial
    window.close()


def test_nutrition_bottle_log_updates_water_score_and_history(tmp_path: Path,monkeypatch):
    application=app(); db=Database(tmp_path/"data.db"); window=MainWindow(db); page=window.pages["gym_nutrition"]
    monkeypatch.setattr("dxb_runway.gym.QMessageBox.information",lambda *args: None)
    page.add_water(500,"Bottle"); assert db.gym_habit()["water_ml"]==500 and len(db.gym_water_entries())==1
    assert page.water_log.rowCount()==1 and "500 ml" in page.water_card.value.text() and page.water_progress.value()==20
    entry_id=db.gym_water_entries()[0]["id"]; db.delete_gym_water(entry_id); page.refresh(); assert db.gym_habit()["water_ml"]==0 and page.water_log.rowCount()==0
    first_meal=page.quick_meal.itemData(1); page.quick_meal.setCurrentIndex(1); page.quick_add_meal(); assert first_meal and len(db.gym_food_entries())==1 and db.gym_logging_streak()==1
    assert page.score_card.value.text()!="0%" and page.coach_title.text()
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
