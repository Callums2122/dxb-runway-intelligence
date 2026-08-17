from dxb_runway.database import Database
from dxb_runway.deal_drive import DealDriveClient, market_evidence, save_market_snapshot, sync_status


def test_allowlisted_client_logs_in_and_chunks_market_details():
    calls = []
    def transport(payload, token):
        calls.append((payload, token))
        query = payload["query"]
        if "mutation Login" in query: return {"login": {"accessToken": "secret", "refreshToken": "refresh"}}
        if "UAEOfferIds" in query: return {"marketOffers": {"edges": [{"node": str(i)} for i in range(205)]}}
        return {"marketOffersData": [{"id": value} for value in payload["variables"]["input"]]}
    client = DealDriveClient(transport); client.login("owner@example.com", "password")
    offers = client.fetch_market(limit=500)
    assert len(offers) == 205
    assert len(calls) == 5
    assert calls[0][1] is None and calls[1][1] == "secret"
    assert "password" not in str(calls[1:])


def test_snapshots_are_retained_and_latest_market_is_summarised(tmp_path):
    db = Database(tmp_path / "runway.db")
    offer = {"id": "one", "price": 250000, "catalogBrand": {"name": "Audi"}, "catalogModel": {"name": "Q8"},
             "catalogTrim": {"name": "S line"}, "modelYear": 2024, "mileage": 12000,
             "catalogMileageUnit": {"multiplierToKm": 1}}
    save_market_snapshot(db, [offer], "AE", 5000)
    save_market_snapshot(db, [{**offer, "price": 240000}], "AE", 5000)
    status = sync_status(db)
    assert status["snapshots"] == 2 and status["retained_offers"] == 2
    evidence = market_evidence(db)
    assert evidence["offer_count"] == 1
    assert evidence["groups"][0]["average_asking_aed"] == 240000
