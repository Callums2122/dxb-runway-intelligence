from __future__ import annotations

from dxb_runway.database import Database
from dxb_runway.google_schedule import GoogleSheetsReadOnlyClient
from dxb_runway.pipeline import appointments, get_pipeline_reader_values, parse_pipeline, spreadsheet_id, sync_pipeline


def sample_values():
    return [
        ["", "2026 August 23"],
        ["COMPLETED APPOINTMENTS"],
        ["NO","SN","NAME","CAR","TIME","SALESPERSON","CHECKED IN?","NOTE","MOVED?"],
        ["1","13833","Ali","Audi Q8 2024","9:30 AM","Finlay","Yes","test drive","Yes"],
        ["2","13412","James","Audi Q8 2023","10:00 AM","Matthew","","","Yes"],
        ["3","12921","Zeeshu","GAC GS8 2022","2:00 PM","","","","Yes"],
    ]


def test_pipeline_parser_grades_exact_model_and_unmatched():
    stock=[{"id":1,"vehicle_name":"2024 Audi Q8"}]
    rows=parse_pipeline(sample_values(),stock)
    assert [row["match_grade"] for row in rows]==["green","amber","unmatched"]
    assert all(row["appointment_date"]=="2026-08-23" for row in rows)


def test_pipeline_sync_is_read_only_and_caches(tmp_path,monkeypatch):
    db=Database(tmp_path/"data.db");db.add_vehicle(vehicle_name="2024 Audi Q8",purchase_type="cash",purchase_price_aed=200000,expected_sale_price_aed=250000,purchased_date="2026-08-01");db.set_setting("pipeline_spreadsheet_id","https://docs.google.com/spreadsheets/d/abcdefghijklmnopqrstuvwxyz123456789/edit");db.set_setting("pipeline_sheet_name","Pipeline")
    calls=[]
    def read(self,source,tab):calls.append((source,tab));return sample_values()
    monkeypatch.setattr(GoogleSheetsReadOnlyClient,"get_spreadsheet_values",read)
    assert sync_pipeline(db)==3
    assert calls==[("abcdefghijklmnopqrstuvwxyz123456789","Pipeline")]
    assert {row["match_grade"] for row in appointments(db,"2026-08-23")}=={"green","amber","unmatched"}


def test_spreadsheet_id_rejects_non_google_noise():
    assert spreadsheet_id("not a sheet")==""


def test_private_reader_is_get_only(monkeypatch):
    captured=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):return None
        def read(self):return b'{"ok":true,"values":[["Pipeline"]]}'
    def open_request(request,timeout):
        captured.append((request.full_url,request.get_method(),timeout));return Response()
    monkeypatch.setattr("urllib.request.urlopen",open_request)
    assert get_pipeline_reader_values("https://script.google.com/macros/s/deployment/exec","private-key")==[["Pipeline"]]
    assert captured[0][1]=="GET"
    assert "key=private-key" in captured[0][0]


def test_private_reader_rejects_other_hosts():
    import pytest
    with pytest.raises(Exception,match="Blocked unapproved"):
        get_pipeline_reader_values("https://example.com/macros/s/deployment/exec","private-key")
