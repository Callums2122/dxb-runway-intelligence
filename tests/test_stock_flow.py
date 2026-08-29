import json
from datetime import date

from dxb_runway.database import Database
from dxb_runway.stock_flow import StockFlowClient, StockFlowService, classify_event


def test_classifies_requested_stages():
    assert classify_event("STOCK FLOW moved to Pull Out - Repair", "", "")[0] == "repair"
    assert classify_event("PRICE REDUCTION", "", "")[0] == "price_change"
    assert classify_event("STOCK FLOW", "Photoshoot", "")[0] == "photoshoot"
    assert classify_event("STOCK FLOW moved to Registered", "", "")== ("registered","REGISTERED")


def test_links_silverado_stock_number_and_updates_status(tmp_path):
    db=Database(tmp_path/"runway.db")
    vehicle_id=db.add_vehicle(vehicle_name="Chevrolet Silverado",purchase_price_aed=100000,expected_sale_price_aed=140000,purchased_date=date.today().isoformat(),purchase_type="cash",market_model_year=2024,market_trim="ZR2")
    payload={"status":"ok","stockEvents":[{"messageId":"m1","createTime":"2026-08-25T11:42:00Z","subject":"STOCK FLOW - Talib assigned STFL-10092 to you","workflowId":"STFL-10092","stockNumber":"13930","vehicle":"Chevrolet Silverado HD (2500-3500)","year":2024,"status":"PREP"}]}
    client=StockFlowClient("https://example.com/v1/stock-flow","secret",lambda _request:json.dumps(payload).encode())
    result=StockFlowService(db,client).sync()
    assert result.linked == 1
    row=db.query("SELECT * FROM vehicles WHERE id=?",(vehicle_id,))[0]
    assert row["external_stock_number"] == "13930"
    assert row["external_workflow_id"] == "STFL-10092"
    assert row["external_stock_status"] == "PREP"


def test_price_change_is_history_and_does_not_sell(tmp_path):
    db=Database(tmp_path/"runway.db")
    vehicle_id=db.add_vehicle(vehicle_name="Chevrolet Silverado",purchase_price_aed=100000,expected_sale_price_aed=140000,purchased_date=date.today().isoformat(),purchase_type="cash",market_model_year=2024,external_stock_number="13930")
    payload={"status":"ok","stockEvents":[{"messageId":"m2","createTime":"2026-08-26T08:00:00Z","subject":"PRICE REDUCTION","workflowId":"STFL-10092","stockNumber":"13930","vehicle":"Chevrolet Silverado","year":2024,"status":"STOCK","priceAed":135000}]}
    result=StockFlowService(db,StockFlowClient("https://example.com","secret",lambda _:json.dumps(payload).encode())).sync()
    row=db.query("SELECT * FROM vehicles WHERE id=?",(vehicle_id,))[0]
    assert result.updated == 1 and row["status"] == "stock"
    assert row["external_live_price_aed"] == 135000
    assert db.query("SELECT event_type FROM stock_flow_events")[0]["event_type"] == "price_change"


def test_registered_sells_using_cached_invoice_but_booked_does_not(tmp_path):
    db=Database(tmp_path/"runway.db");vehicle_id=db.add_vehicle(vehicle_name="Geely Monjaro",purchase_price_aed=90000,expected_sale_price_aed=115000,purchased_date="2026-08-20",purchase_type="cash",market_model_year=2026,external_stock_number="13848")
    db.execute("""INSERT INTO invoice_sync_events(source_message_id,source_created_at,stock_number,vehicle_text,model_year,sold_price_aed,matched_vehicle_id,outcome,detail)
        VALUES ('invoice-1','2026-08-28T15:00:00Z','13,848','Geely Monjaro',2026,114999,?,'review','Invoice price captured; awaiting REGISTERED')""",(vehicle_id,))
    booked={"status":"ok","stockEvents":[{"messageId":"booked-1","createTime":"2026-08-28T15:10:00Z","subject":"STOCK FLOW moved to Booked","workflowId":"STFL-1","stockNumber":"13848","vehicle":"Geely Monjaro","year":2026,"status":"BOOKED"}]}
    StockFlowService(db,StockFlowClient("https://example.com","secret",lambda _:json.dumps(booked).encode())).sync()
    assert db.query("SELECT status,external_stock_status FROM vehicles WHERE id=?",(vehicle_id,))[0]["status"]=="stock"
    registered={"status":"ok","stockEvents":[{"messageId":"registered-1","createTime":"2026-08-29T10:00:00Z","subject":"STOCK FLOW moved to Registered","workflowId":"STFL-1","stockNumber":"13848","vehicle":"Geely Monjaro","year":2026,"status":"REGISTERED"}]}
    StockFlowService(db,StockFlowClient("https://example.com","secret",lambda _:json.dumps(registered).encode())).sync()
    vehicle=db.query("SELECT * FROM vehicles WHERE id=?",(vehicle_id,))[0];invoice=db.query("SELECT * FROM invoice_sync_events")[0]
    assert vehicle["status"]=="sold" and vehicle["sold_price_aed"]==114999 and vehicle["sold_date"]=="2026-08-29"
    assert invoice["outcome"]=="sold" and "Registered status confirmed" in invoice["detail"]


def test_registered_without_invoice_stays_in_stock_for_review(tmp_path):
    db=Database(tmp_path/"runway.db");vehicle_id=db.add_vehicle(vehicle_name="RAM 1500",purchase_price_aed=178000,expected_sale_price_aed=215000,purchased_date="2026-08-20",purchase_type="cash",market_model_year=2024,external_stock_number="13862")
    payload={"status":"ok","stockEvents":[{"messageId":"registered-no-invoice","createTime":"2026-08-29T10:00:00Z","subject":"STOCK FLOW moved to Registered","stockNumber":"13862","vehicle":"RAM 1500","year":2024,"status":"REGISTERED"}]}
    StockFlowService(db,StockFlowClient("https://example.com","secret",lambda _:json.dumps(payload).encode())).sync()
    vehicle=db.query("SELECT * FROM vehicles WHERE id=?",(vehicle_id,))[0];event=db.query("SELECT * FROM stock_flow_events")[0]
    assert vehicle["status"]=="stock" and vehicle["external_stock_status"]=="REGISTERED"
    assert "awaiting matching INVOICES sale price" in event["detail"]
