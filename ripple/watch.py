import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path

from ripple import checks, github, ingest, world
from ripple.graph import connect as graph_of
from ripple.graph import now, read, tenants

TICK_SECONDS = 60
# GitHub allows 60 unauthenticated requests an hour and each check costs at least two
TOKENLESS_SECONDS = 300
Start = Callable[[str, dict], dict]
_syncing = threading.Lock()


def _file(tenant: str) -> Path:
    return world.runtime(tenant) / "github.json"


def connection(tenant: str) -> dict | None:
    return json.loads(_file(tenant).read_text()) if _file(tenant).exists() else None


def _save(tenant: str, found: dict) -> None:
    _file(tenant).touch(mode=0o600)
    _file(tenant).write_text(json.dumps(found, indent=1))


def connect(tenant: str, repo: str, token: str, limit: int, start: Start) -> dict:
    """Reads the repository once and, if that worked, keeps the connection so it goes on being watched."""
    if world.packaged(tenant):
        raise ValueError("This is the packaged example company. Create your own company to connect a repository.")
    kept = connection(tenant) or {}
    found = {"repo": "/".join(github.split(repo)), "token": token or kept.get("token", ""), "limit": limit, "secret": kept.get("secret") or secrets.token_hex(20), "since": kept.get("since") or now()}
    with _syncing:
        return _sync(tenant, found, start)


def disconnect(tenant: str) -> None:
    _file(tenant).unlink(missing_ok=True)


def sync(tenant: str, start: Start) -> dict:
    with _syncing:
        found = connection(tenant)
        if not found:
            raise ValueError("No repository is connected.")
        try:
            return _sync(tenant, found, start)
        except Exception as problem:
            _save(tenant, found | {"checked_at": now(), "polled": time.time(), "error": str(problem)})
            raise


def _export(folder: Path, name: str) -> list[dict]:
    file = folder / ingest.EXPORT_FILES[name]
    return json.loads(file.read_text()) if file.exists() else []


def _sync(tenant: str, found: dict, start: Start) -> dict:
    graph, folder, service = graph_of(tenant), world.world_of(tenant), found["repo"].split("/")[1]
    known = _export(folder, "git")
    fresh = github.changes(found["repo"], found["token"], found["limit"], frozenset(change["number"] for change in known))
    stats = {"records": len(known), "changed": 0}
    if fresh:
        stats = ingest.replace_export(graph, folder, "git", json.dumps(known + fresh, indent=1))
        # ponytail: a merge is counted as a production deploy; read the real deploy log when one is connected
        shipped = [{"id": f"DEP-{change['number']}", "at": change["merged_at"], "env": "production", "status": "succeeded", "pr": change["number"], "service": service} for change in fresh]
        ingest.replace_export(graph, folder, "deploys", json.dumps(_export(folder, "deploys") + shipped, indent=1))
        checks.upkeep(graph)
    reported = sorted(github.issues(found["repo"], found["token"], found["since"]), key=lambda issue: issue["created_at"])
    if reported and not read(graph, "MATCH (s:Service {id: $id}) RETURN s.id AS id", id=service):
        raise ValueError(f"{found['repo']} has an incident issue but no changes to investigate yet.")
    # the investigation drafts replies and reverts through this connection, so it has to be on disk first
    _save(tenant, found)
    opened = [
        start(tenant, {
            "service": service, "symptom": next((label["name"] for label in issue["labels"] if label["name"] != github.INCIDENT_LABEL), "reported_issue"),
            "severity": "warning", "summary": f"#{issue['number']} {issue['title']}", "at": issue["created_at"], "origin": f"{found['repo']}#{issue['number']}",
        })
        for issue in reported
    ]
    _save(tenant, found | {"since": max([found["since"], *[issue["created_at"] for issue in reported]]), "checked_at": now(), "polled": time.time(), "error": ""})
    return stats | {"read": len(fresh), "incidents": sum(item["opened"] for item in opened)}


def signed(tenant: str, body: bytes, signature: str) -> bool:
    found = connection(tenant)
    return bool(found) and hmac.compare_digest("sha256=" + hmac.new(found["secret"].encode(), body, hashlib.sha256).hexdigest(), signature)


def reply(tenant: str, issue: str, body: str) -> str:
    found = connection(tenant)
    if not found or not found["token"]:
        raise ValueError("Posting to GitHub needs a connected repository with a token that may write issues.")
    return github.comment(issue, found["token"], body)


def revertable(tenant: str, pr: str) -> str | None:
    """owner/name#number when the change is a pull request merged in the watched repository and a token is kept."""
    found = connection(tenant)
    if not found or not found["token"]:
        return None
    number, here = pr.removeprefix("PR-"), f"/{found['repo']}/pull/".lower()
    merged_here = any(str(change["number"]) == number and here in change.get("html_url", "").lower() for change in _export(world.world_of(tenant), "git"))
    return f"{found['repo']}#{number}" if merged_here else None


def revert(tenant: str, pull: str, title: str, body: str) -> str:
    found = connection(tenant)
    if not found or not found["token"]:
        raise ValueError("Opening a pull request needs a connected repository with a token that may write to it.")
    return github.revert(pull, found["token"], title, body)


def loop(start: Start) -> None:
    while True:
        for file in world.HOME.glob("*/github.json"):
            tenant = file.parent.name
            found = connection(tenant)
            due = time.time() - found.get("polled", 0) >= (TICK_SECONDS if found["token"] else TOKENLESS_SECONDS)
            if due and tenant in tenants():
                try:
                    sync(tenant, start)
                except Exception:
                    pass
        time.sleep(TICK_SECONDS)
