import json
import re
import smtplib
import threading
import time
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

from ripple import checks, inbox, ingest, world
from ripple.graph import connect as graph_of
from ripple.graph import now, read, tenants

TICK_SECONDS = 60
TIMEOUT_SECONDS = 30
MAX_OUTAGES = 10
DEFAULT_CHANNEL = "incidents"
SOURCES = ("slack", "gmail", "vendor_status")
_checking = threading.Lock()


def _file(tenant: str, source: str) -> Path:
    return world.runtime(tenant) / f"{source}.json"


def connection(tenant: str, source: str) -> dict | None:
    return json.loads(_file(tenant, source).read_text()) if _file(tenant, source).exists() else None


def _save(tenant: str, source: str, found: dict) -> None:
    _file(tenant, source).touch(mode=0o600)
    _file(tenant, source).write_text(json.dumps(found, indent=1))


def disconnect(tenant: str, source: str) -> None:
    _file(tenant, source).unlink(missing_ok=True)


def connect(tenant: str, source: str, fields: dict[str, str]) -> dict:
    """Reads the source once and, if that worked, keeps the connection so it goes on being read."""
    with _checking:
        return _check(tenant, source, SETUP[source](tenant, connection(tenant, source) or {}, fields))


def check(tenant: str, source: str) -> dict:
    with _checking:
        found = connection(tenant, source)
        if not found:
            raise ValueError(f"{source} is not connected.")
        try:
            return _check(tenant, source, found)
        except Exception as problem:
            _save(tenant, source, found | {"checked_at": now(), "error": str(problem)})
            raise


def _check(tenant: str, source: str, found: dict) -> dict:
    stats = READ[source](tenant, found)
    _save(tenant, source, found | {"checked_at": now(), "error": ""})
    return stats


def _limit(fields: dict[str, str], kept: dict) -> int:
    return min(inbox.MAX_PULL, max(1, int(fields.get("limit") or kept.get("limit") or 20)))


def _slack_setup(tenant: str, kept: dict, fields: dict[str, str]) -> dict:
    token = fields.get("token", "").strip() or kept.get("token", "")
    channels = inbox.slack_channels(token)
    wanted = fields.get("channel", "").strip().lstrip("#")
    posts_to = next((channel for channel in channels if channel["name"] == (wanted or DEFAULT_CHANNEL)), None)
    if wanted and not posts_to:
        raise ValueError(f"The bot is not in #{wanted}. Invite it there with /invite and connect again.")
    return {"token": token, "limit": _limit(fields, kept), "channels": [channel["name"] for channel in channels], "posts_to": posts_to and {"id": posts_to["id"], "name": posts_to["name"]}}


def _gmail_setup(tenant: str, kept: dict, fields: dict[str, str]) -> dict:
    return {"address": fields.get("address", "").strip() or kept.get("address", ""), "password": fields.get("app_password", "").replace(" ", "") or kept.get("password", ""), "limit": _limit(fields, kept)}


def _status_setup(tenant: str, kept: dict, fields: dict[str, str]) -> dict:
    vendor, url = fields.get("vendor", "").strip(), fields.get("url", "").strip().rstrip("/")
    if world.packaged(tenant):
        raise ValueError("This is the packaged example company. Create your own company to watch a status page.")
    known = [row["id"] for row in read(graph_of(tenant), "MATCH (v:Vendor) RETURN v.id AS id ORDER BY id")]
    if vendor not in known:
        raise ValueError(f"No vendor called {vendor or 'that'} is in the service catalog. Known vendors: {', '.join(known) or 'none yet'}.")
    if not url.startswith("https://"):
        raise ValueError("Give the status page's address, starting with https://.")
    return {"feeds": kept.get("feeds", {}) | {vendor: url}}


def _read_status(tenant: str, found: dict) -> dict:
    folder = world.world_of(tenant)
    file = folder / ingest.EXPORT_FILES["vendor_status"]
    outages = {outage["id"]: outage for outage in (json.loads(file.read_text())["outages"] if file.exists() else [])}
    for vendor, url in found["feeds"].items():
        outages |= {outage["id"]: outage for outage in status_feed(vendor, url)}
    graph = graph_of(tenant)
    stats = ingest.replace_export(graph, folder, "vendor_status", json.dumps({"outages": list(outages.values())}, indent=1))
    checks.upkeep(graph)
    return stats


def status_feed(vendor: str, url: str) -> list[dict]:
    """A Statuspage site's newest incidents, in the vendor status export's shape. An unresolved one has no end."""
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{url}/api/v2/incidents.json", headers={"User-Agent": "ripple"}), timeout=TIMEOUT_SECONDS) as response:
            incidents = json.load(response)["incidents"][:MAX_OUTAGES]
        return [
            {"id": f"OUT-{vendor}-{incident['id']}", "vendor": vendor, "title": incident["name"], "start": _stamp(incident["created_at"]), "end": incident["resolved_at"] and _stamp(incident["resolved_at"])}
            for incident in incidents
        ]
    except (OSError, ValueError, KeyError, TypeError) as problem:
        raise ValueError(f"{url} did not answer as a Statuspage site: {problem}") from problem


def _stamp(moment: str) -> str:
    return ingest._iso(datetime.fromisoformat(moment))


SETUP = {"slack": _slack_setup, "gmail": _gmail_setup, "vendor_status": _status_setup}
READ = {
    "slack": lambda tenant, found: inbox.file(graph_of(tenant), "slack", inbox.pull_slack(found["token"], found["limit"])),
    "gmail": lambda tenant, found: inbox.file(graph_of(tenant), "gmail", inbox.pull_gmail(found["address"], found["password"], found["limit"])),
    "vendor_status": _read_status,
}


def post(tenant: str, text: str) -> str | None:
    """Posts in the Slack channel chosen for incidents and returns its name; None when Slack is not connected to one."""
    found = connection(tenant, "slack")
    if not found or not found["posts_to"]:
        return None
    inbox.slack(found["token"], "chat.postMessage", channel=found["posts_to"]["id"], text=text)
    return f"#{found['posts_to']['name']}"


def _customer_address(mailbox: str, customer: str) -> str:
    name, _, domain = mailbox.partition("@")
    return f"{name}+{re.sub(r'[^\w.-]', '', customer)}@{domain}"


def mail(tenant: str, customer: str, subject: str, body: str) -> str | None:
    """Emails a notice from the connected mailbox and returns where it went; None when Gmail is not connected."""
    found = connection(tenant, "gmail")
    if not found:
        return None
    # ponytail: the CRM export has no contact address, so a notice goes to the mailbox itself, tagged with the customer
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = found["address"], _customer_address(found["address"], customer), subject
    message.set_content(body)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", timeout=TIMEOUT_SECONDS) as server:
            server.login(found["address"], found["password"])
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as problem:
        raise ValueError(f"Gmail did not send the notice: {problem}") from problem
    return message["To"]


def state(tenant: str) -> dict[str, dict]:
    """Each kept connection without its secret: what is being read, where approved messages go, and the last check."""
    return {source: _described(source, found) | {"checked_at": found.get("checked_at"), "error": found.get("error", ""), "every_seconds": TICK_SECONDS} for source in SOURCES if (found := connection(tenant, source))}


def _described(source: str, found: dict) -> dict:
    if source == "slack":
        sends = f"Approved pages and status updates are posted in #{found['posts_to']['name']}." if found["posts_to"] else f"Nothing is posted yet: invite the bot to #{DEFAULT_CHANNEL}, or name another channel, and connect again."
        return {"watching": ", ".join(f"#{channel}" for channel in found["channels"]), "sends": sends}
    if source == "gmail":
        example = _customer_address(found["address"], "customer")
        return {"watching": found["address"], "sends": f"The CRM export has no contact addresses, so approved customer notices are sent to this mailbox itself, addressed like {example}."}
    return {"watching": ", ".join(f"{vendor} at {urlsplit(url).hostname}" for vendor, url in found["feeds"].items()), "sends": ""}


def loop() -> None:
    while True:
        for file in world.HOME.glob("*/*.json"):
            if file.stem in SOURCES and file.parent.name in tenants():
                try:
                    check(file.parent.name, file.stem)
                except Exception:
                    pass
        time.sleep(TICK_SECONDS)
