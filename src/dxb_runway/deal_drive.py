from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
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
  catalogMileageUnit { code multiplierToKm } catalogRegionalSpecs { name } marketSellerType { name }
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
        query = {"login": LOGIN, "offer_ids": OFFER_IDS, "offer_data": OFFER_DATA}[operation]
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
            connection.execute("""INSERT OR IGNORE INTO deal_drive_market_offers(
                sync_run_id,offer_id,source_name,external_id,listing_url,price_aed,market_price_aed,market_price_diff,
                brand,model,model_version,generation,modification,trim,model_year,mileage_km,regional_spec,seller_type,
                published_at,source_updated_at,deleted,price_history_json,raw_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                run_id, str(offer.get("id") or offer.get("externalId") or ""), _name(offer.get("source")),
                str(offer.get("externalId") or ""), str(offer.get("url") or ""), offer.get("priceInWorkspaceDefaultCurrency") or offer.get("price"),
                offer.get("marketPrice"), offer.get("marketPriceDiff"), _name(offer.get("catalogBrand")), _name(offer.get("catalogModel")),
                str(version.get("shortName") or version.get("name") or ""), _name(offer.get("catalogGeneration")),
                _name(offer.get("catalogModification")), _name(offer.get("catalogTrim")), offer.get("modelYear") or offer.get("year"),
                mileage, _name(offer.get("catalogRegionalSpecs")), _name(offer.get("marketSellerType")), offer.get("publishedAt"),
                offer.get("updatedAt") or offer.get("lastPriceUpdatedAt"), int(bool(offer.get("deleted"))),
                json.dumps(offer.get("priceHistory") or []), json.dumps(offer, default=str)))
        connection.execute("UPDATE deal_drive_sync_runs SET completed_at=?,status='success',offer_count=?,detail=? WHERE id=?",
                           (now, len(offers), f"Retained {len(offers):,} UAE market offers", run_id))
    return run_id


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
        FROM deal_drive_market_offers WHERE sync_run_id=? AND deleted=0 AND brand<>'' AND model<>''
        GROUP BY brand,model,trim,model_year ORDER BY samples DESC LIMIT ?""", (latest["id"], limit))
    return {"status": "ready", "captured_at": latest["completed_at"], "offer_count": latest["offer_count"],
            "retained_snapshots": status["snapshots"], "note": "Deal Drive listings are asking-price evidence, not achieved sale prices.",
            "groups": [dict(row) for row in rows]}
