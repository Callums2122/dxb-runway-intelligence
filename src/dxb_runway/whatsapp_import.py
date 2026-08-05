from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


CHAT_FILE_PREFIX = "WhatsApp Chat - "
CHAT_LINE = re.compile(
    r"^\[(?P<date>\d{1,2}/\d{1,2}/\d{4}),\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*(?P<ampm>[ap]m)?\]\s+"
    r"(?P<sender>[^:]+):\s?(?P<body>.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WhatsAppMessage:
    sent_at: datetime
    sender: str
    body: str

    @property
    def fingerprint(self) -> str:
        raw = f"{self.sent_at.isoformat()}\n{self.sender}\n{self.body}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class WhatsAppChat:
    file_name: str
    chat_name: str
    file_hash: str
    messages: tuple[WhatsAppMessage, ...]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def chat_name_from_filename(path: Path) -> str:
    name = Path(path).stem
    if CHAT_FILE_PREFIX in name:
        name = name.split(CHAT_FILE_PREFIX,1)[1]
    return re.sub(r"\s+\(\d+\)$", "", name).strip() or "Unknown WhatsApp contact"


def _normalise_export_text(value: str) -> str:
    return value.replace("\u202f", " ").replace("\u00a0", " ").replace("\ufeff", "")


def _parse_timestamp(date_text: str, time_text: str, ampm: str | None) -> datetime:
    cleaned = f"{date_text} {time_text}"
    if ampm:
        return datetime.strptime(f"{cleaned} {ampm.upper()}", "%d/%m/%Y %I:%M:%S %p" if time_text.count(":") == 2 else "%d/%m/%Y %I:%M %p")
    return datetime.strptime(cleaned, "%d/%m/%Y %H:%M:%S" if time_text.count(":") == 2 else "%d/%m/%Y %H:%M")


def parse_chat_text(text: str) -> tuple[WhatsAppMessage, ...]:
    messages: list[WhatsAppMessage] = []
    for raw_line in _normalise_export_text(text).splitlines():
        match = CHAT_LINE.match(raw_line)
        if match:
            body = match.group("body").strip()
            if "end-to-end encrypted" in body.lower():
                continue
            messages.append(
                WhatsAppMessage(
                    sent_at=_parse_timestamp(match.group("date"), match.group("time"), match.group("ampm")),
                    sender=match.group("sender").strip(),
                    body=body,
                )
            )
        elif messages and raw_line.strip():
            previous = messages[-1]
            messages[-1] = WhatsAppMessage(previous.sent_at, previous.sender, f"{previous.body}\n{raw_line.strip()}")
    return tuple(messages)


def parse_whatsapp_zip(path: Path) -> WhatsAppChat:
    source = Path(path)
    if not zipfile.is_zipfile(source):
        raise ValueError("This is not a valid WhatsApp ZIP export")
    with zipfile.ZipFile(source) as archive:
        text_names = [name for name in archive.namelist() if name.lower().endswith(".txt") and not name.startswith("__MACOSX/")]
        if not text_names:
            raise ValueError("The ZIP does not contain a WhatsApp chat text file")
        text = archive.read(text_names[0]).decode("utf-8-sig", errors="replace")
    messages = parse_chat_text(text)
    if not messages:
        raise ValueError("No WhatsApp messages could be read from this export")
    return WhatsAppChat(source.name, chat_name_from_filename(source), file_sha256(source), messages)


def route_download_exports(downloads: Path, inbox: Path) -> list[Path]:
    """Copy completed WhatsApp ZIP exports into Runway's inbox without touching originals."""
    source_dir, destination_dir = Path(downloads), Path(inbox)
    destination_dir.mkdir(parents=True, exist_ok=True)
    routed: list[Path] = []
    if not source_dir.exists():
        return routed
    for source in sorted(source_dir.glob(f"{CHAT_FILE_PREFIX}*.zip"), key=lambda item: item.stat().st_mtime):
        digest = file_sha256(source)
        destination = destination_dir / f"{digest[:12]}-{source.name}"
        if destination.exists():
            continue
        temporary = destination.with_suffix(destination.suffix + ".copying")
        shutil.copy2(source, temporary)
        temporary.replace(destination)
        routed.append(destination)
    return routed


def next_best_action(messages: tuple[WhatsAppMessage, ...], own_names: set[str]) -> tuple[str, str]:
    own = {name.casefold().strip() for name in own_names if name.strip()}
    last = messages[-1]
    inbound = last.sender.casefold().strip() not in own
    body = last.body.casefold()
    if inbound:
        if any(term in body for term in ("too low", "lowball", "not interested", "no thanks", "firm", "best price")):
            return "Objection", "Acknowledge their position, ask what figure they need, then offer an inspection before committing to a final number."
        if any(term in body for term in ("sold", "no longer available", "already sold")):
            return "Verify outcome", "Confirm whether it sold to another buyer, then close the lead so it leaves your follow-up queue."
        if any(term in body for term in ("yes", "available", "still have")):
            return "Qualify", "Reply now: thank them, ask whether the price is flexible and check for accidents or paintwork before offering."
        return "Reply now", "Respond while the conversation is warm: acknowledge their message and ask one clear qualifying question."
    return "Awaiting reply", "Give them room to respond. If there is no reply, use a friendly follow-up when the three-day timer becomes due."
