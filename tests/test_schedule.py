from __future__ import annotations

import json
from datetime import date,timedelta

import pytest

from dxb_runway.database import Database
from dxb_runway.google_schedule import GoogleScheduleError,GoogleSheetsReadOnlyClient,SCOPE
from dxb_runway.schedule import classify_shift,get_evening_shift_team,get_recent_changes,get_schedule_rows,sync_schedule


def test_shift_classification_including_blank():
    assert classify_shift("")=="Normal Working Day"
    for value in ("EVENING SHIFT","OFF","ANNUAL LEAVE","SICK LEAVE","UNPAID LEAVE","ADDITIONAL/SPECIAL LEAVE","GOLDEN DAY / COMP OFF","ALBA HOLIDAY / COMP OFF","STANDARD","BIRTHDAY","REMOVED FROM LEADS"):
        assert classify_shift(value)==value


def test_parser_finds_dynamic_columns_and_ignores_metadata():
    values=[["Management rota"],["Date","Day","Notes","Aisha Khan","Callum Steen","Ben Jones"],["20/08/2026","Thursday","Busy","EVENING SHIFT","","EVENING SHIFT"]]
    rows=get_schedule_rows(values)
    assert {(row["person_name"],row["shift_type"]) for row in rows}=={("Aisha Khan","EVENING SHIFT"),("Callum Steen","Normal Working Day"),("Ben Jones","EVENING SHIFT")}


def test_parser_requires_callum_and_date():
    with pytest.raises(GoogleScheduleError):get_schedule_rows([["Date","Someone Else"],["20/08/2026","OFF"]])


def test_sync_caches_locally_and_records_future_change(tmp_path,monkeypatch):
    db=Database(tmp_path/"data.db");future=(date.today()+timedelta(days=5)).strftime("%d/%m/%Y")
    payloads=[[["Date","Callum Steen","Aisha"],[future,"","EVENING SHIFT"]],[["Date","Callum Steen","Aisha"],[future,"OFF","EVENING SHIFT"]]]
    monkeypatch.setenv("DXB_GOOGLE_OAUTH_CLIENT_ID","test-client")
    monkeypatch.setattr(GoogleSheetsReadOnlyClient,"get_spreadsheet_values",lambda self,*args:payloads.pop(0))
    assert sync_schedule(db)==1
    assert sync_schedule(db)==1
    changes=get_recent_changes(db)
    assert changes[0]["old_shift"]=="Normal Working Day" and changes[0]["new_shift"]=="OFF"
    day=date.today()+timedelta(days=5)
    assert get_evening_shift_team(db,day.isoformat())==["Aisha"]


def test_sheets_transport_is_get_only(monkeypatch):
    monkeypatch.setenv("DXB_GOOGLE_OAUTH_CLIENT_ID","test-client");client=GoogleSheetsReadOnlyClient();monkeypatch.setattr(client,"_access_token",lambda:"secret")
    captured=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps({"values":[["Date","Callum Steen"]]}).encode()
    def fake_open(request,timeout):captured.append(request);return Response()
    monkeypatch.setattr("dxb_runway.google_schedule.urllib.request.urlopen",fake_open)
    client.get_spreadsheet_values("sheet-id","SCHEDULE 2026")
    assert captured[0].get_method()=="GET" and captured[0].full_url.startswith("https://sheets.googleapis.com/")
    with pytest.raises(GoogleScheduleError):client._sheets_get("https://example.com/not-sheets")
    assert SCOPE=="https://www.googleapis.com/auth/spreadsheets.readonly"
