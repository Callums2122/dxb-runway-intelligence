from pathlib import Path
import zipfile

from dxb_runway.database import Database
from dxb_runway.whatsapp_import import parse_whatsapp_zip, route_download_exports


CHAT_TEXT = """[05/08/2026, 9:20:39 am] Callum: Messages and calls are end-to-end encrypted. Only people in this chat can read, listen to, or share them.
[05/08/2026, 9:20:39 am] Callum Steen - ALBA CARS: Hey, is the Jeep still available?
[05/08/2026, 9:20:52 am] Callum: Yes, it is still available
"""


def make_export(path:Path,text:str=CHAT_TEXT)->Path:
    with zipfile.ZipFile(path,"w") as archive:
        archive.writestr("_chat.txt",text)
    return path


def test_whatsapp_export_routes_without_removing_original(tmp_path:Path):
    downloads=tmp_path/"Downloads"; downloads.mkdir(); inbox=tmp_path/"inbox"
    source=make_export(downloads/"WhatsApp Chat - Callum.zip")
    (downloads/"unrelated.zip").write_bytes(b"not a chat")
    routed=route_download_exports(downloads,inbox)
    assert source.exists() and len(routed)==1 and routed[0].exists()
    assert route_download_exports(downloads,inbox)==[]


def test_whatsapp_import_updates_unique_customer_and_recommends_action(tmp_path:Path):
    db=Database(tmp_path/"runway.db")
    customer_id=db.add_customer_contact({"customer_name":"Callum","vehicle_name":"Jeep Wrangler","vehicle_age_years":2021,"phone_last5":"12345"})
    chat=parse_whatsapp_zip(make_export(tmp_path/"WhatsApp Chat - Callum.zip"))
    first_id=db.import_whatsapp_chat(chat); second_id=db.import_whatsapp_chat(chat)
    assert first_id==second_id
    imported=db.whatsapp_imports()[0]
    assert imported["status"]=="imported" and imported["customer_id"]==customer_id
    assert imported["action_type"]=="Qualify" and imported["new_message_count"]==2
    customer=db.query("SELECT * FROM customer_contacts WHERE id=?",(customer_id,))[0]
    assert customer["last_contacted_date"]=="2026-08-05" and customer["next_contact_date"]=="2026-08-08"
    lead=db.project5_leads()[0]
    assert lead["stage"]=="replied" and db.project5_source_stats()[0]["target"]==1.5


def test_ambiguous_whatsapp_name_requires_manual_link(tmp_path:Path):
    db=Database(tmp_path/"runway.db")
    first=db.add_customer_contact({"customer_name":"Sam","vehicle_name":"Audi A3","phone_last5":"11111"})
    db.add_customer_contact({"customer_name":"Sam","vehicle_name":"BMW M4","phone_last5":"22222"})
    chat=parse_whatsapp_zip(make_export(tmp_path/"WhatsApp Chat - Sam.zip"))
    import_id=db.import_whatsapp_chat(chat)
    assert db.whatsapp_imports()[0]["status"]=="needs_review"
    db.link_whatsapp_import(import_id,first,"Dubizzle")
    assert db.whatsapp_imports()[0]["status"]=="imported"
    assert db.project5_leads()[0]["source"]=="Dubizzle"
