import json

from dxb_runway.database import Database
from dxb_runway.invoice_sync import InvoiceSyncClient, InvoiceSyncService


def test_unique_vehicle_invoice_marks_cash_stock_sold(tmp_path):
    db = Database(tmp_path / "runway.db")
    vehicle_id = db.add_vehicle(vehicle_name="Audi Q8", purchase_price_aed=227000, expected_sale_price_aed=285000, purchased_date="2026-08-01", market_model_year=2024)
    payload = {"status": "ok", "invoices": [{"messageId": "spaces/x/messages/1", "createTime": "2026-08-22T10:00:00Z", "stockNumber": "13833", "vehicle": "Audi Q8", "year": 2024, "soldPriceAed": 284999}]}
    client = InvoiceSyncClient("https://script.google.com/macros/s/example/exec", "secret", lambda request: json.dumps(payload).encode())
    result = InvoiceSyncService(db, client).sync()
    sold = db.query("SELECT * FROM vehicles WHERE id=?", (vehicle_id,))[0]
    assert result.sold == 1
    assert sold["status"] == "sold" and sold["sold_price_aed"] == 284999
    assert sold["external_stock_number"] == "13833"


def test_ambiguous_invoice_never_changes_stock(tmp_path):
    db = Database(tmp_path / "runway.db")
    for _ in range(2):
        vehicle_id = db.add_vehicle(vehicle_name="Audi Q8", purchase_price_aed=200000, expected_sale_price_aed=250000, purchased_date="2026-08-01", market_model_year=2024)
    payload = {"status": "ok", "invoices": [{"messageId": "m2", "vehicle": "Audi Q8", "year": 2024, "soldPriceAed": 250000}]}
    client = InvoiceSyncClient("https://script.google.com/macros/s/example/exec", "secret", lambda request: json.dumps(payload).encode())
    result = InvoiceSyncService(db, client).sync()
    assert result.review == 1
    assert len(db.stock_vehicles()) == 2


def test_duplicate_message_is_idempotent(tmp_path):
    db = Database(tmp_path / "runway.db")
    vehicle_id = db.add_vehicle(vehicle_name="Audi Q8", purchase_price_aed=200000, expected_sale_price_aed=250000, purchased_date="2026-08-01", market_model_year=2024)
    payload = {"status": "ok", "invoices": [{"messageId": "m3", "vehicle": "Audi Q8", "year": 2024, "soldPriceAed": 250000}]}
    client = InvoiceSyncClient("https://script.google.com/macros/s/example/exec", "secret", lambda request: json.dumps(payload).encode())
    service = InvoiceSyncService(db, client)
    assert service.sync().sold == 1
    assert service.sync().ignored == 1
    assert db.query("SELECT COUNT(*) count FROM invoice_sync_events")[0]["count"] == 1
