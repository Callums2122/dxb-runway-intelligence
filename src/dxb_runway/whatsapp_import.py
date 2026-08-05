from __future__ import annotations

import csv
import hashlib
import io
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path


CHAT_FILE_PREFIX = "WhatsApp Chat - "
CHAT_LINE = re.compile(
    r"^\[(?P<date>\d{1,2}/\d{1,2}/\d{4}),\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*(?P<ampm>[ap]m)?\]\s+"
    r"(?P<sender>[^:]+):\s?(?P<body>.*)$",
    re.IGNORECASE,
)
HTML_DATE_FORMATS = ("%B %d, %Y", "%d %B %Y")
HTML_TIME = re.compile(r"^\d{1,2}:\d{2}\s*[AP]M$", re.IGNORECASE)
OWN_EXPORT_NAME = "Callum Steen - ALBA CARS"


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


class _WhatsAppHTMLParser(HTMLParser):
    """Read the small, self-contained HTML files produced by WAnalysis exports."""

    def __init__(self, chat_name: str):
        super().__init__(convert_charrefs=True)
        self.chat_name = chat_name
        self.depth = 0
        self.date_depth: int | None = None
        self.message_depth: int | None = None
        self.date_text: list[str] = []
        self.message_text: list[str] = []
        self.message_direction = ""
        self.current_date: datetime | None = None
        self.messages: list[WhatsAppMessage] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            return
        self.depth += 1
        classes = set(dict(attrs).get("class", "").split())
        if tag == "div" and "__date" in classes and self.date_depth is None:
            self.date_depth = self.depth
            self.date_text = []
        if tag == "div" and self.message_depth is None and ({"__message-in", "__message-out"} & classes):
            self.message_depth = self.depth
            self.message_direction = "outbound" if "__message-out" in classes else "inbound"
            self.message_text = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())
        if not clean:
            return
        if self.date_depth is not None:
            self.date_text.append(clean)
        if self.message_depth is not None:
            self.message_text.append(clean)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.message_depth == self.depth:
            self._finish_message()
            self.message_depth = None
        if tag == "div" and self.date_depth == self.depth:
            self._finish_date()
            self.date_depth = None
        self.depth = max(0, self.depth - 1)

    def _finish_date(self) -> None:
        candidate = " ".join(self.date_text).strip()
        for date_format in HTML_DATE_FORMATS:
            try:
                self.current_date = datetime.strptime(candidate, date_format)
                return
            except ValueError:
                continue

    def _finish_message(self) -> None:
        if self.current_date is None or not self.message_text:
            return
        time_index = next((index for index in range(len(self.message_text) - 1, -1, -1) if HTML_TIME.match(self.message_text[index])), None)
        if time_index is None:
            return
        time_text = self.message_text[time_index].upper().replace(" ", "")
        body_parts = self.message_text[:time_index]
        if not body_parts:
            body_parts = ["[Attachment]"]
        body = "\n".join(body_parts).strip()
        sent_at = datetime.strptime(f"{self.current_date:%Y-%m-%d} {time_text}", "%Y-%m-%d %I:%M%p")
        sender = OWN_EXPORT_NAME if self.message_direction == "outbound" else self.chat_name
        self.messages.append(WhatsAppMessage(sent_at, sender, body))


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


def _archive_chat_name(source: Path, archive: zipfile.ZipFile) -> str:
    html_names = [name for name in archive.namelist() if name.lower().endswith(".html") and not name.startswith("__MACOSX/")]
    if html_names:
        return chat_name_from_filename(Path(html_names[0]).name)
    return chat_name_from_filename(source)


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


def parse_chat_html(text: str, chat_name: str) -> tuple[WhatsAppMessage, ...]:
    parser = _WhatsAppHTMLParser(chat_name)
    parser.feed(text)
    parser.close()
    return tuple(parser.messages)


def parse_whatsapp_zip(path: Path) -> WhatsAppChat:
    source = Path(path)
    if not zipfile.is_zipfile(source):
        raise ValueError("This is not a valid WhatsApp ZIP export")
    with zipfile.ZipFile(source) as archive:
        text_names = [name for name in archive.namelist() if name.lower().endswith(".txt") and not name.startswith("__MACOSX/")]
        html_names = [name for name in archive.namelist() if name.lower().endswith(".html") and not name.startswith("__MACOSX/")]
        chat_name = _archive_chat_name(source, archive)
        if text_names:
            text = archive.read(text_names[0]).decode("utf-8-sig", errors="replace")
            messages = parse_chat_text(text)
        elif html_names:
            text = archive.read(html_names[0]).decode("utf-8-sig", errors="replace")
            messages = parse_chat_html(text, chat_name)
        else:
            raise ValueError("The ZIP does not contain a supported WhatsApp HTML or text chat file")
    if not messages:
        raise ValueError("No WhatsApp messages could be read from this export")
    if should_ignore_chat(chat_name):
        raise ValueError("This contact is ignored because its name contains ‘work’")
    return WhatsAppChat(source.name, chat_name, file_sha256(source), messages)


def _normalise_chat_name(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def ignored_chat_names(downloads: Path) -> set[str]:
    """Use the exporter's contact index to identify groups and named work contacts."""
    ignored: set[str] = set()
    for source in Path(downloads).glob("*.csv"):
        try:
            text = source.read_text(encoding="utf-8-sig", errors="replace")
            rows = csv.DictReader(io.StringIO(text))
            for row in rows:
                name = (row.get("Name") or row.get("Saved Name") or row.get("Contact's Public Display Name") or "").strip()
                phone = (row.get("Phone Number") or "").strip()
                kind = (row.get("Business or Personal") or "").strip().casefold()
                if name and ("work" in name.casefold() or kind == "group" or "-" in phone):
                    ignored.add(_normalise_chat_name(name))
        except (OSError, csv.Error):
            continue
    return ignored


def should_ignore_chat(chat_name: str, metadata_ignored: set[str] | None = None) -> bool:
    normalised = _normalise_chat_name(chat_name)
    return "work" in normalised or normalised in (metadata_ignored or set())


def _supported_archive_chat_name(source: Path) -> str | None:
    if not zipfile.is_zipfile(source):
        return None
    try:
        with zipfile.ZipFile(source) as archive:
            names = [name for name in archive.namelist() if not name.startswith("__MACOSX/")]
            text_names = [name for name in names if name.lower().endswith(".txt")]
            html_names = [name for name in names if name.lower().endswith(".html")]
            if text_names:
                sample = archive.read(text_names[0])[:16_384].decode("utf-8-sig", errors="replace")
                if not any(CHAT_LINE.match(line) for line in _normalise_export_text(sample).splitlines()):
                    return None
            elif html_names:
                sample = archive.read(html_names[0])[:64_000].decode("utf-8-sig", errors="replace")
                if "__message-in" not in sample and "__message-out" not in sample:
                    return None
            else:
                return None
            return _archive_chat_name(source, archive)
    except (OSError, zipfile.BadZipFile, KeyError):
        return None


def route_download_exports(downloads: Path, inbox: Path) -> list[Path]:
    """Copy recognised chat ZIPs regardless of filename; quarantine work contacts and groups."""
    source_dir, destination_dir = Path(downloads), Path(inbox)
    destination_dir.mkdir(parents=True, exist_ok=True)
    ignored_dir = destination_dir / "ignored"
    metadata_ignored = ignored_chat_names(source_dir)
    routed: list[Path] = []
    if not source_dir.exists():
        return routed
    for source in sorted(source_dir.glob("*.zip"), key=lambda item: item.stat().st_mtime):
        chat_name = _supported_archive_chat_name(source)
        if chat_name is None:
            continue
        target_dir = ignored_dir if should_ignore_chat(chat_name, metadata_ignored) else destination_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        digest = file_sha256(source)
        destination = target_dir / f"{digest[:12]}-{source.name}"
        if destination.exists():
            continue
        temporary = destination.with_suffix(destination.suffix + ".copying")
        shutil.copy2(source, temporary)
        temporary.replace(destination)
        routed.append(destination)
    return routed


def copied_download_exports(downloads: Path, inbox: Path) -> list[Path]:
    """Return only source exports whose byte-identical routed copy is present."""
    source_dir, destination_dir = Path(downloads), Path(inbox)
    copied: list[Path] = []
    if not source_dir.exists():
        return copied
    for source in sorted(source_dir.glob("*.zip"), key=lambda item: item.name.casefold()):
        if _supported_archive_chat_name(source) is None:
            continue
        digest = file_sha256(source)
        name = f"{digest[:12]}-{source.name}"
        if (destination_dir / name).exists() or (destination_dir / "ignored" / name).exists():
            copied.append(source)
    return copied


def delete_copied_download_exports(downloads: Path, inbox: Path) -> list[Path]:
    """Delete exports only after an exact copy has been confirmed in Runway storage."""
    deleted: list[Path] = []
    for source in copied_download_exports(downloads, inbox):
        source.unlink()
        deleted.append(source)
    return deleted


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
