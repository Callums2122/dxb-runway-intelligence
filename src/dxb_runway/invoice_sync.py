from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from .database import Database


class InvoiceSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class InvoiceSyncResult:
    received: int = 0
    sold: int = 0
    review: int = 0
    ignored: int = 0


def _normalise(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).split())


def _tokens(value: str) -> set[str]:
    ignored = {"gcc", "uae", "car", "cars", "the"}
    return {part for part in _normalise(value).split() if part not in ignored}


class InvoiceSyncClient:
    """GET-only reader for the private Apps Script invoice bridge."""

    def __init__(self, endpoint: str, access_key: str, fetcher: Callable[[urllib.request.Request], bytes] | None = None):
        self.endpoint = endpoint.strip()
        self.access_key = access_key.strip()
        self._fetcher = fetcher or self._urlopen

    @staticmethod
    def _urlopen(request: urllib.request.Request) -> bytes:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()

    def fetch_invoices(self) -> list[dict[str, Any]]:
        if not self.endpoint.startswith("https://"):
            raise InvoiceSyncError("Invoice queue endpoint must use HTTPS.")
        if not self.access_key:
            raise InvoiceSyncError("Invoice reader access key is missing.")
        request = urllib.request.Request(self.endpoint, headers={"Accept": "application/json", "x-dxb-sync-key": self.access_key}, method="GET")
        if request.get_method() != "GET":
            raise InvoiceSyncError("Security block: invoice sync is read-only and only permits GET.")
        try:
            payload = json.loads(self._fetcher(request))
        except urllib.error.HTTPError as error:
            raise InvoiceSyncError(f"Invoice reader returned HTTP {error.code}.") from None
        except (urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError):
            raise InvoiceSyncError("Invoice reader is temporarily unavailable.") from None
        if not isinstance(payload, dict) or payload.get("status") != "ok" or not isinstance(payload.get("invoices"), list):
            raise InvoiceSyncError("Invoice reader returned an invalid response.")
        return [row for row in payload["invoices"] if isinstance(row, dict)]


class InvoiceSyncService:
    def __init__(self, db: Database, client: InvoiceSyncClient):
        self.db = db
        self.client = client

    def sync(self) -> InvoiceSyncResult:
        invoices = self.client.fetch_invoices()
        result = {"received": len(invoices), "sold": 0, "review": 0, "ignored": 0}
        for invoice in invoices:
            message_id = str(invoice.get("messageId") or "").strip()
            if not message_id or self.db.query("SELECT id FROM invoice_sync_events WHERE source_message_id=?", (message_id,)):
                result["ignored"] += 1
                continue
            outcome, vehicle_id, detail = self._process(invoice)
            self.db.execute(
                "INSERT INTO invoice_sync_events(source_message_id,source_created_at,stock_number,vehicle_text,model_year,sold_price_aed,matched_vehicle_id,outcome,detail) VALUES (?,?,?,?,?,?,?,?,?)",
                (message_id, str(invoice.get("createTime") or ""), str(invoice.get("stockNumber") or ""), str(invoice.get("vehicle") or ""), invoice.get("year"), invoice.get("soldPriceAed"), vehicle_id, outcome, detail),
            )
            result[outcome if outcome in result else "review"] += 1
        self.db.set_setting("invoice_sync_last_at", datetime.now().astimezone().isoformat(timespec="seconds"))
        self.db.set_setting("invoice_sync_last_result", json.dumps(result, separators=(",", ":")))
        return InvoiceSyncResult(**result)

    def _process(self, invoice: dict[str, Any]) -> tuple[str, int | None, str]:
        price = float(invoice.get("soldPriceAed") or 0)
        vehicle_text = str(invoice.get("vehicle") or "").strip()
        stock_number = str(invoice.get("stockNumber") or "").strip()
        year = int(invoice.get("year") or 0)
        if price <= 0 or not vehicle_text:
            return "review", None, "Missing vehicle name or valid sold price."
        stock = self.db.query("SELECT * FROM vehicles WHERE status='stock' ORDER BY id")
        exact_number = [row for row in stock if stock_number and str(row["external_stock_number"] or "").strip() == stock_number]
        if len(exact_number) == 1:
            return self._sell(exact_number[0], price, invoice, "Matched by exact stock number.")
        if len(exact_number) > 1:
            return "review", None, "Duplicate stock number in Runway; no vehicle changed."

        wanted = _tokens(vehicle_text)
        candidates = []
        for row in stock:
            row_year = int(row["market_model_year"] or 0)
            if year and row_year and row_year != year:
                continue
            current = _tokens(str(row["vehicle_name"] or ""))
            if wanted and (wanted <= current or current <= wanted or len(wanted & current) >= min(2, len(wanted))):
                candidates.append(row)
        if len(candidates) == 1:
            return self._sell(candidates[0], price, invoice, "Unique vehicle/year match.")
        if not candidates:
            return "review", None, "No matching unsold vehicle; no vehicle changed."
        return "review", None, f"{len(candidates)} possible matches; no vehicle changed."

    def _sell(self, vehicle: Any, price: float, invoice: dict[str, Any], detail: str) -> tuple[str, int, str]:
        purchase_type = str(vehicle["purchase_type"] or "cash")
        if purchase_type == "consignment":
            return "review", int(vehicle["id"]), "Consignment sale requires final owner payout; no vehicle changed."
        sold_date = str(invoice.get("createTime") or date.today().isoformat())[:10]
        try:
            date.fromisoformat(sold_date)
        except ValueError:
            sold_date = date.today().isoformat()
        self.db.sell_vehicle(int(vehicle["id"]), sold_price_aed=price, sold_date=sold_date)
        stock_number = str(invoice.get("stockNumber") or "").strip()
        if stock_number:
            self.db.execute("UPDATE vehicles SET external_stock_number=? WHERE id=?", (stock_number, int(vehicle["id"])))
        return "sold", int(vehicle["id"]), detail


def configured_invoice_service(db: Database) -> InvoiceSyncService | None:
    endpoint = db.get_setting("invoice_sync_endpoint").strip()
    access_key = db.get_setting("invoice_sync_access_key").strip()
    if not endpoint or not access_key:
        return None
    return InvoiceSyncService(db, InvoiceSyncClient(endpoint, access_key))
