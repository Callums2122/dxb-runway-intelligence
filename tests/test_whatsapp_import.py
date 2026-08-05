from pathlib import Path
import zipfile

from dxb_runway.database import Database
from dxb_runway.whatsapp_import import copied_download_exports, delete_copied_download_exports, parse_whatsapp_zip, route_download_exports


CHAT_TEXT = """[05/08/2026, 9:20:39 am] Callum: Messages and calls are end-to-end encrypted. Only people in this chat can read, listen to, or share them.
[05/08/2026, 9:20:39 am] Callum Steen - ALBA CARS: Hey, is the Jeep still available?
[05/08/2026, 9:20:52 am] Callum: Yes, it is still available
"""


def make_export(path:Path,text:str=CHAT_TEXT)->Path:
    with zipfile.ZipFile(path,"w") as archive:
        archive.writestr("_chat.txt",text)
    return path


def make_html_export(path:Path,chat_name:str="Dr Hoppman")->Path:
    html='''<!DOCTYPE html><html><body><div class="__date"><span>August 4, 2026</span></div><div class="__message-out"><div>Hi, is tomorrow good for an inspection?</div><span>5:26 PM</span></div><div class="__message-in"><div>I will let you know.</div><span>5:56 PM</span></div><div class="__date"><span>August 5, 2026</span></div><div class="__message-out"><div>How did the service go?</div><span>10:03 AM</span></div></body></html>'''
    with zipfile.ZipFile(path,"w") as archive:
        archive.writestr(f"{chat_name}.html",html)
    return path


def test_whatsapp_export_routes_without_removing_original(tmp_path:Path):
    downloads=tmp_path/"Downloads"; downloads.mkdir(); inbox=tmp_path/"inbox"
    source=make_export(downloads/"WhatsApp Chat - Callum.zip")
    (downloads/"unrelated.zip").write_bytes(b"not a chat")
    routed=route_download_exports(downloads,inbox)
    assert source.exists() and len(routed)==1 and routed[0].exists()
    assert route_download_exports(downloads,inbox)==[]


def test_html_export_without_whatsapp_filename_is_parsed_and_routed(tmp_path:Path):
    downloads=tmp_path/"Downloads"; downloads.mkdir(); inbox=tmp_path/"inbox"
    source=make_html_export(downloads/"Dr Hoppman (1).zip")
    routed=route_download_exports(downloads,inbox)
    assert source.exists() and len(routed)==1
    chat=parse_whatsapp_zip(routed[0])
    assert chat.chat_name=="Dr Hoppman"
    assert [message.sent_at.isoformat() for message in chat.messages]==["2026-08-04T17:26:00","2026-08-04T17:56:00","2026-08-05T10:03:00"]
    assert chat.messages[0].sender=="Callum Steen - ALBA CARS"
    assert chat.messages[1].sender=="Dr Hoppman"


def test_number_named_html_export_matches_unique_customer_phone_suffix(tmp_path:Path):
    db=Database(tmp_path/"runway.db")
    customer_id=db.add_customer_contact({"customer_name":"N","vehicle_name":"BMW X5","phone_last5":"22797"})
    chat=parse_whatsapp_zip(make_html_export(tmp_path/"+971 55 332 2797.zip","+971 55 332 2797"))
    db.import_whatsapp_chat(chat)
    imported=db.whatsapp_imports()[0]
    assert imported["status"]=="imported" and imported["customer_id"]==customer_id


def test_work_contacts_and_groups_are_copied_to_ignored_and_cleanup_is_explicit(tmp_path:Path):
    downloads=tmp_path/"Downloads"; downloads.mkdir(); inbox=tmp_path/"inbox"
    work=make_html_export(downloads/"James Work.zip","James Work")
    group=make_html_export(downloads/"Purchase Team.zip","Purchase Team")
    valid=make_html_export(downloads/"Customer.zip","Customer")
    unrelated=downloads/"photos.zip"; unrelated.write_bytes(b"not a zip")
    (downloads/"smart-inbox-all-contacts.csv").write_text('"Name","Phone Number","Business or Personal"\n"Purchase Team","123-456","Group"\n',encoding="utf-8")
    routed=route_download_exports(downloads,inbox)
    assert len(routed)==3
    assert len(list((inbox/"ignored").glob("*.zip")))==2
    assert len(list(inbox.glob("*.zip")))==1
    assert set(copied_download_exports(downloads,inbox))=={work,group,valid}
    assert set(delete_copied_download_exports(downloads,inbox))=={work,group,valid}
    assert unrelated.exists() and not work.exists() and not group.exists() and not valid.exists()


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


def test_failed_export_is_retried_after_parser_upgrade(tmp_path:Path):
    db=Database(tmp_path/"runway.db")
    export=make_html_export(tmp_path/"Customer.zip","Customer")
    digest=parse_whatsapp_zip(export).file_hash
    failed_id=db.record_failed_whatsapp_import(export.name,digest,"Old parser did not support HTML")
    assert not db.whatsapp_import_known(digest)
    imported_id=db.import_whatsapp_chat(parse_whatsapp_zip(export))
    assert imported_id>0 and failed_id>0
    assert db.whatsapp_imports()[0]["status"]=="needs_review" and db.whatsapp_imports()[0]["error_text"]==""
