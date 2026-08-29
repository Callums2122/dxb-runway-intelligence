#!/usr/bin/env python3
"""DXB Runway's isolated, read-only invoice event queue.

The poller only issues GET requests to the configured Apps Script reader. It
never calls Google Chat directly and has no send/edit/delete capability.
"""
from __future__ import annotations

import hmac
import json
import os
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DB_PATH = Path(os.environ.get("RUNWAY_INVOICE_DB", "/var/lib/dxb-runway-invoices/events.db"))
SOURCE_URL = os.environ.get("RUNWAY_INVOICE_SOURCE_URL", "").strip()
SOURCE_KEY = os.environ.get("RUNWAY_INVOICE_SOURCE_KEY", "").strip()
STOCK_FLOW_SOURCE_URL = os.environ.get("RUNWAY_STOCK_FLOW_SOURCE_URL", "").strip()
STOCK_FLOW_SOURCE_KEY = os.environ.get("RUNWAY_STOCK_FLOW_SOURCE_KEY", "").strip()
MOBILE_STOCK_FLOW_URL = os.environ.get("RUNWAY_MOBILE_STOCK_FLOW_URL", "https://dxb-runway-mobile.randomsteen1.chatgpt.site/api/stock-flow").strip()
MOBILE_SYNC_KEY = os.environ.get("RUNWAY_MOBILE_SYNC_KEY", "").strip()
MOBILE_SITE_TOKEN = os.environ.get("RUNWAY_MOBILE_SITE_TOKEN", "").strip()
QUEUE_KEY = os.environ.get("RUNWAY_INVOICE_QUEUE_KEY", "").strip()
HOST = os.environ.get("RUNWAY_INVOICE_HOST", "127.0.0.1")
PORT = int(os.environ.get("RUNWAY_INVOICE_PORT", "8787"))


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""CREATE TABLE IF NOT EXISTS events(
      message_id TEXT PRIMARY KEY, create_time TEXT NOT NULL DEFAULT '', stock_number TEXT NOT NULL DEFAULT '',
      vehicle TEXT NOT NULL DEFAULT '', model_year INTEGER, sold_price_aed REAL NOT NULL,
      first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, payload_json TEXT NOT NULL
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS poll_runs(
      id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS stock_flow_events(
      message_id TEXT PRIMARY KEY, create_time TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '',
      workflow_id TEXT NOT NULL DEFAULT '', stock_number TEXT NOT NULL DEFAULT '', vehicle TEXT NOT NULL DEFAULT '',
      model_year INTEGER, event_type TEXT NOT NULL DEFAULT '', stock_status TEXT NOT NULL DEFAULT '', live_price_aed REAL,
      first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, forwarded_at TEXT, payload_json TEXT NOT NULL
    )""")
    connection.commit()
    return connection


def source_invoices() -> list[dict]:
    if not SOURCE_URL.startswith("https://script.google.com/") or not SOURCE_KEY:
        raise RuntimeError("Apps Script read-only source is not configured")
    sep = "&" if "?" in SOURCE_URL else "?"
    request = urllib.request.Request(SOURCE_URL + sep + urllib.parse.urlencode({"key": SOURCE_KEY}), headers={"accept": "application/json"}, method="GET")
    if request.get_method() != "GET": raise RuntimeError("Security block: source method must be GET")
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.loads(response.read())
    if payload.get("status") != "ok" or not isinstance(payload.get("invoices"), list):
        raise RuntimeError("Invalid source response")
    return payload["invoices"]


def source_stock_flow() -> list[dict]:
    if not STOCK_FLOW_SOURCE_URL.startswith("https://script.google.com/") or not STOCK_FLOW_SOURCE_KEY:
        raise RuntimeError("Apps Script Stock Flow source is not configured")
    sep = "&" if "?" in STOCK_FLOW_SOURCE_URL else "?"
    request = urllib.request.Request(STOCK_FLOW_SOURCE_URL + sep + urllib.parse.urlencode({"key": STOCK_FLOW_SOURCE_KEY}), headers={"accept": "application/json"}, method="GET")
    if request.get_method() != "GET": raise RuntimeError("Security block: Stock Flow source method must be GET")
    with urllib.request.urlopen(request, timeout=60) as response: payload = json.loads(response.read())
    if payload.get("status") != "ok" or not isinstance(payload.get("stockEvents"), list): raise RuntimeError("Invalid Stock Flow response")
    return payload["stockEvents"]


def classify_stock_event(row: dict) -> str:
    value = " ".join(str(row.get(key) or "") for key in ("subject", "status", "text")).lower()
    for event_type, phrases in (("price_change",("price reduction","price change")),("repair",("pull out - repair","repair")),("photoshoot",("photoshoot","photo shoot")),("registered",("registered","moved to registered")),("booked",("booked",)),("sold",("sold",)),("prep",("prep",)),("stock",("moved to stock","in stock"))):
        if any(phrase in value for phrase in phrases): return event_type
    return "status"


def forward_stock_events(rows: list[dict]) -> None:
    if not rows or not MOBILE_SYNC_KEY or not MOBILE_SITE_TOKEN: return
    request = urllib.request.Request(MOBILE_STOCK_FLOW_URL, data=json.dumps({"stockEvents": rows}, separators=(",", ":")).encode(), headers={"content-type":"application/json","x-dxb-sync-key":MOBILE_SYNC_KEY,"oai-sites-authorization":f"Bearer {MOBILE_SITE_TOKEN}"}, method="POST")
    with urllib.request.urlopen(request, timeout=45) as response:
        payload=json.loads(response.read())
    if not payload.get("ok"): raise RuntimeError("Mobile Stock Flow update was rejected")


def poll_stock_flow() -> dict:
    rows=source_stock_flow();added_rows=[]
    with connect() as db:
        for row in rows:
            message_id=str(row.get("messageId") or "").strip();stock=str(row.get("stockNumber") or "").strip();vehicle=str(row.get("vehicle") or "").strip()
            if not message_id or not stock or not vehicle: continue
            event_type=classify_stock_event(row);row=dict(row);row["eventType"]=event_type
            cursor=db.execute("""INSERT OR IGNORE INTO stock_flow_events(message_id,create_time,subject,workflow_id,stock_number,vehicle,model_year,event_type,stock_status,live_price_aed,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
              (message_id,str(row.get("createTime") or ""),str(row.get("subject") or ""),str(row.get("workflowId") or ""),stock,vehicle,row.get("year"),event_type,str(row.get("status") or ""),row.get("priceAed"),json.dumps(row,separators=(",",":"))))
            if cursor.rowcount: added_rows.append(row)
        db.commit()
    forward_stock_events(added_rows)
    if added_rows:
        with connect() as db:
            now=datetime.now(timezone.utc).isoformat(timespec="seconds")
            db.executemany("UPDATE stock_flow_events SET forwarded_at=? WHERE message_id=?",[(now,str(row["messageId"])) for row in added_rows]);db.commit()
    return {"received":len(rows),"added":len(added_rows)}


def poll() -> dict:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as db:
        run_id = db.execute("INSERT INTO poll_runs(started_at,status) VALUES (?,'running')", (started,)).lastrowid
        try:
            invoices = source_invoices(); added = 0
            for row in invoices:
                message_id = str(row.get("messageId") or "").strip(); price = float(row.get("soldPriceAed") or 0)
                if not message_id or price <= 0: continue
                cursor = db.execute("INSERT OR IGNORE INTO events(message_id,create_time,stock_number,vehicle,model_year,sold_price_aed,payload_json) VALUES (?,?,?,?,?,?,?)",
                    (message_id, str(row.get("createTime") or ""), str(row.get("stockNumber") or ""), str(row.get("vehicle") or ""), row.get("year"), price, json.dumps(row, separators=(",", ":"))))
                added += max(0, cursor.rowcount)
            db.execute("UPDATE poll_runs SET finished_at=?,status='ok',detail=? WHERE id=?", (datetime.now(timezone.utc).isoformat(timespec="seconds"), f"received={len(invoices)} added={added}", run_id)); db.commit()
            return {"received": len(invoices), "added": added}
        except Exception as error:
            db.execute("UPDATE poll_runs SET finished_at=?,status='error',detail=? WHERE id=?", (datetime.now(timezone.utc).isoformat(timespec="seconds"), str(error)[:500], run_id)); db.commit(); raise


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/health": return self.reply(200, {"ok": True})
        route=self.path.split("?",1)[0]
        if route not in {"/v1/invoices","/v1/stock-flow"}: return self.reply(404, {"status": "error", "error": "not found"})
        supplied = self.headers.get("x-dxb-sync-key", "")
        if not QUEUE_KEY or not hmac.compare_digest(supplied, QUEUE_KEY): return self.reply(401, {"status": "error", "error": "unauthorised"})
        with connect() as db:
            if route=="/v1/stock-flow":
                rows=[json.loads(row["payload_json"]) for row in db.execute("SELECT payload_json FROM stock_flow_events ORDER BY create_time DESC,message_id DESC LIMIT 2000")]
                return self.reply(200,{"status":"ok","stockEvents":rows})
            rows = [json.loads(row["payload_json"]) for row in db.execute("SELECT payload_json FROM events ORDER BY create_time DESC,message_id DESC LIMIT 1000")]
            last = db.execute("SELECT * FROM poll_runs ORDER BY id DESC LIMIT 1").fetchone()
        self.reply(200, {"status": "ok", "invoices": rows, "lastPoll": dict(last) if last else None})

    def do_POST(self) -> None: self.reply(405, {"status": "error", "error": "read only"})
    do_PUT = do_POST; do_PATCH = do_POST; do_DELETE = do_POST
    def log_message(self, *_args) -> None: pass
    def reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode(); self.send_response(status); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)


if __name__ == "__main__":
    if not QUEUE_KEY: raise SystemExit("RUNWAY_INVOICE_QUEUE_KEY is required")
    if "--poll-stock-flow" in os.sys.argv: print(json.dumps(poll_stock_flow()));raise SystemExit(0)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
