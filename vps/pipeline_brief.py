#!/usr/bin/env python3
"""VPS-backed, read-only Pipeline cache and DXB Runway daily brief publisher.

Google is accessed exclusively through the approved Apps Script GET endpoint.
The only POSTs are to DXB Runway's own authenticated mobile endpoints.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import tempfile
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DB_PATH = Path(os.environ.get("RUNWAY_PIPELINE_DB", "/var/lib/dxb-runway-pipeline/pipeline.db"))
AGENT_SNAPSHOT_PATH = Path(os.environ.get("RUNWAY_AGENT_SNAPSHOT", "/var/lib/dxb-runway-agent/appointments.json"))
SOURCE_URL = os.environ.get("RUNWAY_PIPELINE_SOURCE_URL", "").strip()
SOURCE_KEY = os.environ.get("RUNWAY_PIPELINE_SOURCE_KEY", "").strip()
MOBILE_BRIEF_URL = os.environ.get("RUNWAY_MOBILE_BRIEF_URL", "https://dxb-runway-mobile.randomsteen1.chatgpt.site/api/brief").strip()
MOBILE_NOTIFICATIONS_URL = os.environ.get("RUNWAY_MOBILE_NOTIFICATIONS_URL", "https://dxb-runway-mobile.randomsteen1.chatgpt.site/api/notifications").strip()
SYNC_KEY = os.environ.get("RUNWAY_MOBILE_SYNC_KEY", "").strip()
SITES_AUTH_TOKEN = os.environ.get("RUNWAY_MOBILE_SITES_TOKEN", "").strip()
VAPID_PRIVATE_KEY = os.environ.get("RUNWAY_VAPID_PRIVATE_KEY", "").strip()
VAPID_EMAIL = os.environ.get("RUNWAY_VAPID_EMAIL", "mailto:steen.callum@albacars.ae").strip()
DUBAI = ZoneInfo("Asia/Dubai")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    # Jobs are short, serialized oneshots. DELETE mode keeps the completed
    # cache safely readable by the separate publisher without granting it
    # write access to SQLite WAL/SHM sidecars.
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("""CREATE TABLE IF NOT EXISTS appointments(
      appointment_key TEXT PRIMARY KEY, appointment_date TEXT NOT NULL, appointment_time TEXT NOT NULL DEFAULT '',
      stock_number TEXT NOT NULL DEFAULT '', customer_name TEXT NOT NULL DEFAULT '', vehicle_text TEXT NOT NULL DEFAULT '',
      salesperson TEXT NOT NULL DEFAULT '', checked_in TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', moved TEXT NOT NULL DEFAULT '',
      first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, payload_json TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS sync_runs(
      id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, rows_seen INTEGER NOT NULL DEFAULT 0, detail TEXT NOT NULL DEFAULT ''
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_date ON appointments(appointment_date,appointment_time)")
    db.commit()
    return db


def connect_readonly() -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def fetch_values() -> list[list[str]]:
    if not SOURCE_URL.startswith("https://script.google.com/macros/s/") or not SOURCE_KEY:
        raise RuntimeError("Approved Apps Script Pipeline reader is not configured")
    separator = "&" if "?" in SOURCE_URL else "?"
    url = SOURCE_URL + separator + urllib.parse.urlencode({"key": SOURCE_KEY})
    request = urllib.request.Request(url, method="GET", headers={"accept": "application/json", "user-agent": "DXB-Runway-Pipeline/1.0"})
    if request.get_method() != "GET":
        raise RuntimeError("Security block: Google reader method must be GET")
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read())
    values = payload.get("values")
    if payload.get("ok") is not True or not isinstance(values, list):
        raise RuntimeError(str(payload.get("error") or "Invalid Pipeline reader response"))
    return [[str(cell or "").strip() for cell in row] for row in values if isinstance(row, list)]


def parse_date(value: str) -> str:
    text = value.strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y %B %d", "%Y %b %d", "%B %d %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            pass
    match = re.search(r"\b(20\d{2})\s+([A-Za-z]+)\s+(\d{1,2})\b", text)
    if match:
        try:
            return datetime.strptime(" ".join(match.groups()), "%Y %B %d").date().isoformat()
        except ValueError:
            pass
    return ""


def normalise_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def parse_appointments(values: list[list[str]], default_date: str = "") -> list[dict]:
    appointments: list[dict] = []
    active_date = default_date
    header: dict[str, int] = {}
    aliases = {
        "stockNumber": {"sn", "stocknumber", "stockno", "stock"}, "customerName": {"name", "customer", "customername"},
        "vehicleText": {"car", "vehicle", "carmodel"}, "appointmentTime": {"time", "appointmenttime"},
        "salesperson": {"salesperson", "salespersonname", "sales"}, "checkedIn": {"checkedin", "checkedinquestion"},
        "note": {"note", "notes"}, "moved": {"moved", "movedquestion"},
    }
    for row_index, row in enumerate(values):
        joined = " ".join(row)
        discovered = next((parse_date(cell) for cell in row if parse_date(cell)), "")
        if discovered:
            active_date = discovered
        normalised = [normalise_header(cell) for cell in row]
        if "car" in normalised and ("time" in normalised or "name" in normalised):
            header = {}
            for field, names in aliases.items():
                match = next((i for i, name in enumerate(normalised) if name in names), None)
                if match is not None:
                    header[field] = match
            continue
        if not active_date or not header or "vehicleText" not in header:
            continue
        def cell(field: str) -> str:
            index = header.get(field, -1)
            return row[index].strip() if 0 <= index < len(row) else ""
        vehicle = cell("vehicleText")
        if not vehicle or normalise_header(vehicle) == "car":
            continue
        stock = cell("stockNumber")
        time = cell("appointmentTime")
        key = f"{active_date}:{stock}:{time}:{normalise_header(vehicle)}:{row_index}"
        appointments.append({"appointmentKey": key, "date": active_date, "appointmentTime": time, "stockNumber": stock,
            "customerName": cell("customerName"), "vehicleText": vehicle, "salesperson": cell("salesperson"),
            "checkedIn": cell("checkedIn"), "note": cell("note"), "moved": cell("moved")})
    return appointments


def publish(date_key: str, appointments: list[dict]) -> dict:
    if not MOBILE_BRIEF_URL.startswith("https://dxb-runway-mobile.randomsteen1.chatgpt.site/") or not SYNC_KEY:
        raise RuntimeError("Runway mobile briefing destination is not configured")
    payload = json.dumps({"date": date_key, "appointments": appointments}, separators=(",", ":")).encode()
    headers = {"content-type": "application/json", "x-dxb-sync-key": SYNC_KEY, "user-agent": "DXB-Runway-Pipeline/1.0"}
    if SITES_AUTH_TOKEN:
        headers["OAI-Sites-Authorization"] = "Bearer " + SITES_AUTH_TOKEN
    request = urllib.request.Request(MOBILE_BRIEF_URL, data=payload, method="POST", headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.loads(response.read())
    if result.get("ok") is not True:
        raise RuntimeError(str(result.get("error") or "Mobile briefing rejected"))
    return result


def send_push(result: dict) -> int:
    if not VAPID_PRIVATE_KEY:
        raise RuntimeError("VAPID private key is not configured on the VPS")
    try:
        from pywebpush import webpush
    except ImportError as error:
        raise RuntimeError("pywebpush is not installed") from error
    notification = result.get("notification") or {}
    sent = 0
    for row in result.get("pushSubscriptions") or []:
        subscription = {"endpoint": row.get("endpoint"), "keys": {"p256dh": row.get("p256dh"), "auth": row.get("auth")}}
        try:
            webpush(subscription_info=subscription, data=json.dumps(notification), vapid_private_key=VAPID_PRIVATE_KEY, vapid_claims={"sub": VAPID_EMAIL}, ttl=3600)
            sent += 1
        except Exception as error:
            print(f"push failed for one subscription: {error}")
    return sent


def mobile_headers(content_type: bool = False) -> dict[str, str]:
    headers = {"x-dxb-sync-key": SYNC_KEY, "user-agent": "DXB-Runway-Pipeline/1.0"}
    if content_type:
        headers["content-type"] = "application/json"
    if SITES_AUTH_TOKEN:
        headers["OAI-Sites-Authorization"] = "Bearer " + SITES_AUTH_TOKEN
    return headers


def dispatch_sold_notifications() -> int:
    """Deliver durable stock-to-sold events queued by the mobile sync API."""
    if not MOBILE_NOTIFICATIONS_URL.startswith("https://dxb-runway-mobile.randomsteen1.chatgpt.site/") or not SYNC_KEY:
        raise RuntimeError("Runway mobile notification queue is not configured")

    request = urllib.request.Request(MOBILE_NOTIFICATIONS_URL, method="GET", headers=mobile_headers())
    with urllib.request.urlopen(request, timeout=60) as response:
        queue = json.loads(response.read())
    if queue.get("ok") is not True:
        raise RuntimeError(str(queue.get("error") or "Mobile notification queue rejected"))

    subscriptions = queue.get("pushSubscriptions") or []
    delivered_ids: list[int] = []
    for event in queue.get("events") or []:
        notification = {
            "title": event.get("title") or "Vehicle sold",
            "body": event.get("body") or "A vehicle has moved from stock to sold.",
            "url": event.get("url") or "/?screen=desk",
            "tag": f"runway-{event.get('eventType', 'sold')}-{event.get('id')}",
        }
        sent = send_push({"notification": notification, "pushSubscriptions": subscriptions}) if subscriptions else 0
        if sent:
            delivered_ids.append(int(event["id"]))

    if delivered_ids:
        payload = json.dumps({"deliveredIds": delivered_ids}, separators=(",", ":")).encode()
        acknowledge = urllib.request.Request(
            MOBILE_NOTIFICATIONS_URL,
            data=payload,
            method="POST",
            headers=mobile_headers(content_type=True),
        )
        with urllib.request.urlopen(acknowledge, timeout=60) as response:
            result = json.loads(response.read())
        if result.get("ok") is not True:
            raise RuntimeError(str(result.get("error") or "Notification acknowledgement rejected"))
    return len(delivered_ids)


def write_agent_snapshot(rows: list[dict], generated_at: str) -> None:
    """Publish only the fields approved for the read-only advisory agent."""
    allowed = (
        "appointmentKey", "date", "appointmentTime", "stockNumber",
        "vehicleText", "salesperson", "checkedIn", "moved",
    )
    payload = {
        "generatedAt": generated_at,
        "appointments": [{key: row.get(key, "") for key in allowed} for row in rows],
    }
    AGENT_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".appointments-", dir=AGENT_SNAPSHOT_PATH.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(payload, output, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, AGENT_SNAPSHOT_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fetch_and_cache() -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as db:
        run_id = db.execute("INSERT INTO sync_runs(started_at,status) VALUES (?,'running')", (now,)).lastrowid
        try:
            rows = parse_appointments(fetch_values(), datetime.now(DUBAI).date().isoformat())
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            snapshot_dates = sorted({row["date"] for row in rows})
            for snapshot_date in snapshot_dates:
                db.execute("DELETE FROM appointments WHERE appointment_date=?", (snapshot_date,))
            for row in rows:
                db.execute("""INSERT INTO appointments(appointment_key,appointment_date,appointment_time,stock_number,customer_name,vehicle_text,salesperson,checked_in,note,moved,first_seen,last_seen,payload_json)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(appointment_key) DO UPDATE SET appointment_date=excluded.appointment_date,appointment_time=excluded.appointment_time,stock_number=excluded.stock_number,customer_name=excluded.customer_name,vehicle_text=excluded.vehicle_text,salesperson=excluded.salesperson,checked_in=excluded.checked_in,note=excluded.note,moved=excluded.moved,last_seen=excluded.last_seen,payload_json=excluded.payload_json""",
                  (row["appointmentKey"], row["date"], row["appointmentTime"], row["stockNumber"], row["customerName"], row["vehicleText"], row["salesperson"], row["checkedIn"], row["note"], row["moved"], timestamp, timestamp, json.dumps(row, separators=(",", ":"))))
            write_agent_snapshot(rows, timestamp)
            detail = f"fetched={len(rows)} dates={len(snapshot_dates)}"
            db.execute("UPDATE sync_runs SET finished_at=?,status='ok',rows_seen=?,detail=? WHERE id=?", (datetime.now(timezone.utc).isoformat(timespec="seconds"), len(rows), detail, run_id))
            db.commit()
            return {"ok": True, "detail": detail}
        except Exception as error:
            db.execute("UPDATE sync_runs SET finished_at=?,status='error',detail=? WHERE id=?", (datetime.now(timezone.utc).isoformat(timespec="seconds"), str(error)[:1000], run_id))
            db.commit()
            raise


def publish_cached(notify: bool = False, date_key: str | None = None) -> dict:
    target = date_key or datetime.now(DUBAI).date().isoformat()
    with connect_readonly() as db:
        records = db.execute("SELECT payload_json FROM appointments WHERE appointment_date=? ORDER BY appointment_time", (target,))
        appointments = [json.loads(row["payload_json"]) for row in records]
    result = publish(target, appointments)
    sent = send_push(result) if notify else 0
    sold_sent = dispatch_sold_notifications()
    return {"ok": True, "detail": f"today={len(appointments)} push={sent} sold_push={sold_sent}"}


def run(notify: bool = False, date_key: str | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    target = date_key or datetime.now(DUBAI).date().isoformat()
    with connect() as db:
        run_id = db.execute("INSERT INTO sync_runs(started_at,status) VALUES (?,'running')", (now,)).lastrowid
        try:
            rows = parse_appointments(fetch_values(), datetime.now(DUBAI).date().isoformat())
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            # Each source date is a complete read-only snapshot. Clear only the
            # matching local dates before replacing them so deleted or moved
            # appointments cannot remain stale in Runway.
            snapshot_dates = sorted({row["date"] for row in rows})
            for snapshot_date in snapshot_dates:
                db.execute("DELETE FROM appointments WHERE appointment_date=?", (snapshot_date,))
            for row in rows:
                db.execute("""INSERT INTO appointments(appointment_key,appointment_date,appointment_time,stock_number,customer_name,vehicle_text,salesperson,checked_in,note,moved,first_seen,last_seen,payload_json)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(appointment_key) DO UPDATE SET appointment_date=excluded.appointment_date,appointment_time=excluded.appointment_time,stock_number=excluded.stock_number,customer_name=excluded.customer_name,vehicle_text=excluded.vehicle_text,salesperson=excluded.salesperson,checked_in=excluded.checked_in,note=excluded.note,moved=excluded.moved,last_seen=excluded.last_seen,payload_json=excluded.payload_json""",
                  (row["appointmentKey"], row["date"], row["appointmentTime"], row["stockNumber"], row["customerName"], row["vehicleText"], row["salesperson"], row["checkedIn"], row["note"], row["moved"], timestamp, timestamp, json.dumps(row, separators=(",", ":"))))
            today_rows = [dict(row) for row in db.execute("SELECT payload_json FROM appointments WHERE appointment_date=? ORDER BY appointment_time", (target,))]
            appointments = [json.loads(row["payload_json"]) for row in today_rows]
            result = publish(target, appointments)
            sent = send_push(result) if notify else 0
            sold_sent = dispatch_sold_notifications()
            detail = f"fetched={len(rows)} today={len(appointments)} push={sent} sold_push={sold_sent}"
            db.execute("UPDATE sync_runs SET finished_at=?,status='ok',rows_seen=?,detail=? WHERE id=?", (datetime.now(timezone.utc).isoformat(timespec="seconds"), len(rows), detail, run_id)); db.commit()
            return {"ok": True, "detail": detail}
        except Exception as error:
            db.execute("UPDATE sync_runs SET finished_at=?,status='error',detail=? WHERE id=?", (datetime.now(timezone.utc).isoformat(timespec="seconds"), str(error)[:1000], run_id)); db.commit(); raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fetch-only", action="store_true", help="GET Google and refresh the local cache only")
    mode.add_argument("--publish-only", action="store_true", help="Publish the cached brief without accessing Google")
    parser.add_argument("--notify", action="store_true", help="Send the 07:00 iPhone push after updating the brief")
    parser.add_argument("--date", help="Override Dubai date as YYYY-MM-DD")
    args = parser.parse_args()
    if args.fetch_only:
        if args.notify:
            parser.error("--notify cannot be combined with --fetch-only")
        outcome = fetch_and_cache()
    elif args.publish_only:
        outcome = publish_cached(notify=args.notify, date_key=args.date)
    else:
        outcome = run(notify=args.notify, date_key=args.date)
    print(json.dumps(outcome, separators=(",", ":")))
