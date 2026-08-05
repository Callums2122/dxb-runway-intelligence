from __future__ import annotations

import csv
import hashlib
import html
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path


@dataclass
class ChatMessage:
    direction: str
    text: str
    sent_on: date


@dataclass
class ContactImport:
    source: Path
    customer_name: str
    vehicle_name: str
    phone_last5: str
    mileage: int = 0
    model_year: int = 0
    vehicle_price_aed: float = 0
    cash_offer_aed: float = 0
    consignment_offer_aed: float = 0
    rapport: str = "green"
    next_contact_date: str = field(default_factory=lambda: date.today().isoformat())
    note: str = ""
    fingerprint: str = ""


@dataclass
class ImportResult:
    added: int = 0
    updated: int = 0
    ignored: int = 0
    failed: list[str] = field(default_factory=list)
    processed_files: list[Path] = field(default_factory=list)


VEHICLES = [
    r"Mercedes(?:-Benz)?\s+(?:AMG\s+)?(?:G\s?63|[CES]\s?\d{2,3}|GL[CES]\s?\d{2,3})",
    r"Toyota\s+(?:Land\s+Cruiser|RAV\s?4|Prado|Camry|Corolla)",
    r"Nissan\s+(?:Patrol|X-Trail|Pathfinder)", r"Jeep\s+(?:Wrangler|Grand\s+Cherokee)",
    r"Ford\s+(?:Explorer|Mustang|Ranger)", r"(?:Land\s+Rover\s+)?(?:Range\s+Rover(?:\s+Sport)?|Defender)",
    r"Porsche\s+(?:Cayenne|Macan|911)", r"Lexus\s+(?:LX|RX)\s?\d*",
    r"Audi\s+(?:Q[578]|A[345678]|RS\s?[34567])", r"BMW\s+(?:X[567]|M[2345]|\d{3}i?)",
    r"Volkswagen\s+Golf", r"Honda\s+(?:Accord|Civic)", r"Hyundai\s+Tucson",
    r"Kia\s+Sportage", r"Chevrolet\s+Tahoe", r"GMC\s+Yukon",
]

MODEL_ALIASES = [
    (r"\be[ -]?class\b", "Mercedes E-Class"), (r"\bc[ -]?class\b", "Mercedes C-Class"),
    (r"\bg\s?63\b", "Mercedes G63"), (r"\bland\s+cruiser\b", "Toyota Land Cruiser"),
    (r"\bpatrol\b", "Nissan Patrol"), (r"\bwrangler\b", "Jeep Wrangler"),
    (r"\brange\s+rover\s+sport\b", "Range Rover Sport"), (r"\bdefender\b", "Land Rover Defender"),
]


class _WhatsAppHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.depth=0; self.date_depth=None; self.message_depth=None; self.body_depth=None
        self.date_parts=[]; self.body_parts=[]; self.direction=""; self.current_date=date.today(); self.messages=[]

    def handle_starttag(self, tag, attrs):
        if tag != "div": return
        self.depth += 1; classes=dict(attrs).get("class","").split()
        if "__date" in classes: self.date_depth=self.depth; self.date_parts=[]
        if "__message-in" in classes or "__message-out" in classes:
            self.message_depth=self.depth; self.direction="in" if "__message-in" in classes else "out"; self.body_parts=[]
        if self.message_depth and "___3zb-j" in classes and "__ZhF0n" in classes: self.body_depth=self.depth

    def handle_data(self, data):
        if self.date_depth is not None: self.date_parts.append(data)
        if self.body_depth is not None: self.body_parts.append(data)

    def handle_endtag(self, tag):
        if tag != "div": return
        if self.body_depth == self.depth: self.body_depth=None
        if self.message_depth == self.depth:
            text=" ".join(" ".join(self.body_parts).split())
            if text: self.messages.append(ChatMessage(self.direction,html.unescape(text),self.current_date))
            self.message_depth=None; self.body_depth=None
        if self.date_depth == self.depth:
            raw=" ".join(" ".join(self.date_parts).split())
            for fmt in ("%B %d, %Y","%d %B %Y","%d/%m/%Y","%m/%d/%Y"):
                try: self.current_date=datetime.strptime(raw,fmt).date(); break
                except ValueError: pass
            self.date_depth=None
        self.depth -= 1


def _metadata(downloads: Path) -> tuple[dict[str,str],set[str]]:
    phones: dict[str,str]={}; ignored:set[str]=set()
    for path in downloads.glob("*.csv"):
        try:
            with path.open(encoding="utf-8-sig",errors="replace",newline="") as stream:
                for row in csv.DictReader(stream):
                    name=(row.get("Name") or row.get("Saved Name") or row.get("Contact's Public Display Name") or "").strip()
                    phone="".join(re.findall(r"\d",row.get("Phone Number") or ""))
                    kind=(row.get("Business or Personal") or "").lower(); group=(row.get("Group Name") or "").strip()
                    if name and len(phone)>=5: phones[name.casefold()]=phone[-5:]
                    if name and ("group" in kind or (group and group.casefold() not in {"all chats",""})): ignored.add(name.casefold())
        except (OSError,csv.Error): pass
    return phones,ignored


def _phone_only(value: str) -> bool:
    return bool(re.fullmatch(r"[+\d\s().-]+",value.strip()))


def _vehicle(text: str) -> tuple[str,int]:
    year_match=re.search(r"\b(20(?:1[8-9]|2[0-6]))\b",text)
    year=int(year_match.group(1)) if year_match else 0
    for pattern in VEHICLES:
        match=re.search(rf"\b({pattern})\b",text,re.I)
        if match:
            name=re.sub(r"\s+"," ",match.group(1)).strip()
            return name.title().replace("Bmw","BMW").replace("Gmc","GMC").replace("Rav4","RAV4"),year
    for pattern,name in MODEL_ALIASES:
        if re.search(pattern,text,re.I): return name,year
    return "",year


def _amounts(text: str) -> list[float]:
    found=[]
    for match in re.finditer(r"(?i)(?:AED\s*)?(\d{2,3}(?:[,.]\d{3})+|\d+(?:\.\d+)?\s*k)\b",text):
        raw=match.group(1).replace(",","").replace(" ","").lower()
        value=float(raw[:-1])*1000 if raw.endswith("k") else float(raw)
        if 10_000 <= value <= 100_000_000: found.append(value)
    return found


def parse_chat_export(path: Path, phone_lookup: dict[str,str] | None=None, ignored_names: set[str] | None=None) -> ContactImport | None:
    phone_lookup=phone_lookup or {}; ignored_names=ignored_names or set(); raw=b""; chat_name=path.stem
    if path.suffix.lower()==".zip":
        with zipfile.ZipFile(path) as archive:
            members=[n for n in archive.namelist() if n.lower().endswith((".html","_chat.txt"))]
            if not members: return None
            member=members[0]; raw=archive.read(member); chat_name=Path(member).stem
    elif path.suffix.lower()==".html": raw=path.read_bytes()
    else: return None
    chat_name=re.sub(r"\s*\(\d+\)$","",chat_name).strip()
    if "work" in chat_name.casefold() or chat_name.casefold() in ignored_names: return None
    decoded=raw.decode("utf-8",errors="replace"); messages:list[ChatMessage]=[]
    if "<html" in decoded.lower():
        parser=_WhatsAppHTMLParser(); parser.feed(decoded); messages=parser.messages
    else:
        pattern=re.compile(r"\[(\d{1,2}/\d{1,2}/\d{2,4})[^\]]*\]\s*([^:]+):\s*(.*)")
        for line in decoded.splitlines():
            match=pattern.match(line)
            if not match: continue
            try: sent=datetime.strptime(match.group(1),"%d/%m/%Y").date()
            except ValueError:
                try: sent=datetime.strptime(match.group(1),"%d/%m/%y").date()
                except ValueError: sent=date.today()
            messages.append(ChatMessage("out" if "callum" in match.group(2).casefold() else "in",match.group(3),sent))
    if not messages: raise ValueError("No WhatsApp messages found")
    full_text="\n".join(message.text for message in messages); vehicle,model_year=_vehicle(full_text)
    digits="".join(re.findall(r"\d",chat_name)); phone=digits[-5:] if len(digits)>=5 else phone_lookup.get(chat_name.casefold(),"")
    if len(phone)!=5: raise ValueError("phone number was not found in the export or contact lists")
    customer=chat_name
    if not customer or _phone_only(customer) or customer.casefold() in {"unknown","unsaved"}: customer=vehicle or f"WhatsApp seller · {phone}"
    mileage=0
    for match in re.finditer(r"(?i)\b([\d,]{2,})\s*(?:km|kms|kilomet(?:er|re)s?)\b",full_text):
        mileage=max(mileage,int(match.group(1).replace(",","")))
    asking=cash=consignment=0.0
    for message in messages:
        lower=message.text.casefold(); values=_amounts(message.text)
        if not values: continue
        if message.direction=="out" and "consign" in lower: consignment=values[-1]
        elif message.direction=="out" and any(word in lower for word in ("cash","offer","pay")): cash=values[-1]
        elif any(word in lower for word in ("asking","listed","listing","price","want")): asking=values[-1]
    inbound=sum(m.direction=="in" for m in messages); outbound=len(messages)-inbound
    rapport_signal=any(re.search(r"(?i)\b(inspection|come tomorrow|appointment|sounds good|deal|agreed|thank|thanks|perfect|sure)\b",m.text) for m in messages if m.direction=="in")
    rapport="red" if inbound>=2 and outbound>=2 and (rapport_signal or len(messages)>=6) else "green"
    latest=messages[-1]; due=latest.sent_on if latest.direction=="in" else latest.sent_on+timedelta(days=3)
    reason="strong two-way conversation" if rapport=="red" else "normal follow-up"
    last=latest.text[:180]+("…" if len(latest.text)>180 else "")
    note=f"Imported from {path.name}. Rapport set to {rapport}: {reason}. Last WhatsApp message ({latest.direction}): {last}"
    return ContactImport(path,customer,vehicle or "Vehicle not identified",phone,mileage,model_year,asking,cash,consignment,rapport,due.isoformat(),note,hashlib.sha256(raw).hexdigest())


def import_downloaded_contacts(db, downloads: Path) -> ImportResult:
    result=ImportResult(); phones,ignored=_metadata(downloads)
    candidates=sorted({*downloads.glob("*.zip"),*downloads.glob("*.html")})
    for path in candidates:
        try:
            record=parse_chat_export(path,phones,ignored)
            if record is None: continue
            outcome=db.upsert_imported_customer_contact(record.__dict__)
            if outcome=="added": result.added+=1
            elif outcome=="updated": result.updated+=1
            else: result.ignored+=1
            result.processed_files.append(path)
        except (OSError,ValueError,zipfile.BadZipFile) as error:
            # Unrelated ZIPs are not treated as failures.
            if path.suffix.lower()==".html" or "WhatsApp" in str(error) or "phone number" in str(error): result.failed.append(f"{path.name}: {error}")
    return result
