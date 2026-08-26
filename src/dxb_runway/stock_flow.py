from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from .database import Database


class StockFlowError(RuntimeError):
    pass


@dataclass(frozen=True)
class StockFlowResult:
    received: int = 0
    linked: int = 0
    updated: int = 0
    review: int = 0
    ignored: int = 0


def _normalise(value: str) -> str:
    value = str(value or "").casefold().replace("mercedes-benz", "mercedes").replace("silverado hd", "silverado")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def _tokens(value: str) -> set[str]:
    ignored = {"gcc", "uae", "car", "cars", "hd", "class", "series", "2500", "3500"}
    return {part for part in _normalise(value).split() if part not in ignored and not (len(part) == 4 and part.isdigit())}


def classify_event(subject: str, status: str, text: str = "") -> tuple[str, str]:
    haystack = f" {_normalise(' '.join((subject, status, text)))} "
    rules = [
        ("price_change", ("price reduction", "price change", "price reduced"), "PRICE CHANGE"),
        ("repair", ("pull out repair", "repair"), "PULL OUT - REPAIR"),
        ("photoshoot", ("photoshoot", "photo shoot", "photography"), "PHOTOSHOOT"),
        ("booked", ("booked", "subject to booking"), "BOOKED"),
        ("sold", (" sold ",), "SOLD"),
        ("prep", (" prep ", "preparation"), "PREP"),
        ("stock", ("moved to stock", "in stock", " stock "), "STOCK"),
    ]
    for event_type, phrases, canonical in rules:
        if any(phrase in haystack for phrase in phrases): return event_type, canonical
    return "status", str(status or "UPDATE").strip().upper()


class StockFlowClient:
    """GET-only reader for the private Stock Flow queue."""
    def __init__(self, endpoint: str, access_key: str, fetcher: Callable[[urllib.request.Request], bytes] | None = None):
        self.endpoint=endpoint.strip(); self.access_key=access_key.strip(); self._fetcher=fetcher or self._urlopen
    @staticmethod
    def _urlopen(request: urllib.request.Request)->bytes:
        with urllib.request.urlopen(request,timeout=30) as response:return response.read()
    def fetch_events(self)->list[dict[str,Any]]:
        if not self.endpoint.startswith("https://"):raise StockFlowError("Stock Flow endpoint must use HTTPS.")
        if not self.access_key:raise StockFlowError("Stock Flow access key is missing.")
        request=urllib.request.Request(self.endpoint,headers={"Accept":"application/json","x-dxb-sync-key":self.access_key},method="GET")
        if request.get_method()!="GET":raise StockFlowError("Security block: Stock Flow only permits GET.")
        try:payload=json.loads(self._fetcher(request))
        except urllib.error.HTTPError as error:raise StockFlowError(f"Stock Flow returned HTTP {error.code}.") from None
        except (urllib.error.URLError,json.JSONDecodeError,UnicodeDecodeError):raise StockFlowError("Stock Flow is temporarily unavailable.") from None
        rows=payload.get("stockEvents") if isinstance(payload,dict) else None
        if not isinstance(payload,dict) or payload.get("status")!="ok" or not isinstance(rows,list):raise StockFlowError("Stock Flow returned an invalid response.")
        return [row for row in rows if isinstance(row,dict)]


class StockFlowService:
    def __init__(self,db:Database,client:StockFlowClient):self.db=db;self.client=client
    def sync(self)->StockFlowResult:
        events=self.client.fetch_events(); result={"received":len(events),"linked":0,"updated":0,"review":0,"ignored":0}
        for event in sorted(events,key=lambda row:str(row.get("createTime") or "")):
            message_id=str(event.get("messageId") or "").strip()
            if not message_id or self.db.query("SELECT id FROM stock_flow_events WHERE source_message_id=?",(message_id,)):
                result["ignored"]+=1;continue
            outcome,vehicle_id,detail,parsed=self._process(event)
            self.db.execute("""INSERT INTO stock_flow_events(source_message_id,source_created_at,subject,workflow_id,stock_number,vehicle_text,model_year,event_type,stock_status,live_price_aed,matched_vehicle_id,outcome,detail,raw_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(message_id,str(event.get("createTime") or ""),str(event.get("subject") or ""),parsed["workflow_id"],parsed["stock_number"],parsed["vehicle"],parsed["year"],parsed["event_type"],parsed["status"],parsed["price"],vehicle_id,outcome,detail,json.dumps(event,separators=(",",":"),default=str)))
            result[outcome if outcome in result else "review"]+=1
        self.db.set_setting("stock_flow_sync_last_at",datetime.now().astimezone().isoformat(timespec="seconds"));self.db.set_setting("stock_flow_sync_last_result",json.dumps(result,separators=(",",":")))
        return StockFlowResult(**result)

    def _process(self,event:dict[str,Any])->tuple[str,int|None,str,dict[str,Any]]:
        subject=str(event.get("subject") or "");body=str(event.get("text") or event.get("body") or "")
        workflow=str(event.get("workflowId") or "").strip().upper()
        if not workflow:
            match=re.search(r"\bSTFL[-\s]?(\d+)\b",subject+" "+body,re.I);workflow=f"STFL-{match.group(1)}" if match else ""
        stock_number=str(event.get("stockNumber") or "").strip();vehicle=str(event.get("vehicle") or "").strip();year=int(event.get("year") or 0)
        status=str(event.get("status") or "").strip();price=float(event.get("priceAed") or event.get("newPriceAed") or 0) or None
        event_type,canonical=classify_event(subject,status,body)
        parsed={"workflow_id":workflow,"stock_number":stock_number,"vehicle":vehicle,"year":year or None,"event_type":event_type,"status":canonical,"price":price}
        if not stock_number or not vehicle:return "review",None,"Missing stock number or vehicle description; no stock changed.",parsed
        stock=self.db.query("SELECT * FROM vehicles WHERE status='stock' ORDER BY id")
        exact=[row for row in stock if str(row["external_stock_number"] or "").strip()==stock_number]
        if not exact and workflow:exact=[row for row in stock if str(row["external_workflow_id"] or "").strip().upper()==workflow]
        candidates=exact
        if not candidates:
            wanted=_tokens(vehicle);candidates=[]
            for row in stock:
                row_year=int(row["market_model_year"] or 0)
                if year and row_year and year!=row_year:continue
                current=_tokens(row["vehicle_name"]);overlap=len(wanted&current)
                if wanted and current and (wanted<=current or current<=wanted or overlap>=2):candidates.append(row)
        if len(candidates)!=1:
            detail="No matching current-stock vehicle" if not candidates else f"{len(candidates)} possible stock matches"
            return "review",None,detail+"; no stock changed.",parsed
        row=candidates[0];vehicle_id=int(row["id"]);was_linked=bool(str(row["external_stock_number"] or "").strip())
        live_price=price if event_type=="price_change" and price else row["external_live_price_aed"]
        self.db.execute("""UPDATE vehicles SET external_stock_number=?,external_workflow_id=?,external_stock_status=?,external_live_price_aed=?,external_status_updated_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (stock_number,workflow,canonical,live_price,str(event.get("createTime") or datetime.now().astimezone().isoformat(timespec="seconds")),vehicle_id))
        outcome="updated" if was_linked else "linked";detail=("Matched by existing identifier." if exact else "Unique make/model/year match.")+f" {stock_number} → {row['vehicle_name']} · {canonical}."
        return outcome,vehicle_id,detail,parsed


def configured_stock_flow_service(db:Database)->StockFlowService|None:
    endpoint=db.get_setting("stock_flow_sync_endpoint").strip()
    if not endpoint:
        endpoint=db.get_setting("invoice_sync_endpoint").strip().replace("/v1/invoices","/v1/stock-flow")
    key=db.get_setting("stock_flow_sync_access_key").strip() or db.get_setting("invoice_sync_access_key").strip()
    return StockFlowService(db,StockFlowClient(endpoint,key)) if endpoint and key else None
