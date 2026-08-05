from pathlib import Path
import zipfile

from dxb_runway.contact_import import import_downloaded_contacts, parse_chat_export
from dxb_runway.database import Database


def make_export(path:Path,name:str="+971 50 123 4567",messages=None)->Path:
    messages=messages or [
        ("August 2, 2026","out","Hi, is your 2023 Ford Explorer with 83,500 km still available?"),
        ("August 2, 2026","in","Yes, asking price is AED 150,000."),
        ("August 3, 2026","out","We can offer 125k cash subject to inspection."),
        ("August 3, 2026","in","Perfect, inspection sounds good. Thank you."),
    ]
    body=[]
    for sent,direction,text in messages:
        body.append(f'<div class="__date"><span>{sent}</span></div><div class="__message-{direction}"><div class="___3zb-j __ZhF0n">{text}</div></div>')
    with zipfile.ZipFile(path,"w") as archive: archive.writestr(f"{name}.html","<html>"+"".join(body)+"</html>")
    return path


def test_html_export_extracts_contact_vehicle_and_strong_rapport(tmp_path:Path):
    record=parse_chat_export(make_export(tmp_path/"seller.zip"))
    assert record.customer_name=="Ford Explorer"
    assert record.phone_last5=="34567"
    assert (record.model_year,record.vehicle_name,record.mileage)==(2023,"Ford Explorer",83500)
    assert (record.vehicle_price_aed,record.cash_offer_aed)==(150000,125000)
    assert record.rapport=="red"


def test_import_adds_then_updates_without_duplicate(tmp_path:Path):
    downloads=tmp_path/"Downloads"; downloads.mkdir(); db=Database(tmp_path/"runway.db")
    first=make_export(downloads/"first.zip")
    result=import_downloaded_contacts(db,downloads)
    assert (result.added,result.updated)==(1,0) and result.processed_files==[first]
    first.unlink(); make_export(downloads/"newer.zip",messages=[
        ("August 5, 2026","out","Your 2023 Ford Explorer is around 130k cash."),
        ("August 5, 2026","in","Thanks"),
    ])
    result=import_downloaded_contacts(db,downloads)
    rows=db.query("SELECT * FROM customer_contacts")
    assert (result.added,result.updated,len(rows))==(0,1,1)
    assert rows[0]["cash_offer_aed"]==130000
    assert len(db.customer_contact_notes(rows[0]["id"]))==2


def test_work_contact_is_ignored(tmp_path:Path):
    path=make_export(tmp_path/"work.zip",name="Callum Work")
    assert parse_chat_export(path,{"callum work":"12345"}) is None
