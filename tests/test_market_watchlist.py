from dxb_runway.database import Database
from datetime import datetime, timedelta, timezone

from dxb_runway.market_watchlist import (
    archive_speed_days, delete_watchlist_item, radar_rows, save_watchlist_item, set_watchlist_active,
    snapshot_watchlist_item, watchlist_items, watchlist_sync_due,
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
            for index in range(3):
                offers.append({"id":f"archive-{index}","price":190000+index*5000,"publishedAt":"2026-05-01T00:00:00+00:00","deletedAt":f"2026-05-{21+index:02d}T00:00:00+00:00","mileage":40000,
                               "catalogRegionalSpecs":{"name":"GCC"},"marketSellerType":{"name":"Dealer"},"address":"Dubai","_active_market":False})
            return offers,{"evaluation":{"marketPrice":215000,"liveMarket":{"weightedAvgPrice":212000},"salesHistory":{"usefulOffersCount":3,"weightedAvgDaysInSale":21}}}
    snapshot_watchlist_item(db,Client(),item)
    rows=radar_rows(db)
    assert len(rows)==1 and rows[0]["sample_size"]==3 and rows[0]["current_listings"]==8
    assert rows[0]["median_asking_aed"]==215000 and rows[0]["confidence"]=="Low"
    assert rows[0]["median_listing_age_days"]==21 and rows[0]["speed_source"]=="deal_drive_archive_v2"
    assert rows[0]["live_median_age_days"] is not None


def test_watchlist_sync_uses_rolling_three_day_cooldown():
    now=datetime(2026,8,17,12,tzinfo=timezone.utc)
    base={"last_synced":(now-timedelta(hours=71)).isoformat(),"updated_at":(now-timedelta(days=5)).isoformat(),"last_detail_json":'{"speed_source":"deal_drive_archive_v2"}'}
    assert not watchlist_sync_due(base,now)
    assert watchlist_sync_due({**base,"last_synced":(now-timedelta(hours=72)).isoformat()},now)
    assert watchlist_sync_due({**base,"last_synced":None},now)


def test_editing_watchlist_cohort_bypasses_cooldown():
    now=datetime(2026,8,17,12,tzinfo=timezone.utc)
    item={"last_synced":(now-timedelta(hours=2)).isoformat(),"updated_at":(now-timedelta(hours=1)).isoformat(),"last_detail_json":'{"speed_source":"deal_drive_archive_v2"}'}
    assert watchlist_sync_due(item,now)


def test_legacy_live_age_snapshot_is_due_for_archive_speed_correction():
    now=datetime(2026,8,17,12,tzinfo=timezone.utc)
    item={"last_synced":(now-timedelta(hours=1)).isoformat(),"updated_at":(now-timedelta(days=2)).isoformat(),"last_detail_json":"{}"}
    assert watchlist_sync_due(item,now)


def test_zero_archive_days_is_rejected_and_observed_timestamps_win():
    assert archive_speed_days(0,[18,42,30])==30
    assert archive_speed_days("0",[20,40])==30
    assert archive_speed_days(27,[100,120])==27
    assert archive_speed_days(0,[]) is None
