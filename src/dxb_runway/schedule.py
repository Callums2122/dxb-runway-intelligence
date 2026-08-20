from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from typing import Any

from .database import Database
from .google_schedule import GoogleSheetsReadOnlyClient, GoogleScheduleError

SPREADSHEET_ID="19I7Hmi8xptq5KMuDMamAwcU-dNBcRMx37S7tmpJYcfw";SHEET_NAME="SCHEDULE 2026";MY_NAME="Callum Steen"
OFF_TYPES={"OFF","ANNUAL LEAVE","SICK LEAVE","UNPAID LEAVE","ADDITIONAL/SPECIAL LEAVE","GOLDEN DAY / COMP OFF","ALBA HOLIDAY / COMP OFF","BIRTHDAY"}
NON_PERSON_HEADERS={"DATE","DAY","WEEK","MONTH","NOTES","NOTE","COMMENTS","COMMENT","SHIFT","STATUS"}

def _norm(value:object)->str:return re.sub(r"\s+"," ",str(value or "").strip()).upper()

def _date(value:object)->str|None:
    text=str(value or "").strip()
    for pattern in ("%d/%m/%Y","%d-%m-%Y","%Y-%m-%d","%d %b %Y","%d %B %Y","%a %d %b %Y"):
        try:return datetime.strptime(text,pattern).date().isoformat()
        except ValueError:pass
    return None

def classify_shift(value:object)->str:
    text=_norm(value)
    if not text:return "Normal Working Day"
    aliases=(("EVENING SHIFT","EVENING SHIFT"),("ANNUAL LEAVE","ANNUAL LEAVE"),("SICK LEAVE","SICK LEAVE"),("UNPAID LEAVE","UNPAID LEAVE"),("ADDITIONAL/SPECIAL LEAVE","ADDITIONAL/SPECIAL LEAVE"),("ADDITIONAL LEAVE","ADDITIONAL/SPECIAL LEAVE"),("SPECIAL LEAVE","ADDITIONAL/SPECIAL LEAVE"),("GOLDEN DAY","GOLDEN DAY / COMP OFF"),("ALBA HOLIDAY","ALBA HOLIDAY / COMP OFF"),("BIRTHDAY","BIRTHDAY"),("REMOVED FROM LEADS","REMOVED FROM LEADS"),("STANDARD","STANDARD"),("OFF","OFF"))
    return next((canonical for token,canonical in aliases if token in text),text.title())

def get_schedule_rows(values:list[list[str]])->list[dict[str,str]]:
    header_index=-1;headers=[]
    for index,row in enumerate(values):
        normal=[_norm(cell) for cell in row]
        if "DATE" in normal and _norm(MY_NAME) in normal:header_index=index;headers=[str(cell).strip() for cell in row];break
    if header_index<0:raise GoogleScheduleError("Schedule structure changed: Date or Callum Steen header was not found. Using cached rota.")
    date_col=next(i for i,value in enumerate(headers) if _norm(value)=="DATE");people=[(i,name) for i,name in enumerate(headers) if name.strip() and _norm(name) not in NON_PERSON_HEADERS]
    output=[]
    for raw in values[header_index+1:]:
        day=_date(raw[date_col] if date_col<len(raw) else "")
        if not day:continue
        for column,name in people:
            value=raw[column] if column<len(raw) else "";output.append({"schedule_date":day,"person_name":name.strip(),"shift_type":classify_shift(value),"raw_value":str(value or "").strip()})
    if not any(_norm(row["person_name"])==_norm(MY_NAME) for row in output):raise GoogleScheduleError("Callum Steen was removed from the schedule structure. Using cached rota.")
    return output

def sync_schedule(db:Database)->int:
    run=db.execute("INSERT INTO schedule_sync_runs(status,message) VALUES ('running','Reading management schedule — read only')")
    try:
        values=GoogleSheetsReadOnlyClient().get_spreadsheet_values(SPREADSHEET_ID,SHEET_NAME);rows=get_schedule_rows(values);digest=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest();previous={row["schedule_date"]:row["shift_type"] for row in db.query("SELECT schedule_date,shift_type FROM schedule_entries WHERE lower(person_name)=lower(?)",(MY_NAME,))}
        current={row["schedule_date"]:row["shift_type"] for row in rows if _norm(row["person_name"])==_norm(MY_NAME)}
        with db.connect() as connection:
            for day,new in current.items():
                old=previous.get(day)
                if old is not None and old!=new and day>=date.today().isoformat():connection.execute("INSERT INTO schedule_changes(schedule_date,old_shift,new_shift) VALUES (?,?,?)",(day,old,new))
            connection.execute("DELETE FROM schedule_entries")
            connection.executemany("INSERT INTO schedule_entries(schedule_date,person_name,shift_type,raw_value) VALUES (?,?,?,?)",[(r["schedule_date"],r["person_name"],r["shift_type"],r["raw_value"]) for r in rows])
            connection.execute("UPDATE schedule_sync_runs SET status='success',message=?,content_hash=?,completed_at=CURRENT_TIMESTAMP WHERE id=?",(f"Read-only sync complete · {len(current)} rota days",digest,run))
        return len(current)
    except Exception as error:
        db.execute("UPDATE schedule_sync_runs SET status='failed',message=?,completed_at=CURRENT_TIMESTAMP WHERE id=?",(str(error),run));raise

def get_my_schedule(db:Database)->list[dict[str,Any]]:return [dict(row) for row in db.query("SELECT * FROM schedule_entries WHERE lower(person_name)=lower(?) ORDER BY schedule_date",(MY_NAME,))]
def get_evening_shift_team(db:Database,day:str)->list[str]:return [row["person_name"] for row in db.query("SELECT person_name FROM schedule_entries WHERE schedule_date=? AND shift_type='EVENING SHIFT' AND lower(person_name)<>lower(?) ORDER BY person_name",(day,MY_NAME))]
def get_upcoming_schedule(db:Database,start:date|None=None)->list[dict[str,Any]]:
    start=start or date.today();return [row for row in get_my_schedule(db) if row["schedule_date"]>=start.isoformat()]
def get_recent_changes(db:Database)->list[dict[str,Any]]:return [dict(row) for row in db.query("SELECT * FROM schedule_changes ORDER BY detected_at DESC,id DESC LIMIT 10")]
def sync_status(db:Database)->dict[str,Any]:
    rows=db.query("SELECT * FROM schedule_sync_runs ORDER BY id DESC LIMIT 1");return dict(rows[0]) if rows else {"status":"never","message":"Waiting for first read-only sync","completed_at":None}
