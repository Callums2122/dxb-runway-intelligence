from dxb_runway.database import Database
from dxb_runway.deal_drive import DealDriveClient, DealDriveError, comparison_exclusion, comparison_summary, market_evidence, save_market_snapshot, sync_status, velocity_rankings


def test_allowlisted_client_logs_in_and_chunks_market_details():
    calls = []
    def transport(payload, token):
        calls.append((payload, token))
        query = payload["query"]
        if "mutation Login" in query: return {"login": {"accessToken": "secret", "refreshToken": "refresh"}}
        if "UAEOfferIds" in query: return {"marketOffers": {"edges": [{"node": str(i)} for i in range(205)]}}
        return {"marketOffersData": [{"id": value} for value in payload["variables"]["input"]]}
    client = DealDriveClient(transport, workspace_id="workspace-123"); client.login("owner@example.com", "password")
    offers = client.fetch_market(limit=500)
    assert len(offers) == 205
    assert len(calls) == 5
    assert calls[0][1] is None and calls[1][1] == "secret"
    assert "password" not in str(calls[1:])


def test_market_access_requires_workspace_id():
    client = DealDriveClient(lambda payload, token: {"login": {"accessToken": "secret"}})
    client.login("owner@example.com", "password")
    try:
        client.verify_market_access()
        assert False, "Expected missing Workspace ID to stop the request"
    except Exception as error:
        assert "Workspace ID" in str(error)


def test_broad_market_sync_clamps_to_documented_api_limit():
    calls = []
    def transport(payload, token):
        calls.append(payload)
        if "mutation Login" in payload["query"]: return {"login": {"accessToken": "secret"}}
        if "UAEOfferIds" in payload["query"]: return {"marketOffers": {"edges": []}}
        return {}
    client = DealDriveClient(transport, workspace_id="workspace-123")
    client.login("owner@example.com", "password")
    client.fetch_market(limit=10_000)
    assert calls[1]["variables"]["input"]["limit"] == 1000


def test_catalog_trim_matching_ignores_spacing_hyphens_and_case():
    def transport(payload, token):
        search=payload["variables"]["input"]["search"]
        nodes=[{"id":"trim-1","name":"S line"}] if search in {"S-line","S line","Sline",""} else []
        return {"catalogTrims":{"edges":[{"node":node} for node in nodes]}}
    client=DealDriveClient(transport,workspace_id="workspace-123")
    result=client._catalog_match("trims","catalogTrims","S-line",{"catalogModelIds":["q8"]})
    assert result=={"id":"trim-1","name":"S line"}


def test_unresolved_trim_error_lists_real_catalog_values():
    def transport(payload, token):
        nodes=[{"id":"one","name":"Premium Plus"},{"id":"two","name":"Black Edition"}] if payload["variables"]["input"]["search"]=="" else []
        return {"catalogTrims":{"edges":[{"node":node} for node in nodes]}}
    client=DealDriveClient(transport,workspace_id="workspace-123")
    try:client._catalog_match("trims","catalogTrims","Unknown trim")
    except DealDriveError as error:
        assert "Available values:" in str(error) and "Black Edition" in str(error) and "Premium Plus" in str(error)
    else:assert False,"Expected unresolved catalogue trim to fail safely"


def test_offer_variant_matching_reads_model_version_when_trim_is_empty():
    trofeo={"catalogTrim":None,"catalogModification":None,"catalogModelVersion":{"name":"Trofeo","shortName":"Trofeo"}}
    modena={"catalogTrim":None,"catalogModification":None,"catalogModelVersion":{"name":"Modena"}}
    assert DealDriveClient._catalog_key("trofeo") in DealDriveClient._offer_variant_keys(trofeo)
    assert DealDriveClient._catalog_key("trofeo") not in DealDriveClient._offer_variant_keys(modena)
    assert DealDriveClient._offer_variant_names(trofeo)==["Trofeo"]


def test_snapshots_are_retained_and_latest_market_is_summarised(tmp_path):
    db = Database(tmp_path / "runway.db")
    offer = {"id": "one", "price": 250000, "catalogBrand": {"name": "Audi"}, "catalogModel": {"name": "Q8"},
             "catalogTrim": {"name": "S line"}, "modelYear": 2024, "mileage": 12000,
             "catalogMileageUnit": {"multiplierToKm": 1}, "catalogRegionalSpecs":{"name":"GCC"},
             "marketSellerType":{"name":"Dealer"}, "marketSeller":{"id":"dealer-1","name":"Dubai Dealer"}, "address":"Dubai"}
    save_market_snapshot(db, [offer], "AE", 5000)
    save_market_snapshot(db, [{**offer, "price": 240000}], "AE", 5000)
    status = sync_status(db)
    assert status["snapshots"] == 2 and status["retained_offers"] == 2
    evidence = market_evidence(db)
    assert evidence["offer_count"] == 1
    assert evidence["groups"][0]["average_asking_aed"] == 240000


def test_policy_excludes_private_non_gcc_and_disallowed_emirates():
    base={"marketSellerType":{"name":"Dealer"},"catalogRegionalSpecs":{"name":"GCC"},"address":"Dubai"}
    assert comparison_exclusion(base) == ""
    assert "private" in comparison_exclusion({**base,"marketSellerType":{"name":"Private"}})
    assert "Sharjah" in comparison_exclusion({**base,"address":"Sharjah"})
    assert "non-GCC" in comparison_exclusion({**base,"catalogRegionalSpecs":{"name":"US Spec"}})
    assert comparison_exclusion({**base,"catalogRegionalSpecs":{"name":"US Spec"}},allow_imports=True) == ""


def test_comparison_keeps_live_and_history_separate_and_uses_medians(tmp_path):
    db=Database(tmp_path/"runway.db")
    base={"catalogBrand":{"name":"Audi"},"catalogModel":{"name":"Q8"},"catalogTrim":{"name":"S line"},"modelYear":2021,
          "mileage":30000,"catalogMileageUnit":{"multiplierToKm":1},"catalogRegionalSpecs":{"name":"GCC"},
          "marketSellerType":{"name":"Dealer"},"address":"Dubai"}
    offers=[]
    for index,price in enumerate((200000,210000,900000)):
        offers.append({**base,"id":f"live-{index}","price":price,"marketSeller":{"id":f"d-{index}"},"_active_market":True,"_comparison_weight":1})
    offers.append({**base,"id":"old","price":190000,"marketSeller":{"id":"old-d"},"deleted":True,"_active_market":False})
    save_market_snapshot(db,offers,"AE",100)
    result=comparison_summary(db,"Audi","Q8","S line",2021,30000)
    assert result["live_market_asking"]["median_price_aed"] == 210000
    assert result["live_market_asking"]["average_price_aed"] > 400000
    assert result["historical_sold_or_removed"]["median_price_aed"] == 190000


def test_velocity_uses_disappearance_for_fast_and_listing_age_for_slow(tmp_path):
    db=Database(tmp_path/"runway.db")
    base={"catalogBrand":{"name":"Toyota"},"catalogModel":{"name":"Land Cruiser"},"catalogTrim":{"name":"GXR"},"modelYear":2022,
          "mileage":30000,"catalogMileageUnit":{"multiplierToKm":1},"catalogRegionalSpecs":{"name":"GCC"},
          "marketSellerType":{"name":"Dealer"},"address":"Dubai","publishedAt":"2026-07-01T00:00:00+00:00"}
    first=[{**base,"id":f"gone-{i}","price":200000+i,"marketSeller":{"id":f"d-{i}"}} for i in range(3)]
    first += [{**base,"id":f"stay-{i}","price":210000+i,"marketSeller":{"id":f"s-{i}"}} for i in range(3)]
    save_market_snapshot(db,first,"AE",100,sync_mode="nightly_market")
    second=[row for row in first if str(row["id"]).startswith("stay")]
    save_market_snapshot(db,second,"AE",100,sync_mode="nightly_market")
    result=velocity_rankings(db)
    assert result["status"]=="ready"
    assert result["fast"][0]["samples"]==3
    assert result["slow"][0]["samples"]==3
