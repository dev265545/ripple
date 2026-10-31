import email
import hashlib
import imaplib
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from email import policy
from email.utils import getaddresses, parsedate_to_datetime
from html import unescape
from pathlib import PurePath
from xml.etree import ElementTree

from falkordb import Graph

from ripple import access, checks, ingest, model
from ripple.graph import apply_schema, now, read, write

# Mail and personal chats are readable only by the people on them until one of them shares; channels and files are for everyone.
PRIVATE = {"gmail", "whatsapp"}
SOURCES = {"gmail": "Gmail", "drive": "Google Drive and Word", "slack": "Slack", "whatsapp": "WhatsApp"}
EXAMPLES = {"gmail": "bluepeak-thread.mbox", "drive": "Kite Grocers quarterly review.docx", "slack": "slack-export.zip", "whatsapp": "WhatsApp Chat with Larkspur weekend sale.txt"}
MAX_FILE = 10_000_000
MAX_TEXT = 20_000
MAX_ITEMS = 200
MAX_PULL = 50
TIMEOUT_SECONDS = 30
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
GOOGLE_FILE = re.compile(r"docs\.google\.com/(document|spreadsheets|presentation)/d/([\w-]+)")
GOOGLE_EXPORT = {"document": "txt", "spreadsheets": "csv", "presentation": "txt"}
MBOX_START = re.compile(rb"^From \S+ .*\n", re.M)
WHATSAPP_LINE = re.compile(r"^\u200e?\[?(\d{1,2})[/.](\d{1,2})[/.](\d{2,4}),? (\d{1,2}):(\d{2})(?::\d{2})?[\s\u202f]?([APap])?\.?[Mm]?\.?\]?(?: -)? ([^:]{1,60}): (.*)$")

Who = tuple[str, str]


@dataclass
class Item:
    """One thing read from an inbox: an email, a file, or a day of one chat."""

    key: str
    kind: str
    title: str
    text: str
    at: str | None = None
    sender: Who | None = None
    others: list[Who] = field(default_factory=list)
    channel: str | None = None
    reply_to: str | None = None
    uri: str = ""


def read_file(source: str, name: str, raw: bytes) -> list[Item]:
    if not raw or len(raw) > MAX_FILE:
        raise ValueError(f"The file must be non-empty and under {MAX_FILE // 1_000_000} MB.")
    suffix = PurePath(name).suffix.lower()
    readers = {
        ("gmail", ".eml"): lambda: [read_email(raw)],
        ("gmail", ".mbox"): lambda: [read_email(part) for part in MBOX_START.split(raw) if part.strip()],
        ("drive", ".docx"): lambda: [_document(name, read_docx(raw))],
        ("drive", ".txt"): lambda: [_document(name, _decode(raw))],
        ("drive", ".md"): lambda: [_document(name, _decode(raw))],
        ("drive", ".csv"): lambda: [_document(name, _decode(raw))],
        ("slack", ".zip"): lambda: read_slack_export(raw),
        ("whatsapp", ".txt"): lambda: read_whatsapp(name, _decode(raw)),
        ("whatsapp", ".zip"): lambda: read_whatsapp(name, _decode(_only_text_file(raw))),
    }
    if (source, suffix) not in readers:
        accepted = ", ".join(kind for known, kind in readers if known == source)
        raise ValueError(f"{SOURCES[source]} reads {accepted} files, not {suffix or 'files without an extension'}.")
    try:
        return readers[source, suffix]()
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, json.JSONDecodeError) as problem:
        raise ValueError(f"Could not read {name} as a {SOURCES[source]} {suffix} file: {problem}") from problem


def pull(source: str, fields: dict[str, str]) -> list[Item]:
    limit = min(MAX_PULL, max(1, int(fields.get("limit") or 20)))
    if source == "gmail":
        return pull_gmail(fields.get("address", "").strip(), fields.get("app_password", "").replace(" ", ""), limit)
    if source == "slack":
        return pull_slack(fields.get("token", "").strip(), limit)
    if source == "drive":
        return [pull_google_file(fields.get("url", "").strip())]
    raise ValueError(f"{SOURCES[source]} is read from an exported file.")


def read_email(raw: bytes) -> Item:
    message = email.message_from_bytes(raw, policy=policy.default)
    part = message.get_body(preferencelist=("plain", "html"))
    try:
        body = part.get_content() if part else ""
    except (LookupError, UnicodeError):
        body = (part.get_payload(decode=True) or b"").decode(errors="replace")
    if part and part.get_content_type() == "text/html":
        body = _plain(body)
    key = _slug(str(message["Message-ID"] or hashlib.sha1(raw).hexdigest()))
    senders = [(f"email:{address.lower()}", name) for name, address in getaddresses([str(message["From"] or "")]) if "@" in address]
    return Item(
        key, "Email", str(message["Subject"] or "(no subject)"), body.strip()[:MAX_TEXT], _email_time(message), senders[0] if senders else None,
        [(f"email:{address.lower()}", name) for name, address in getaddresses([str(message[header] or "") for header in ("To", "Cc")]) if "@" in address],
        reply_to=_slug(str(message["In-Reply-To"])) if message["In-Reply-To"] else None, uri=f"message {key}",
    )


def pull_gmail(address: str, password: str, limit: int) -> list[Item]:
    if "@" not in address or not password:
        raise ValueError("Give the mailbox address and an app password.")
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com", timeout=TIMEOUT_SECONDS) as box:
            box.login(address, password)
            box.select("INBOX", readonly=True)
            newest = box.search(None, "ALL")[1][0].split()[-limit:]
            return [read_email(box.fetch(number, "(RFC822)")[1][0][1]) for number in newest]
    except (imaplib.IMAP4.error, OSError) as problem:
        detail = problem.args[0].decode(errors="replace") if problem.args and isinstance(problem.args[0], bytes) else str(problem)
        raise ValueError(f"Gmail did not let Ripple read {address}: {detail}") from problem


def read_docx(raw: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if archive.getinfo("word/document.xml").file_size > MAX_FILE:
            raise ValueError("The document is too large to read.")
        body = ElementTree.fromstring(archive.read("word/document.xml"))
    return "\n".join("".join(run.text or "" for run in paragraph.iter(f"{WORD}t")) for paragraph in body.iter(f"{WORD}p"))


def pull_google_file(url: str) -> Item:
    found = GOOGLE_FILE.search(url)
    if not found:
        raise ValueError("Paste a link to a Google Doc, Sheet or Slides file.")
    kind, id = found.groups()
    try:
        with urllib.request.urlopen(f"https://docs.google.com/{kind}/d/{id}/export?format={GOOGLE_EXPORT[kind]}", timeout=TIMEOUT_SECONDS) as response:
            shared = response.headers.get_content_type() != "text/html"
            name = response.headers.get_filename() or id
            text = response.read(MAX_FILE).decode("utf-8-sig", errors="replace")
    except OSError as problem:
        raise ValueError(f"Google did not return that file: {problem}") from problem
    if not shared:
        raise ValueError("That file is not shared as 'Anyone with the link', so Ripple cannot read it.")
    item = _document(name, text)
    item.key, item.uri = f"google-{id}", f"https://docs.google.com/{kind}/d/{id}"
    return item


def read_slack_export(raw: bytes) -> list[Item]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        users = _slack_users(json.loads(archive.read("users.json")))
        days = [name for name in archive.namelist() if re.fullmatch(r"[^/]+/\d{4}-\d{2}-\d{2}\.json", name)]
        return [item for name in sorted(days) for item in _slack_days(name.split("/")[0], json.loads(archive.read(name)), users)]


def pull_slack(token: str, limit: int) -> list[Item]:
    users = _slack_users(slack(token, "users.list")["members"])
    return [item for channel in slack_channels(token) for item in _slack_days(channel["name"], slack(token, "conversations.history", channel=channel["id"], limit=str(limit))["messages"], users)]


def slack_channels(token: str) -> list[dict]:
    if not token.startswith("xox"):
        raise ValueError("Give a Slack bot token; it starts with xoxb-.")
    channels = [channel for channel in slack(token, "conversations.list", types="public_channel,private_channel", limit="200")["channels"] if channel.get("is_member")]
    if not channels:
        raise ValueError("The bot is not in any channel yet. Invite it to one with /invite and read again.")
    return channels


def slack(token: str, method: str, **params: str) -> dict:
    request = urllib.request.Request(f"https://slack.com/api/{method}", data=urllib.parse.urlencode(params).encode(), headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            reply = json.load(response)
    except (OSError, ValueError) as problem:
        raise ValueError(f"Slack could not be reached: {problem}") from problem
    if not reply.get("ok"):
        raise ValueError(f"Slack refused {method}: {reply.get('error', 'unknown error')}")
    return reply


def _slack_users(members: list[dict]) -> dict[str, Who]:
    def who(member: dict) -> Who:
        name = member.get("real_name") or member.get("profile", {}).get("real_name") or member.get("name") or member["id"]
        address = member.get("profile", {}).get("email")
        return (f"email:{address.lower()}" if address else f"name:{name}", name)

    return {member["id"]: who(member) for member in members}


def _slack_days(channel: str, messages: list[dict], users: dict[str, Who]) -> list[Item]:
    said = [
        (datetime.fromtimestamp(float(message["ts"]), UTC), users.get(message["user"], (f"slack:{message['user']}", message["user"])), re.sub(r"<@(\w+)>", lambda tag: "@" + users.get(tag[1], ("", tag[1]))[1], unescape(message["text"])))
        for message in messages
        if message.get("user") and message.get("text") and not message.get("subtype") and not message.get("bot_id")
    ]
    return _conversations("slack", f"#{channel}", sorted(said, key=lambda line: line[0]))


def read_whatsapp(name: str, text: str) -> list[Item]:
    lines = []
    for line in text.splitlines():
        if found := WHATSAPP_LINE.match(line):
            lines.append([*found.groups()])
        elif lines and line.strip():
            lines[-1][-1] += f" {line.strip()}"
    if not lines:
        raise ValueError("No messages found. Export the chat from WhatsApp with 'Export chat', without media.")
    # ponytail: 03/04 is read as 3 April unless some line in the file proves month-first; a locale picker would settle it
    month_first = any(int(line[1]) > 12 for line in lines) and not any(int(line[0]) > 12 for line in lines)
    said = []
    for first, second, year, hour, minute, half, speaker, message in lines:
        day, month = (second, first) if month_first else (first, second)
        clock = int(hour) % 12 + (12 if half.lower() == "p" else 0) if half else int(hour)
        said.append((datetime(int(year) + (2000 if len(year) == 2 else 0), int(month), int(day), clock, int(minute), tzinfo=UTC), (f"name:{speaker.strip()}", speaker.strip()), message))
    chat = re.sub(r"^(WhatsApp Chat (with|-) |_chat$)", "", PurePath(name).stem).strip() or "WhatsApp chat"
    return _conversations("whatsapp", chat, said)


def _conversations(system: str, channel: str, said: list[tuple[datetime, Who, str]]) -> list[Item]:
    """A chat becomes one conversation per day, so a long history is a few records and a few model reads, not thousands."""
    days: dict[str, list[tuple[datetime, Who, str]]] = {}
    for line in said:
        days.setdefault(line[0].strftime("%Y-%m-%d"), []).append(line)
    return [
        Item(
            _slug(f"{channel}-{day}"), "Conversation", f"{channel} on {day}", "\n".join(f"{moment:%H:%M} {who[1]}: {text}" for moment, who, text in lines)[:MAX_TEXT],
            lines[0][0].strftime("%Y-%m-%dT%H:%M:%SZ"), None, list(dict.fromkeys(who for _, who, _ in lines)), f"{system}:{channel}", uri=f"{channel}, {day}",
        )
        for day, lines in days.items()
    ]


def _document(name: str, text: str) -> Item:
    if not text.strip():
        raise ValueError(f"{name} has no text in it.")
    return Item(_slug(PurePath(name).stem), "Doc", PurePath(name).stem, text.strip()[:MAX_TEXT], uri=name)


def _only_text_file(raw: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        name = next(name for name in archive.namelist() if name.endswith(".txt"))
        if archive.getinfo(name).file_size > MAX_FILE:
            raise ValueError("The chat is too large to read.")
        return archive.read(name)


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8-sig", errors="replace")


def _plain(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", html)))


def _slug(text: str) -> str:
    return re.sub(r"[^\w.@-]+", "-", text.strip("<> \n")).strip("-")[:120]


def _email_time(message) -> str | None:
    try:
        return ingest._iso(parsedate_to_datetime(str(message["Date"])))
    except (TypeError, ValueError):
        return None


def file(graph: Graph, source: str, items: list[Item]) -> dict:
    """Stores what was read: who said it, what it names, who may read it, and, with a model, the promises in it and a note."""
    apply_schema(graph)
    write(graph, "MERGE (s:Source {id: $id}) SET s.name = $name", id=source, name=SOURCES[source])
    stats = {"records": 0, "changed": 0, "linked": 0, "promises": 0, "decisions": 0, "notes": 0, "skipped": max(0, len(items) - MAX_ITEMS)}
    for item in items[:MAX_ITEMS]:
        record = ingest.Record(item.key, item.uri or item.key, json.dumps(asdict(item), sort_keys=True), item.text)
        stats["records"] += 1
        if not ingest.unchanged(graph, source, record):
            found = _connect(graph, source, item, record)
            ingest.store(graph, source, record)
            stats = {name: count + found.get(name, 0) for name, count in stats.items()} | {"changed": stats["changed"] + 1}
        if source in PRIVATE:
            known = [_known(graph, who) for who in [item.sender, *item.others] if who]
            access.restrict(graph, f"{source}:{item.key}", [ref[1] for ref in known if ref and ref[0] == "Person"])
    write(graph, "MATCH (s:Source {id: $id}) SET s.last_sync = $at", id=source, at=now())
    checks.upkeep(graph)
    return stats | {"model": model.name()}


def _connect(graph: Graph, source: str, item: Item, record: ingest.Record) -> dict:
    id = f"{source}-{item.key}"
    at = item.at or now()
    props = {
        "Email": {"subject": item.title, "sent_at": at, "body": item.text},
        "Doc": {"title": item.title, "type": SOURCES[source], "text": item.text},
        "Conversation": {"title": item.title, "started_at": at, "text": item.text},
    }[item.kind]
    origin = record.node(item.kind, id, **props)
    parties = [_who(graph, record, who) for who in item.others]
    if item.sender:
        sender = _who(graph, record, item.sender)
        record.edge(sender, "SENT", origin)
        for party in parties:
            record.edge(origin, "SENT_TO", party)
        parties.append(sender)
    else:
        for party in parties:
            record.edge(party, "TOOK_PART_IN", origin)
    if item.channel:
        record.edge(origin, "POSTED_IN", record.node("Channel", item.channel, name=item.channel.split(":", 1)[1]))
    if item.reply_to and read(graph, "MATCH (e:Email {id: $id}) RETURN e.id", id=f"{source}-{item.reply_to}"):
        record.edge(origin, "REPLIES_TO", ("Email", f"{source}-{item.reply_to}"))
    named = ingest.named_entities(graph, f"{item.title}\n{item.text}")
    for entity in named:
        record.edge(origin, "MENTIONS", (entity["kind"], entity["id"]), quote=entity["quote"] if entity["quote"] in item.text else None)
    about = list(dict.fromkeys([(entity["kind"], entity["id"]) for entity in named] + [party for party in parties if party[0] == "Customer"]))
    # ponytail: the model only reads items tied to something known, to stay inside free-tier quota; it is never retried for an unchanged item
    reading = ingest.understand(graph, item.text, f"COM-{id}") if about and model.settings() else {"promises": [], "decisions": [], "note": None}
    promises, note = reading["promises"], reading["note"]
    for promise in promises:
        commitment = record.node("Commitment", promise["id"], promise["quote"], inferred=True, text=promise["text"], made_at=at, **({"valid_to": promise["valid_to"]} if promise["valid_to"] else {}))
        record.edge(("Person", promise["made_by"]), "MADE", commitment, inferred=True)
        record.edge(commitment, "MADE_TO", ("Customer", promise["customer"]), inferred=True)
        if promise["replaces"]:
            record.edge(commitment, "SUPERSEDES", ("Commitment", promise["replaces"]), inferred=True, proposed=True, proposed_at=at)
    for choice in reading["decisions"]:
        decision = record.node("Decision", choice["id"], choice["quote"], inferred=True, title=choice["text"], status="accepted", decided_at=at, decided_in=item.kind)
        record.edge(("Person", choice["decided_by"]), "DECIDED", decision, inferred=True)
        for entity in ingest.named_entities(graph, choice["quote"]):
            if entity["kind"] == "Service":
                record.edge(decision, "GOVERNS", ("Service", entity["id"]), inferred=True)
        if choice["replaces"]:
            record.edge(decision, "SUPERSEDES", ("Decision", choice["replaces"]), inferred=True, proposed=True, proposed_at=at)
    if note:
        written = record.node("Note", f"NOTE-{id}", inferred=True, text=note, written_by=model.name(), written_at=at)
        record.edge(origin, "HAS_NOTE", written)
        for ref in about:
            record.edge(written, "ABOUT", ref)
    return {"linked": len(named), "promises": len(promises), "decisions": len(reading["decisions"]), "notes": int(bool(note))}


def _who(graph: Graph, record: ingest.Record, who: Who) -> ingest.Ref:
    """A known person by address or name, else the customer that owns the address's domain, else a new outside contact."""
    identity, name = who
    return _known(graph, who) or record.node("Contact", identity, name=name or identity.split(":", 1)[1])


def _known(graph: Graph, who: Who) -> ingest.Ref | None:
    identity, name = who
    for candidate in dict.fromkeys([identity, f"name:{name}"]):
        found = ingest._resolve(graph, "Person", candidate)
        if found[1] != candidate:
            return found
    if identity.startswith("email:"):
        customer = ingest._resolve(graph, "Customer", f"domain:{identity.split('@')[1]}")
        if customer[0] == "Customer" and not customer[1].startswith("domain:"):
            return customer
    return None
