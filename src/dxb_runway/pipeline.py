from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Any

from .database import Database
from .google_schedule import GoogleSheetsReadOnlyClient, GoogleScheduleError


PIPELINE_READER_ORIGIN = "https://script.google.com"


def get_pipeline_reader_values(endpoint: str, access_key: str) -> list[list[str]]:
    """Read the private Pipeline bridge using one capability-limited GET request."""
    endpoint = str(endpoint or "").strip()
    access_key = str(access_key or "").strip()
    if not endpoint or not access_key:
        raise GoogleScheduleError("The private Pipeline reader is not configured. Cached appointments remain available.")
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme != "https" or parsed.netloc != "script.google.com" or not parsed.path.startswith("/macros/s/"):
        raise GoogleScheduleError("Blocked unapproved Pipeline reader destination.")
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("key", access_key))
    url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    if request.get_method() != "GET":
        raise GoogleScheduleError("Blocked: Pipeline integration is strictly read-only.")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise GoogleScheduleError(f"The private Pipeline reader could not be read (HTTP {error.code}). Cached appointments remain available.") from None
    except (urllib.error.URLError, json.JSONDecodeError):
        raise GoogleScheduleError("The private Pipeline reader is temporarily unavailable. Cached appointments remain available.") from None
    if not payload.get("ok"):
        raise GoogleScheduleError(str(payload.get("error") or "The private Pipeline reader rejected the request."))
    values = payload.get("values")
    return values if isinstance(values, list) else []


def spreadsheet_id(value: str) -> str:
    text = str(value or "").strip()
    match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", text)
    candidate = match.group(1) if match else text
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{20,}", candidate) else ""


def _norm(value: object) -> str:
    text = str(value or "").upper().replace("MERCEDES-BENZ", "MERCEDES").replace("RANGE ROVER", "LAND ROVER")
    text = re.sub(r"\b(NEW|USED|GCC|UAE|CLASS)\b", " ", text)
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def _date(value: object) -> str | None:
    text = str(value or "").strip()
    for pattern in ("%Y %B %d", "%Y %b %d", "%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d"):
        try: return datetime.strptime(text, pattern).date().isoformat()
        except ValueError: pass
    match = re.search(r"(20\d{2})\s+([A-Za-z]+)\s+(\d{1,2})", text)
    if match:
        try: return datetime.strptime(" ".join(match.groups()), "%Y %B %d").date().isoformat()
        except ValueError: pass
    return None


def _vehicle_parts(value: object) -> tuple[int | None, tuple[str, ...]]:
    text = _norm(value); year_match = re.search(r"\b(20\d{2})\b", text); year = int(year_match.group(1)) if year_match else None
    if year_match: text = re.sub(rf"\b{year}\b", " ", text)
    tokens = tuple(token for token in text.split() if token not in {"THE", "CAR", "PREMIUM", "PLUS", "LINE", "EDITION"})
    return year, tokens


def _same_model(left: object, right: object) -> bool:
    _, a = _vehicle_parts(left); _, b = _vehicle_parts(right)
    if not a or not b: return False
    compact_a = "".join(a); compact_b = "".join(b)
    if compact_a in compact_b or compact_b in compact_a: return True
    common = set(a) & set(b)
    return len(common) >= min(2, len(set(a)), len(set(b)))


def _stock_number_key(value: object) -> str:
    """Compare Sheet-formatted numbers (13,848) with locally stored values (13848)."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").strip().upper())


def match_stock(vehicle_text: str, stock: list[dict[str, Any]], stock_number: str = "") -> tuple[int | None, str, str]:
    wanted_stock_number=_stock_number_key(stock_number)
    if wanted_stock_number:
        exact_number=next((row for row in stock if _stock_number_key(row.get("external_stock_number"))==wanted_stock_number),None)
        if exact_number:return int(exact_number["id"]),"green",f"Exact stock number {wanted_stock_number} · {exact_number['vehicle_name']}"
    source_year, _ = _vehicle_parts(vehicle_text)
    candidates = [row for row in stock if _same_model(vehicle_text, row["vehicle_name"])]
    if not candidates: return None, "unmatched", "No matching make/model currently in stock"
    exact = [row for row in candidates if source_year and _vehicle_parts(row["vehicle_name"])[0] == source_year]
    chosen = exact[0] if exact else candidates[0]
    if exact: return int(chosen["id"]), "green", f"Exact year, make and model · {chosen['vehicle_name']}"
    return int(chosen["id"]), "amber", f"Same make and model · stock is {chosen['vehicle_name']}"


def parse_pipeline(values: list[list[str]], stock: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_date: str | None = None; section = "Appointments"; headers: dict[str, int] = {}; output: list[dict[str, Any]] = []
    aliases = {"NO":"no","SN":"stock_number","STOCK NO":"stock_number","STOCK NUMBER":"stock_number","NAME":"customer_name","CUSTOMER":"customer_name","CAR":"vehicle_text","VEHICLE":"vehicle_text","TIME":"appointment_time","SALESPERSON":"salesperson","CHECKED IN?":"checked_in","CHECKED IN":"checked_in","NOTE":"note","NOTES":"note","MOVED?":"moved","MOVED":"moved"}
    for row_index, row in enumerate(values):
        cells = [str(cell or "").strip() for cell in row]; joined = " ".join(cell for cell in cells if cell)
        found_date = next((_date(cell) for cell in cells if _date(cell)), None)
        if found_date: current_date = found_date
        if "APPOINTMENT" in joined.upper() and len(joined) < 100: section = joined.title()
        normalized = [_norm(cell) for cell in cells]
        if "CAR" in normalized or "VEHICLE" in normalized:
            headers = {aliases[name]: index for index, name in enumerate(normalized) if name in aliases}; continue
        if not headers or "vehicle_text" not in headers: continue
        def cell(key: str) -> str:
            index = headers.get(key, -1); return cells[index] if 0 <= index < len(cells) else ""
        vehicle = cell("vehicle_text")
        appointment_number = cell("no")
        # Management often creates the booking before filling in its vehicle.
        # A numbered rota row is still a real appointment and must be counted.
        is_numbered_appointment = bool(re.fullmatch(r"\d+", appointment_number.replace(",", "").strip()))
        has_appointment_details = bool(cell("customer_name") and cell("appointment_time"))
        if not is_numbered_appointment and not has_appointment_details: continue
        if _norm(vehicle) in {"CAR", "VEHICLE"}: continue
        if vehicle:
            matched, grade, detail = match_stock(vehicle, stock, cell("stock_number"))
        else:
            vehicle = "Vehicle not supplied"
            matched, grade, detail = None, "unmatched", "Management has not supplied a vehicle for this appointment yet"
        day = current_date or date.today().isoformat()
        key = "|".join((cell("stock_number"), cell("customer_name"), vehicle, cell("appointment_time"), str(row_index)))
        output.append({"appointment_date":day,"source_row_key":hashlib.sha256(key.encode()).hexdigest()[:24],"stock_number":cell("stock_number"),"customer_name":cell("customer_name"),"vehicle_text":vehicle,"appointment_time":cell("appointment_time"),"salesperson":cell("salesperson"),"checked_in":cell("checked_in"),"note":cell("note"),"moved":cell("moved"),"section_name":section,"matched_vehicle_id":matched,"match_grade":grade,"match_detail":detail})
    return output


def sync_pipeline(db: Database) -> int:
    source_id = spreadsheet_id(db.get_setting("pipeline_spreadsheet_id", "")); sheet = db.get_setting("pipeline_sheet_name", "Pipeline").strip() or "Pipeline"
    if not source_id: raise GoogleScheduleError("Paste the Pipeline Google Sheet link in Settings first. Cached appointments remain available.")
    run = db.execute("INSERT INTO pipeline_sync_runs(status,message) VALUES ('running','Reading Pipeline — strictly read only')")
    try:
        reader_url = db.get_setting("pipeline_reader_url", "").strip()
        reader_key = db.get_setting("pipeline_reader_key", "").strip()
        if reader_url or reader_key:
            if not reader_url or not reader_key:
                raise GoogleScheduleError("The private Pipeline reader URL and access key must both be configured. Cached appointments remain available.")
            values = get_pipeline_reader_values(reader_url, reader_key)
        else:
            values = GoogleSheetsReadOnlyClient().get_spreadsheet_values(source_id, sheet)
        stock = [dict(row) for row in db.query("SELECT id,vehicle_name,external_stock_number FROM vehicles WHERE status='stock' ORDER BY id")]
        rows = parse_pipeline(values, stock); digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        days = sorted({row["appointment_date"] for row in rows})
        with db.connect() as connection:
            for day in days: connection.execute("DELETE FROM pipeline_appointments WHERE appointment_date=?", (day,))
            connection.executemany("""INSERT INTO pipeline_appointments(appointment_date,source_row_key,stock_number,customer_name,vehicle_text,appointment_time,salesperson,checked_in,note,moved,section_name,matched_vehicle_id,match_grade,match_detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", [tuple(row[key] for key in ("appointment_date","source_row_key","stock_number","customer_name","vehicle_text","appointment_time","salesperson","checked_in","note","moved","section_name","matched_vehicle_id","match_grade","match_detail")) for row in rows])
            connection.execute("UPDATE pipeline_sync_runs SET status='success',message=?,content_hash=?,completed_at=CURRENT_TIMESTAMP WHERE id=?", (f"Read-only sync complete · {len(rows)} appointments", digest, run))
        return len(rows)
    except Exception as error:
        db.execute("UPDATE pipeline_sync_runs SET status='failed',message=?,completed_at=CURRENT_TIMESTAMP WHERE id=?", (str(error), run)); raise


def rematch_cached_appointments(db: Database) -> int:
    """Rewire cached appointments after local stock details change; no Google write occurs."""
    stock=[dict(row) for row in db.query("SELECT id,vehicle_name,external_stock_number FROM vehicles WHERE status='stock' ORDER BY id")]
    rows=db.query("SELECT id,vehicle_text,stock_number FROM pipeline_appointments WHERE appointment_date>=?",(date.today().isoformat(),))
    changed=0
    with db.connect() as connection:
        for row in rows:
            matched,grade,detail=match_stock(str(row["vehicle_text"] or ""),stock,str(row["stock_number"] or ""))
            connection.execute("UPDATE pipeline_appointments SET matched_vehicle_id=?,match_grade=?,match_detail=?,synced_at=CURRENT_TIMESTAMP WHERE id=?",(matched,grade,detail,row["id"]));changed+=1
    return changed


def appointments(db: Database, day: str | None = None) -> list[dict[str, Any]]:
    day = day or date.today().isoformat()
    return [dict(row) for row in db.query("SELECT p.*,v.vehicle_name AS matched_vehicle FROM pipeline_appointments p LEFT JOIN vehicles v ON v.id=p.matched_vehicle_id WHERE p.appointment_date=? ORDER BY p.appointment_time,p.id", (day,))]


def sync_status(db: Database) -> dict[str, Any]:
    rows = db.query("SELECT * FROM pipeline_sync_runs ORDER BY id DESC LIMIT 1")
    return dict(rows[0]) if rows else {"status":"never","message":"Waiting for first read-only Pipeline sync","completed_at":None}


def connection_status(db: Database) -> tuple[bool, str]:
    """Report the actual Pipeline transport state without exposing credentials."""
    source = spreadsheet_id(db.get_setting("pipeline_spreadsheet_id", ""))
    reader_url = db.get_setting("pipeline_reader_url", "").strip()
    reader_key = db.get_setting("pipeline_reader_key", "").strip()
    if not source:
        return False, "Pipeline spreadsheet is not configured"
    if bool(reader_url) != bool(reader_key):
        return False, "Private reader configuration is incomplete"
    if reader_url and reader_key:
        return True, "Connected through the private GET-only reader"
    return False, "Private Pipeline reader URL and access key are required"
