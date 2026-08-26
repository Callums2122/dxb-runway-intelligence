import json
from datetime import date

from dxb_runway.database import Database
from dxb_runway.stock_flow import StockFlowClient, StockFlowService, classify_event


def test_classifies_requested_stages():
    assert classify_event("STOCK FLOW moved to Pull Out - Repair", "", "")[0] == "repair"
    assert classify_event("PRICE REDUCTION", "", "")[0] == "price_change"
    assert classify_event("STOCK FLOW", "Photoshoot", "")[0] == "photoshoot"


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
