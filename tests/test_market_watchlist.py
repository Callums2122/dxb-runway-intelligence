from dxb_runway.database import Database
from dxb_runway.market_watchlist import (
    delete_watchlist_item, radar_rows, save_watchlist_item, set_watchlist_active,
    snapshot_watchlist_item, watchlist_items,
)


def payload():
    return {"make":"Audi","model":"Q8","trim":"S line","year_from":2021,"year_to":2022,"gcc_only":True,
            "mileage_min":20000,"mileage_max":80000,"dealer_only":True,"exclude_sharjah_ajman":True,"active":True}


def test_watchlist_crud_is_owner_controlled(tmp_path):
    db=Database(tmp_path/"runway.db")
    item_id=save_watchlist_item(db,payload())
    assert watchlist_items(db)[0]["model"]=="Q8"
    set_watchlist_active(db,item_id,False)
    assert watchlist_items(db)[0]["active"]==0
    delete_watchlist_item(db,item_id)
    assert watchlist_items(db)==[]


def test_snapshot_retains_cohort_and_builds_radar(tmp_path):
    db=Database(tmp_path/"runway.db"); item_id=save_watchlist_item(db,payload()); item=watchlist_items(db)[0]
    class Client:
        def evaluate_subject(self,**kwargs):
            offers=[]
            for index,price in enumerate((180000,190000,200000,210000,220000,230000,240000,250000)):
                offers.append({"id":str(index),"price":price,"publishedAt":"2026-07-01T00:00:00+00:00","mileage":40000,
                               "catalogRegionalSpecs":{"name":"GCC"},"marketSellerType":{"name":"Dealer"},"address":"Dubai","_active_market":True})
            return offers,{"evaluation":{"marketPrice":215000,"liveMarket":{"weightedAvgPrice":212000}}}
    snapshot_watchlist_item(db,Client(),item)
    rows=radar_rows(db)
    assert len(rows)==1 and rows[0]["sample_size"]==8
    assert rows[0]["median_asking_aed"]==215000 and rows[0]["confidence"]=="Medium"
