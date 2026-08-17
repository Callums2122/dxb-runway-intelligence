from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .database import Database
from .dealer_trust import dealer_evidence, weighted_median
from .deal_drive import DealDriveClient, DealDriveError, KeychainCredentials, comparison_exclusion


def watchlist_items(db: Database, *, active_only: bool = False) -> list[dict[str, Any]]:
    where = "WHERE active=1 AND ignored_suggestion=0" if active_only else "WHERE ignored_suggestion=0"
    rows = db.query(f"""SELECT w.*,(SELECT MAX(captured_at) FROM market_watchlist_snapshots s WHERE s.watchlist_id=w.id) last_synced,
        (SELECT detail_json FROM market_watchlist_snapshots s WHERE s.watchlist_id=w.id ORDER BY captured_at DESC LIMIT 1) last_detail_json
        FROM market_watchlist w {where} ORDER BY active DESC,make,model,trim""")
    return [dict(row) for row in rows]


def save_watchlist_item(db: Database, payload: dict[str, Any], item_id: int | None = None) -> int:
    values = (
        str(payload["make"]).strip(), str(payload["model"]).strip(), str(payload.get("trim", "")).strip(),
        int(payload["year_from"]), int(payload["year_to"]), int(bool(payload.get("gcc_only", True))),
        payload.get("mileage_min"), payload.get("mileage_max"), int(bool(payload.get("dealer_only", True))),
        int(bool(payload.get("exclude_sharjah_ajman", True))), int(bool(payload.get("active", True))),
    )
    if not values[0] or not values[1] or not values[2]:
        raise ValueError("Make, model and exact trim are required.")
    if values[3] > values[4]:
        raise ValueError("Year from cannot be later than year to.")
    if item_id:
        db.execute("""UPDATE market_watchlist SET make=?,model=?,trim=?,year_from=?,year_to=?,gcc_only=?,mileage_min=?,mileage_max=?,
            dealer_only=?,exclude_sharjah_ajman=?,active=?,ignored_suggestion=0,updated_at=CURRENT_TIMESTAMP WHERE id=?""", values + (item_id,))
        return item_id
    return db.execute("""INSERT INTO market_watchlist(make,model,trim,year_from,year_to,gcc_only,mileage_min,mileage_max,dealer_only,
        exclude_sharjah_ajman,active) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(make,model,trim,year_from,year_to) DO UPDATE SET active=1,ignored_suggestion=0,updated_at=CURRENT_TIMESTAMP""", values)


def delete_watchlist_item(db: Database, item_id: int) -> None:
    db.execute("DELETE FROM market_watchlist WHERE id=?", (item_id,))


def set_watchlist_active(db: Database, item_id: int, active: bool) -> None:
    db.execute("UPDATE market_watchlist SET active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (int(active), item_id))


def watchlist_suggestions(db: Database, limit: int = 8) -> list[dict[str, Any]]:
    interest = db.query("""SELECT make,model,trim,MIN(model_year) year_from,MAX(model_year) year_to,SUM(observations) samples
        FROM market_watchlist_interest i WHERE make<>'' AND model<>'' AND trim<>''
        AND NOT EXISTS (SELECT 1 FROM market_watchlist w WHERE lower(w.make)=lower(i.make) AND lower(w.model)=lower(i.model) AND lower(w.trim)=lower(i.trim))
        GROUP BY make,model,trim HAVING SUM(observations)>=3 ORDER BY samples DESC LIMIT ?""", (limit,))
    rows = db.query("""SELECT make,model,trim,MIN(model_year) year_from,MAX(model_year) year_to,COUNT(*) samples
        FROM intelligence_records r WHERE duplicate_of IS NULL AND review_reason='' AND make<>'' AND model<>'' AND trim<>''
        AND NOT EXISTS (SELECT 1 FROM market_watchlist w WHERE lower(w.make)=lower(r.make) AND lower(w.model)=lower(r.model) AND lower(w.trim)=lower(r.trim))
        GROUP BY make,model,trim HAVING COUNT(*)>=3 ORDER BY samples DESC LIMIT ?""", (limit,))
    output=[dict(row) for row in interest]
    keys={(row["make"].casefold(),row["model"].casefold(),row["trim"].casefold()) for row in output}
    output.extend(dict(row) for row in rows if (row["make"].casefold(),row["model"].casefold(),row["trim"].casefold()) not in keys)
    return output[:limit]


def record_market_interest(db: Database, make: str, model: str, trim: str, model_year: int | None) -> None:
    if not make.strip() or not model.strip() or not trim.strip():
        return
    db.execute("""INSERT INTO market_watchlist_interest(make,model,trim,model_year,observations) VALUES (?,?,?,?,1)
        ON CONFLICT(make,model,trim,model_year) DO UPDATE SET observations=observations+1,last_seen=CURRENT_TIMESTAMP""",
        (make.strip(),model.strip(),trim.strip(),model_year))


def ignore_suggestion(db: Database, suggestion: dict[str, Any]) -> None:
    db.execute("""INSERT OR IGNORE INTO market_watchlist(make,model,trim,year_from,year_to,active,ignored_suggestion)
        VALUES (?,?,?,?,?,0,1)""", (suggestion["make"], suggestion["model"], suggestion["trim"], suggestion["year_from"], suggestion["year_to"]))


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed=datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed).astimezone(timezone.utc)
    except ValueError:
        return None


def watchlist_sync_due(item: dict[str, Any], now: datetime | None = None, cooldown_days: int = 3) -> bool:
    """Return true only for never-synced, changed, or 72-hour-old cohorts."""
    current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc); last=_timestamp(item.get("last_synced"))
    if last is None:return True
    try:detail=json.loads(str(item.get("last_detail_json") or "{}"))
    except json.JSONDecodeError:detail={}
    if detail.get("speed_source")!="deal_drive_archive":return True
    updated=_timestamp(item.get("updated_at"))
    if updated is not None and updated>last:return True
    return current-last>=timedelta(days=cooldown_days)


def _trend(db: Database, watchlist_id: int, captured: datetime, days: int, median_price: float | None) -> float | None:
    if not median_price:
        return None
    target = (captured - timedelta(days=days)).isoformat()
    rows = db.query("""SELECT median_asking_aed FROM market_watchlist_snapshots
        WHERE watchlist_id=? AND captured_at<=? AND median_asking_aed IS NOT NULL ORDER BY captured_at DESC LIMIT 1""", (watchlist_id, target))
    if not rows or not rows[0]["median_asking_aed"]:
        return None
    previous = float(rows[0]["median_asking_aed"])
    return round((median_price - previous) / previous * 100, 1)


def _score(sample: int, median_age: float | None, new: int, exits: int, reductions: int, previous_sample: int, change_30d: float | None) -> float:
    if not sample:
        return 0.0
    exit_rate = exits / max(1, previous_sample)
    exit_component = min(100.0, exit_rate * 500) if previous_sample else 50.0
    age_component = max(0.0, min(100.0, 100 - float(median_age or 50) * 1.7))
    supply_change = (sample - previous_sample) / max(1, previous_sample) if previous_sample else 0
    supply_component = max(0.0, min(100.0, 50 - supply_change * 200))
    reduction_component = max(0.0, 100 - reductions / max(1, sample) * 300)
    price_component = 70.0 if change_30d is None else max(0.0, min(100.0, 75 - abs(change_30d) * 5 + max(0, change_30d) * 2))
    sample_component = min(100.0, sample / 20 * 100)
    return round(exit_component * .30 + age_component * .25 + supply_component * .15 + price_component * .15 + reduction_component * .10 + sample_component * .05, 1)


def _label(score: float) -> str:
    return "Strong" if score >= 80 else "Healthy" if score >= 60 else "Neutral" if score >= 40 else "Weak" if score >= 20 else "Avoid"


def snapshot_watchlist_item(db: Database, client: DealDriveClient, item: dict[str, Any], progress: Callable[[str], None] | None = None) -> int:
    mileage_min, mileage_max = item.get("mileage_min"), item.get("mileage_max")
    reference_mileage = int(((mileage_min or 0) + (mileage_max or 100000)) / 2)
    offers, meta = client.evaluate_subject(
        make=item["make"], model=item["model"], trim=item["trim"], year=int(item["year_from"]), year_to=int(item["year_to"]),
        mileage_km=reference_mileage, allow_imports=not bool(item["gcc_only"]), dealer_only=bool(item["dealer_only"]), progress=progress,
    )
    filtered: list[dict[str, Any]] = []; archived: list[dict[str, Any]] = []
    seen: set[str] = set()
    for offer in offers:
        offer_id = str(offer.get("id") or "")
        if not offer_id or offer_id in seen:
            continue
        reason = comparison_exclusion(offer, allow_imports=not bool(item["gcc_only"]), dealer_only=bool(item["dealer_only"]),
                                      exclude_sharjah_ajman=bool(item["exclude_sharjah_ajman"]))
        mileage = offer.get("mileage")
        if mileage_min is not None and mileage is not None and float(mileage) < float(mileage_min): reason = "Below mileage range"
        if mileage_max is not None and mileage is not None and float(mileage) > float(mileage_max): reason = "Above mileage range"
        dealer_tier,dealer_weight,_=dealer_evidence(offer)
        if dealer_tier=="exclude":reason="Dealer/location excluded by owner trust policy"
        if reason:continue
        offer["_runway_dealer_tier"]=dealer_tier; offer["_runway_dealer_weight"]=dealer_weight
        seen.add(offer_id)
        if offer.get("_active_market",not bool(offer.get("deleted"))):filtered.append(offer)
        else:archived.append(offer)
    now = datetime.now(timezone.utc)
    prices = [float(row.get("priceInWorkspaceDefaultCurrency") or row.get("price")) for row in filtered if row.get("priceInWorkspaceDefaultCurrency") or row.get("price")]
    ages = [(now - published).total_seconds() / 86400 for row in filtered if (published := _timestamp(row.get("publishedAt"))) and published <= now]
    archive_durations=[]
    for row in archived:
        published=_timestamp(row.get("publishedAt") or row.get("createdAt"));ended=_timestamp(row.get("deletedAt") or row.get("updatedAt"))
        if published and ended and ended>=published:archive_durations.append((ended-published).total_seconds()/86400)
    previous_rows = db.query("SELECT * FROM market_watchlist_snapshots WHERE watchlist_id=? ORDER BY captured_at DESC LIMIT 1", (item["id"],))
    previous = dict(previous_rows[0]) if previous_rows else None
    previous_offers = {str(row["offer_id"]): float(row["price_aed"] or 0) for row in db.query(
        "SELECT offer_id,price_aed FROM market_watchlist_snapshot_offers WHERE snapshot_id=?", (previous["id"],))} if previous else {}
    current = {str(row.get("id")): float(row.get("priceInWorkspaceDefaultCurrency") or row.get("price") or 0) for row in filtered}
    new = len(set(current) - set(previous_offers)) if previous else 0
    exits = len(set(previous_offers) - set(current)) if previous else 0
    reductions = sum(current[key] < previous_offers[key] for key in set(current) & set(previous_offers) if current[key] and previous_offers[key])
    median_price = statistics.median(prices) if prices else None
    evaluation = meta.get("evaluation") or {}
    sales_history=evaluation.get("salesHistory") or {}
    archive_days=sales_history.get("weightedAvgDaysInSale")
    if archive_days is None and archive_durations:archive_days=statistics.median(archive_durations)
    archive_sample=len(archived) or int(sales_history.get("usefulOffersCount") or 0)
    weighted = weighted_median([(float(row.get("priceInWorkspaceDefaultCurrency") or row.get("price")),float(row.get("_comparison_weight",1))*float(row.get("_runway_dealer_weight",1))) for row in filtered if row.get("priceInWorkspaceDefaultCurrency") or row.get("price")])
    change_7 = _trend(db, item["id"], now, 7, median_price); change_30 = _trend(db, item["id"], now, 30, median_price); change_90 = _trend(db, item["id"], now, 90, median_price)
    score = _score(archive_sample, float(archive_days) if archive_days is not None else None, new, exits, reductions, int(previous["sample_size"] or 0) if previous else 0, change_30)
    confidence = "High" if archive_sample >= 20 else "Medium" if archive_sample >= 8 else "Low"
    snapshot_id = db.execute("""INSERT INTO market_watchlist_snapshots(watchlist_id,captured_at,current_listings,median_asking_aed,
        weighted_market_price_aed,median_listing_age_days,new_listings,market_exits,price_reductions,sample_size,confidence,score,label,
        change_7d,change_30d,change_90d,detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        item["id"], now.isoformat(), len(filtered), median_price, weighted, archive_days, new, exits, reductions,
        archive_sample, confidence, score, _label(score), change_7, change_30, change_90, json.dumps({"evaluation": evaluation,"speed_source":"deal_drive_archive","live_median_age_days":statistics.median(ages) if ages else None,"archive_sample_size":archive_sample,"archive_observed_durations":len(archive_durations),"dealer_policy":{"direct":sum(row.get("_runway_dealer_tier")=="direct" for row in filtered+archived),"consider":sum(row.get("_runway_dealer_tier")=="consider" for row in filtered+archived),"unrated":sum(row.get("_runway_dealer_tier")=="unrated" for row in filtered+archived),"dubai_priority":True}}, default=str),
    ))
    with db.connect() as connection:
        connection.executemany("INSERT INTO market_watchlist_snapshot_offers(snapshot_id,offer_id,price_aed,published_at) VALUES (?,?,?,?)", [
            (snapshot_id, str(row.get("id")), row.get("priceInWorkspaceDefaultCurrency") or row.get("price"), row.get("publishedAt")) for row in filtered])
    return snapshot_id


def nightly_watchlist_sync(db: Database, progress: Callable[[str], None] | None = None) -> int:
    items = watchlist_items(db, active_only=True)
    if not items:
        raise DealDriveError("Nightly watchlist sync skipped: add at least one active Market Watchlist vehicle.")
    due=[item for item in items if watchlist_sync_due(item)]
    skipped=len(items)-len(due)
    if skipped and progress:progress(f"Cooldown protected · skipped {skipped} cohort{'s' if skipped!=1 else ''} synced within the last 72 hours.")
    if not due:
        if progress:progress("Everything is current · no Deal Drive fetches used.")
        return 0
    email = db.get_setting("deal_drive_email").strip(); workspace_id = db.get_setting("deal_drive_workspace_id").strip()
    password = KeychainCredentials().load(email) if email else None
    if not email or not password or not workspace_id:
        raise DealDriveError("Nightly watchlist sync skipped: Deal Drive connection is incomplete.")
    client = DealDriveClient(workspace_id=workspace_id); client.login(email, password); client.verify_market_access()
    completed = 0
    for index, item in enumerate(due, 1):
        if progress: progress(f"Due {index}/{len(due)} · {item['year_from']}–{item['year_to']} {item['make']} {item['model']} {item['trim']}")
        snapshot_watchlist_item(db, client, item, progress)
        completed += 1
    return completed


def radar_rows(db: Database) -> list[dict[str, Any]]:
    rows = db.query("""SELECT w.*,s.captured_at,s.current_listings,s.median_asking_aed,s.weighted_market_price_aed,
        s.median_listing_age_days,s.new_listings,s.market_exits,s.price_reductions,s.sample_size,s.confidence,s.score,s.label,
        s.change_7d,s.change_30d,s.change_90d,s.detail_json FROM market_watchlist w
        JOIN market_watchlist_snapshots s ON s.id=(SELECT id FROM market_watchlist_snapshots WHERE watchlist_id=w.id ORDER BY captured_at DESC LIMIT 1)
        WHERE w.active=1 AND w.ignored_suggestion=0 ORDER BY s.score DESC,w.make,w.model""")
    output=[]
    for row in rows:
        item=dict(row)
        try:detail=json.loads(str(item.get("detail_json") or "{}"))
        except json.JSONDecodeError:detail={}
        item["live_median_age_days"]=detail.get("live_median_age_days");item["speed_source"]=detail.get("speed_source")
        output.append(item)
    return output


def matching_market_snapshot(db: Database, make: str, model: str, trim: str, year: int | None) -> dict[str, Any] | None:
    rows = db.query("""SELECT w.*,s.* FROM market_watchlist w JOIN market_watchlist_snapshots s
        ON s.id=(SELECT id FROM market_watchlist_snapshots WHERE watchlist_id=w.id ORDER BY captured_at DESC LIMIT 1)
        WHERE lower(w.make)=lower(?) AND lower(w.model)=lower(?) AND lower(w.trim)=lower(?)
        AND (? IS NULL OR ? BETWEEN w.year_from AND w.year_to) AND w.active=1 ORDER BY s.sample_size DESC LIMIT 1""",
        (make.strip(), model.strip(), trim.strip(), year, year))
    return dict(rows[0]) if rows else None
