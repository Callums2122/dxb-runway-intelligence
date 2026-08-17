from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .database import Database

ENDPOINT = "https://partnerapi.deal-drive.com/query"
KEYCHAIN_SERVICE = "com.dxb-runway-intelligence.deal-drive"

LOGIN = """mutation Login($input: LoginInput!) { login(input: $input) { accessToken refreshToken } }"""
OFFER_IDS = """query UAEOfferIds($input: SelectMarketOffersInput!) { marketOffers(input: $input) { edges { node } } }"""
OFFER_DATA = """query UAEOfferData($input: [ID!]!) { marketOffersData(input: $input) {
  id createdAt updatedAt externalId url price priceInWorkspaceDefaultCurrency marketPrice marketPriceDiff
  deleted deletedAt publishedAt lastPriceUpdatedAt year modelYear mileage priceHistory { priceUpdatedAt price }
  source { name } catalogBrand { name } catalogModel { name } catalogModelVersion { name shortName }
  catalogGeneration { name } catalogModification { name } catalogTrim { name }
  catalogMileageUnit { code multiplierToKm } catalogRegionalSpecs { id name } marketSellerType { id name }
  marketSeller { id name official reliable } address shortAddress latitude longitude
} }"""
CATALOG_BRANDS = """query Brands($input: SelectCatalogBrandsInput!) { catalogBrands(input:$input) { edges { node { id name } } } }"""
CATALOG_MODELS = """query Models($input: SelectCatalogModelsInput!) { catalogModels(input:$input) { edges { node { id name } } } }"""
CATALOG_TRIMS = """query Trims($input: SelectCatalogTrimsInput!) { catalogTrims(input:$input) { edges { node { id name } } } }"""
CATALOG_REGIONS = """query Regions($input: SelectCatalogRegionalSpecsInput!) { catalogRegionalSpecs(input:$input) { edges { node { id name } } } }"""
AUTOFILTERS = """query Auto($input: MarketEvaluatorAutofiltersByParamsInput!) { marketEvaluatorAutofiltersByParams(input:$input) {
 commonFilter { catalogRegionalSpecs { id name } } liveMarketFilter { sellerTypes { id name } } salesHistoryFilter { sellerTypes { id name } }
} }"""
EVALUATE = """query Evaluate($input: MarketEvaluatorEvaluateByParamsInput!) { marketEvaluatorEvaluateByParams(input:$input) {
 evaluatedMarketOffers { marketOfferId active ignored explicitlyExcluded weight }
 liveMarket { totalOffersCount usefulOffersCount weightedAvgPrice weightedAvgDaysInSale }
 salesHistory { totalOffersCount usefulOffersCount weightedAvgPrice weightedAvgDaysInSale }
 accuracyState marketPrice marketPriceFrom marketPriceTo avgDaysInSale
} }"""


class DealDriveError(RuntimeError):
    pass


class KeychainCredentials:
    def save(self, email: str, password: str) -> None:
        result = subprocess.run(["/usr/bin/security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE,
                                 "-a", email, "-w", password], capture_output=True, text=True)
        if result.returncode:
            raise DealDriveError("macOS Keychain could not save the Deal Drive login.")

    def load(self, email: str) -> str | None:
        result = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
                                 "-a", email, "-w"], capture_output=True, text=True)
        return result.stdout.rstrip("\n") if result.returncode == 0 else None

    def delete(self, email: str) -> None:
        subprocess.run(["/usr/bin/security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", email],
                       capture_output=True, text=True)


Transport = Callable[[dict[str, Any], Optional[str]], dict[str, Any]]


class DealDriveClient:
    """Minimal allowlisted read-only client. Tokens exist only on this instance."""
    def __init__(self, transport: Transport | None = None):
        self._transport = transport or self._http
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    def _http(self, payload: dict[str, Any], token: str | None) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise DealDriveError(f"Deal Drive rejected the request (HTTP {error.code}).") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise DealDriveError("Deal Drive could not be reached or returned an invalid response.") from None
        if result.get("errors"):
            message = str(result["errors"][0].get("message", "Request failed"))
            raise DealDriveError(f"Deal Drive: {message}")
        return result.get("data") or {}

    def _run(self, operation: str, variables: dict[str, Any], *, authenticated: bool = True) -> dict[str, Any]:
        # No caller can provide a query: this map is the complete API permission boundary.
        query = {"login": LOGIN, "offer_ids": OFFER_IDS, "offer_data": OFFER_DATA, "brands": CATALOG_BRANDS,
                 "models": CATALOG_MODELS, "trims": CATALOG_TRIMS, "regions": CATALOG_REGIONS,
                 "autofilters": AUTOFILTERS, "evaluate": EVALUATE}[operation]
        return self._transport({"query": query, "variables": variables}, self._access_token if authenticated else None)

    def login(self, email: str, password: str) -> None:
        auth = self._run("login", {"input": {"email": email, "password": password, "clientInfo": "partner-api"}}, authenticated=False).get("login") or {}
        if not auth.get("accessToken"):
            raise DealDriveError("Deal Drive login did not return an access token. Partner API credentials may be required.")
        self._access_token = auth["accessToken"]
        self._refresh_token = auth.get("refreshToken")

    def fetch_market(self, *, country_code: str = "AE", limit: int = 5000,
                     progress: Callable[[str], None] | None = None) -> list[dict[str, Any]]:
        if not self._access_token:
            raise DealDriveError("Connect to Deal Drive before syncing.")
        data = self._run("offer_ids", {"input": {"limit": limit, "filters": {"countryCode": country_code}}})
        ids = [str(edge["node"]) for edge in ((data.get("marketOffers") or {}).get("edges") or []) if edge.get("node")]
        if progress: progress(f"Found {len(ids):,} UAE market offers. Downloading details…")
        offers: list[dict[str, Any]] = []
        for start in range(0, len(ids), 100):
            chunk = ids[start:start + 100]
            offers.extend(self._run("offer_data", {"input": chunk}).get("marketOffersData") or [])
            if progress: progress(f"Downloaded {min(start + 100, len(ids)):,} of {len(ids):,} offers…")
        return offers

    def _catalog_match(self, operation: str, root: str, search: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        request = {"first": 100, "active": True, "search": search, "countryCode": "AE", **(extra or {})}
        edges = ((self._run(operation, {"input": request}).get(root) or {}).get("edges") or [])
        nodes = [edge["node"] for edge in edges]
        exact = [node for node in nodes if str(node.get("name", "")).strip().casefold() == search.strip().casefold()]
        if not exact: raise DealDriveError(f"Deal Drive could not resolve the exact catalog value: {search}.")
        return exact[0]

    def evaluate_subject(self, *, make: str, model: str, trim: str, year: int, mileage_km: int,
                         allow_imports: bool = False, progress: Callable[[str], None] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if progress: progress(f"Resolving exact Deal Drive catalog IDs for {make} {model} {trim}…")
        brand = self._catalog_match("brands", "catalogBrands", make)
        model_node = self._catalog_match("models", "catalogModels", model, {"catalogBrandIds": [brand["id"]]})
        trim_node = self._catalog_match("trims", "catalogTrims", trim, {"catalogBrandIds": [brand["id"]], "catalogModelIds": [model_node["id"]]}) if trim.strip() else None
        gcc = None
        if not allow_imports:
            for search in ("GCC", "Gulf", "Middle East"):
                try: gcc = self._catalog_match("regions", "catalogRegionalSpecs", search); break
                except DealDriveError: pass
            if not gcc: raise DealDriveError("GCC regional specification could not be resolved; the comparison was stopped rather than widened.")
        product = {"catalogBrandId":brand["id"], "catalogModelId":model_node["id"], "catalogTrimId":trim_node["id"] if trim_node else None,
                   "year":year, "modelYear":year, "mileage":mileage_km, "catalogMileageUnitCode":"km", "countryCode":"AE"}
        product = {key:value for key,value in product.items() if value is not None}
        auto = self._run("autofilters", {"input":{"evaluationProductParams":product,"countryCode":"AE"}}).get("marketEvaluatorAutofiltersByParams") or {}
        seller_types = [item for item in ((auto.get("liveMarketFilter") or {}).get("sellerTypes") or [])
                        if not any(word in str(item.get("name","")).casefold() for word in ("private","individual"))]
        if not seller_types: raise DealDriveError("No commercial/dealer seller type was returned; comparison stopped safely.")
        common = {"catalogBrandId":brand["id"],"catalogModelId":model_node["id"],"yearFrom":year,"yearTo":year+1,"currencyCode":"AED"}
        if trim_node: common["catalogTrimIds"]=[trim_node["id"]]
        if gcc: common["catalogRegionalSpecIds"]=[gcc["id"]]
        seller_ids=[item["id"] for item in seller_types]
        request={"evaluationProductParams":product,"commonFilter":common,"liveMarketFilter":{"sellerTypeIds":seller_ids,"maxOffersInSelection":500},
                 "salesHistoryFilter":{"sellerTypeIds":seller_ids,"depthDays":730,"maxOffersInSelection":1000},
                 "countryCode":"AE","evaluationCurrencyCode":"AED","userCurrencyCode":"AED","orderBy":"weight","orderDirection":"desc"}
        if progress: progress("Deal Drive is evaluating the exact year, trim, GCC and dealer cohort…")
        evaluation=self._run("evaluate", {"input":request}).get("marketEvaluatorEvaluateByParams") or {}
        evaluated=[row for row in evaluation.get("evaluatedMarketOffers") or [] if row.get("marketOfferId") and not row.get("ignored")]
        active={str(row["marketOfferId"]):bool(row.get("active")) for row in evaluated}
        weights={str(row["marketOfferId"]):float(row.get("weight") or 1) for row in evaluated}
        ids=list(active)
        if progress: progress(f"Fetching {len(ids):,} evaluated comparables for local mileage, city and duplicate checks…")
        offers=[]
        for start in range(0,len(ids),100): offers.extend(self._run("offer_data", {"input":ids[start:start+100]}).get("marketOffersData") or [])
        for offer in offers:
            offer["_active_market"]=active.get(str(offer.get("id")),not bool(offer.get("deleted")))
            offer["_comparison_weight"]=weights.get(str(offer.get("id")),1)
        return offers, {"brand":brand,"model":model_node,"trim":trim_node,"gcc":gcc,"seller_types":seller_types,"evaluation":evaluation}


def _name(value: Any) -> str:
    return str((value or {}).get("name") or "") if isinstance(value, dict) else ""


def save_market_snapshot(db: Database, offers: list[dict[str, Any]], country_code: str, requested_limit: int) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with db.connect() as connection:
        cursor = connection.execute("INSERT INTO deal_drive_sync_runs(started_at,status,country_code,requested_limit) VALUES (?,?,?,?)",
                                    (now, "running", country_code, requested_limit))
        run_id = int(cursor.lastrowid)
        for offer in offers:
            unit = offer.get("catalogMileageUnit") or {}; multiplier = float(unit.get("multiplierToKm") or 1)
            mileage = float(offer.get("mileage") or 0) * multiplier if offer.get("mileage") is not None else None
            version = offer.get("catalogModelVersion") or {}
            seller = offer.get("marketSeller") or {}; address = str(offer.get("shortAddress") or offer.get("address") or "")
            exclusion = comparison_exclusion(offer, allow_imports=db.get_setting("deal_drive_allow_imports", "0") == "1")
            connection.execute("""INSERT OR IGNORE INTO deal_drive_market_offers(
                sync_run_id,offer_id,source_name,external_id,listing_url,price_aed,market_price_aed,market_price_diff,
                brand,model,model_version,generation,modification,trim,model_year,mileage_km,regional_spec,seller_type,
                published_at,source_updated_at,deleted,price_history_json,raw_json,address,latitude,longitude,seller_id,seller_name,
                active_market,exclusion_reason,comparison_weight)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                run_id, str(offer.get("id") or offer.get("externalId") or ""), _name(offer.get("source")),
                str(offer.get("externalId") or ""), str(offer.get("url") or ""), offer.get("priceInWorkspaceDefaultCurrency") or offer.get("price"),
                offer.get("marketPrice"), offer.get("marketPriceDiff"), _name(offer.get("catalogBrand")), _name(offer.get("catalogModel")),
                str(version.get("shortName") or version.get("name") or ""), _name(offer.get("catalogGeneration")),
                _name(offer.get("catalogModification")), _name(offer.get("catalogTrim")), offer.get("modelYear") or offer.get("year"),
                mileage, _name(offer.get("catalogRegionalSpecs")), _name(offer.get("marketSellerType")), offer.get("publishedAt"),
                offer.get("updatedAt") or offer.get("lastPriceUpdatedAt"), int(bool(offer.get("deleted"))),
                json.dumps(offer.get("priceHistory") or []), json.dumps(offer, default=str), address, offer.get("latitude"), offer.get("longitude"),
                str(seller.get("id") or ""), str(seller.get("name") or ""), int(offer.get("_active_market", not bool(offer.get("deleted")))), exclusion,
                offer.get("_comparison_weight")))
        _mark_duplicates(connection, run_id)
        connection.execute("UPDATE deal_drive_sync_runs SET completed_at=?,status='success',offer_count=?,detail=? WHERE id=?",
                           (now, len(offers), f"Retained {len(offers):,} UAE market offers", run_id))
    return run_id


def comparison_exclusion(offer: dict[str, Any], *, allow_imports: bool = False) -> str:
    seller_type = _name(offer.get("marketSellerType")).casefold()
    if not seller_type or any(term in seller_type for term in ("private", "individual")): return "private or unknown seller"
    address = f"{offer.get('address','')} {offer.get('shortAddress','')}".casefold()
    if "sharjah" in address: return "Sharjah excluded"
    if "ajman" in address: return "Ajman excluded"
    regional = _name(offer.get("catalogRegionalSpecs")).casefold()
    if not allow_imports and not any(term in regional for term in ("gcc", "gulf", "middle east")): return "non-GCC or unknown specification"
    return ""


def _mark_duplicates(connection: Any, run_id: int) -> None:
    rows = connection.execute("SELECT id,offer_id,seller_id,brand,model,trim,model_year,mileage_km,price_aed FROM deal_drive_market_offers WHERE sync_run_id=? AND exclusion_reason='' ORDER BY id", (run_id,)).fetchall()
    seen: dict[tuple[Any, ...], str] = {}
    for row in rows:
        # Same dealer + near-identical vehicle/mileage/price is treated as a repost, not a second comparable.
        key = (row["seller_id"], str(row["brand"]).casefold(), str(row["model"]).casefold(), str(row["trim"]).casefold(), row["model_year"],
               round(float(row["mileage_km"] or 0) / 500), round(float(row["price_aed"] or 0) / 1000))
        if row["seller_id"] and key in seen:
            connection.execute("UPDATE deal_drive_market_offers SET duplicate_of_offer_id=? WHERE id=?", (seen[key], row["id"]))
        else: seen[key] = row["offer_id"]


def comparison_summary(db: Database, make: str, model: str, trim: str, year: int, mileage_km: float) -> dict[str, Any]:
    latest = sync_status(db)["latest"]
    if not latest or latest["status"] != "success": return {"status": "not_synced"}
    tolerance = max(15000.0, mileage_km * 0.25)
    rows = [dict(row) for row in db.query("""SELECT * FROM deal_drive_market_offers WHERE sync_run_id=? AND lower(brand)=lower(?)
        AND lower(model)=lower(?) AND model_year BETWEEN ? AND ? AND exclusion_reason='' AND duplicate_of_offer_id IS NULL
        AND mileage_km BETWEEN ? AND ?""", (latest["id"], make, model, year, year + 1, max(0, mileage_km-tolerance), mileage_km+tolerance))]
    exact = [row for row in rows if str(row["trim"]).casefold() == trim.strip().casefold()] if trim.strip() else rows
    chosen = exact if exact else rows
    live = [row for row in chosen if row["active_market"]]
    history = [row for row in chosen if not row["active_market"]]
    def stats(group: list[dict[str, Any]]) -> dict[str, Any]:
        prices = [float(row["price_aed"]) for row in group if row.get("price_aed")]
        weighted = sorted((float(row["price_aed"]), max(0.0,float(row.get("comparison_weight") or 1))) for row in group if row.get("price_aed"))
        weighted_median = None
        if weighted:
            halfway=sum(weight for _,weight in weighted)/2; running=0.0
            for price,weight in weighted:
                running += weight
                if running >= halfway: weighted_median=price; break
        return {"samples": len(prices), "median_price_aed": statistics.median(prices) if prices else None,
                "weighted_median_price_aed": weighted_median,
                "average_price_aed": statistics.mean(prices) if prices else None,
                "minimum_price_aed": min(prices) if prices else None, "maximum_price_aed": max(prices) if prices else None}
    return {"status":"ready", "filter_receipt": {"vehicle":f"{year}–{year+1} {make} {model}", "trim": trim or "all trims",
            "trim_rule":"exact trim used" if exact else "no exact trim found; related trims shown separately", "mileage_km":mileage_km,
            "mileage_tolerance_km":tolerance, "seller":"commercial/dealers only", "regional_spec":"GCC only" if db.get_setting("deal_drive_allow_imports","0") != "1" else "imports explicitly allowed",
            "excluded_locations":["Sharjah","Ajman"], "duplicates":"collapsed by dealer + vehicle + near mileage/price"},
            "exact_trim_samples":len(exact), "related_trim_samples":max(0,len(rows)-len(exact)), "live_market_asking":stats(live),
            "historical_sold_or_removed":stats(history), "pricing_basis":"Median is primary; average is diagnostic only."}


def sync_status(db: Database) -> dict[str, Any]:
    rows = db.query("SELECT * FROM deal_drive_sync_runs ORDER BY id DESC LIMIT 1")
    snapshots = int(db.query("SELECT COUNT(*) n FROM deal_drive_sync_runs WHERE status='success'")[0]["n"])
    retained = int(db.query("SELECT COUNT(*) n FROM deal_drive_market_offers")[0]["n"])
    return {"latest": dict(rows[0]) if rows else None, "snapshots": snapshots, "retained_offers": retained}


def market_evidence(db: Database, limit: int = 200) -> dict[str, Any]:
    status = sync_status(db); latest = status["latest"]
    if not latest or latest["status"] != "success": return {"status": "not_synced", "groups": []}
    rows = db.query("""SELECT brand,model,trim,model_year,COUNT(*) samples,AVG(price_aed) average_asking_aed,
        MIN(price_aed) minimum_asking_aed,MAX(price_aed) maximum_asking_aed,AVG(mileage_km) average_mileage_km
        FROM deal_drive_market_offers WHERE sync_run_id=? AND deleted=0 AND exclusion_reason='' AND duplicate_of_offer_id IS NULL AND brand<>'' AND model<>''
        GROUP BY brand,model,trim,model_year ORDER BY samples DESC LIMIT ?""", (latest["id"], limit))
    return {"status": "ready", "captured_at": latest["completed_at"], "offer_count": latest["offer_count"],
            "retained_snapshots": status["snapshots"], "note": "Deal Drive listings are asking-price evidence, not achieved sale prices.",
            "groups": [dict(row) for row in rows]}
