import json
import os
import re
import threading
from pathlib import Path
from typing import Annotated

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ripple import access, actions, agents, areas, chat, checks, connectors, demo, evaluate, fixer, github, inbox, ingest, live, load, memory, model, queries, trust, watch, world
from ripple.graph import connect, read, tenants
from ripple.investigation import open_incident, parse_alerts, resolve, state
from ripple.mcp_server import parameters

WEB = Path("web/dist")
STEP_DELAY = float(os.getenv("RIPPLE_STEP_DELAY", "0.6"))
app = FastAPI(title="Ripple")
# ponytail: who is asking is the demo login's word, sent by the browser; put real auth in front before this leaves a demo
Viewer = Annotated[str | None, Header(alias="X-Ripple-User")]


class Approval(BaseModel):
    user: str
    body: str | None = None


class Login(BaseModel):
    email: str


class NewCompany(BaseModel):
    name: str


class Export(BaseModel):
    text: str


class Pull(BaseModel):
    fields: dict[str, str] = {}


class Upload(BaseModel):
    name: str
    text: str


class Question(BaseModel):
    text: str
    user: str
    session: str = "default"


class ToolCall(BaseModel):
    params: dict[str, str] = {}
    user: str = "demo"
    session: str = "default"


def graph_of(tenant: str):
    if tenant not in tenants():
        raise HTTPException(404, f"unknown tenant: {tenant}")
    return connect(tenant)


def start(tenant: str, alert: dict) -> dict:
    investigation, opened = open_incident(connect(tenant), alert)
    if opened:
        threading.Thread(target=agents.run, args=(tenant, investigation, 3, STEP_DELAY), daemon=True).start()
    return {"investigation": investigation, "opened": opened}


@app.on_event("startup")
def watch_repositories() -> None:
    threading.Thread(target=watch.loop, args=(start,), daemon=True).start()
    threading.Thread(target=live.loop, daemon=True).start()


@app.get("/api/connectors")
def connector_catalog() -> list[dict]:
    return connectors.catalog()


@app.get("/api/connectors/{source}/example")
def export_example(source: str) -> dict:
    if source not in ingest.EXPORT_FILES:
        raise HTTPException(404, f"no example export for: {source}")
    file = world.DEFAULT_WORLD / ingest.EXPORT_FILES[source]
    return {"filename": file.name, "text": file.read_text()}


@app.get("/api/tenants")
def list_tenants() -> list[str]:
    return [tenant for tenant in tenants() if not tenant.startswith(("eval", "load-", "test"))]


@app.post("/api/tenants")
def create_tenant(company: NewCompany) -> dict:
    # ponytail: anyone who can reach the API can create a company; put real auth in front before this leaves a demo
    tenant = re.sub(r"[^a-z0-9]+", "-", company.name.lower()).strip("-")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", tenant) or tenant.startswith(("eval", "load-", "test")):
        raise HTTPException(422, "Use 2 to 31 letters, digits or spaces, starting with a letter.")
    if tenant in tenants() or world.runtime(tenant).exists():
        raise HTTPException(409, f"A company called {tenant} already exists.")
    world.create(tenant)
    return {"tenant": tenant}


@app.post("/api/tenants/{tenant}/seed")
def seed(tenant: str) -> dict:
    if world.runtime(tenant).exists() and world.world_of(tenant) != world.demo_world(tenant).resolve():
        raise HTTPException(409, f"{tenant} was built from its own uploads; resetting it would replace them with the demo company.")
    demo.load_history(tenant, world.seed(tenant, world.demo_world(tenant)))
    return {"tenant": tenant}


@app.get("/api/{tenant}/overview")
def overview(tenant: str) -> dict:
    graph = graph_of(tenant)
    return {
        "nodes": read(graph, "MATCH (n) WHERE NOT labels(n)[0] IN ['SourceRecord', 'Identity'] RETURN labels(n)[0] AS kind, count(n) AS count ORDER BY count DESC"),
        "edges": read(graph, "MATCH ()-[r]->() RETURN count(r) AS count")[0]["count"],
    }


@app.get("/api/{tenant}/people")
def people(tenant: str) -> list[dict]:
    return read(graph_of(tenant), "MATCH (p:Person)-[:MEMBER_OF]->(t:Team) RETURN p.id AS id, p.name AS name, p.email AS email, p.role AS role, t.id AS team ORDER BY name")


@app.post("/api/{tenant}/login")
def login(tenant: str, attempt: Login) -> dict:
    # ponytail: directory lookup only, no password or token; put real auth in front before this leaves a demo
    found = read(
        graph_of(tenant),
        "MATCH (:Identity {id: $identity})<-[:HAS_IDENTITY]-(p:Person)-[:MEMBER_OF]->(t:Team) RETURN p.id AS id, p.name AS name, p.email AS email, p.role AS role, t.id AS team",
        identity=f"email:{attempt.email.strip().lower()}",
    )
    if not found:
        raise HTTPException(401, "No one in the company directory has that email.")
    return found[0]


@app.get("/api/{tenant}/connectors")
def list_connectors(tenant: str) -> list[dict]:
    return connectors.overview(graph_of(tenant), {source for source in inbox.SOURCES if _inbox_example(tenant, source).exists()})


@app.post("/api/{tenant}/documents")
def upload(tenant: str, document: Upload) -> dict:
    graph = graph_of(tenant)
    return _or_conflict(lambda: ingest.add_document(graph, world.runtime(tenant) / "uploads", document.name, document.text))


@app.get("/api/{tenant}/sources/{source}/records")
def source_records(tenant: str, source: str, viewer: Viewer = None) -> list[dict]:
    graph = graph_of(tenant)
    return access.view(graph, viewer).only_seen(ingest.records(graph, source), "id")


@app.get("/api/{tenant}/records/{record:path}")
def record(tenant: str, record: str, viewer: Viewer = None) -> dict:
    graph = graph_of(tenant)
    found = ingest.record_trace(graph, record)
    if found is None:
        raise HTTPException(404, f"unknown record: {record}")
    if record in access.view(graph, viewer).records:
        raise HTTPException(403, "Only the people on this item can read it, and none of them has shared it.")
    return found


@app.post("/api/{tenant}/chat")
def ask(tenant: str, question: Question) -> dict:
    return chat.answer(graph_of(tenant), question.text, question.user, question.session)


@app.get("/api/model")
def configured_model() -> dict:
    return {"name": model.name()}


@app.post("/api/{tenant}/actions/{action}/rewrite")
def rewrite_action(tenant: str, action: str) -> dict:
    graph = graph_of(tenant)
    try:
        return _or_conflict(lambda: actions.rewrite(graph, action))
    except model.ModelUnavailable as problem:
        raise HTTPException(503, str(problem)) from problem


@app.get("/api/chat/suggestions")
def suggestions() -> list[str]:
    return chat.SUGGESTIONS


@app.get("/api/{tenant}/sources")
def sources(tenant: str) -> list[dict]:
    return ingest.source_overview(graph_of(tenant))


@app.get("/api/{tenant}/graph")
def sourced_graph(tenant: str, viewer: Viewer = None) -> dict:
    graph = graph_of(tenant)
    found, seen = ingest.sourced_graph(graph), access.view(graph, viewer)
    nodes = [node for node in found["nodes"] if seen.sees(f"{node['kind']}:{node['id']}")]
    return found | {"nodes": nodes, "edges": seen.only_seen(found["edges"], "source", "target"), "withheld": len(found["nodes"]) - len(nodes)}


@app.post("/api/{tenant}/sources/{source}/sync")
def sync(tenant: str, source: str) -> dict:
    if source not in ingest.SOURCES:
        raise HTTPException(404, f"unknown source: {source}")
    root = world.runtime(tenant) if source == "uploads" else world.world_of(tenant)
    graph = graph_of(tenant)
    stats = ingest.sync(graph, source, root / ingest.SOURCES[source][1])
    checks.upkeep(graph)
    return stats


@app.post("/api/{tenant}/sources/{source}/file")
def upload_export(tenant: str, source: str, export: Export) -> dict:
    if source not in ingest.EXPORT_FILES:
        raise HTTPException(404, f"{source} does not take a file upload")
    graph = graph_of(tenant)
    try:
        stats = ingest.replace_export(graph, world.world_of(tenant), source, export.text)
    except ValueError as problem:
        raise HTTPException(422, str(problem)) from problem
    checks.upkeep(graph)
    return stats


@app.post("/api/{tenant}/sources/git/pull")
def git_pull(tenant: str, pull: Pull) -> dict:
    graph_of(tenant)
    try:
        return watch.connect(tenant, pull.fields.get("repo", ""), pull.fields.get("token", "").strip(), int(pull.fields.get("limit") or 10), start)
    except ValueError as problem:
        raise HTTPException(422, str(problem)) from problem


@app.get("/api/{tenant}/github")
def github_connection(tenant: str) -> dict:
    graph_of(tenant)
    found = watch.connection(tenant)
    if not found:
        return {"connected": False}
    seconds = watch.TICK_SECONDS if found["token"] else watch.TOKENLESS_SECONDS
    return {
        "connected": True, "repo": found["repo"], "has_token": bool(found["token"]), "checked_at": found.get("checked_at"), "error": found.get("error", ""),
        "every_seconds": seconds, "label": github.INCIDENT_LABEL, "hook": f"/api/{tenant}/hooks/github", "secret": found["secret"],
    }


@app.post("/api/{tenant}/github/check")
def github_check(tenant: str) -> dict:
    graph_of(tenant)
    try:
        return watch.sync(tenant, start)
    except ValueError as problem:
        raise HTTPException(422, str(problem)) from problem


@app.delete("/api/{tenant}/github")
def github_disconnect(tenant: str) -> dict:
    graph_of(tenant)
    watch.disconnect(tenant)
    return {"connected": False}


@app.post("/api/{tenant}/hooks/github")
async def github_webhook(tenant: str, request: Request) -> dict:
    if not watch.signed(tenant, await request.body(), request.headers.get("X-Hub-Signature-256", "")):
        raise HTTPException(401, "The signature does not match this company's webhook secret.")
    threading.Thread(target=watch.sync, args=(tenant, start), daemon=True).start()
    return {"accepted": True}


@app.post("/api/{tenant}/inbox/{source}/pull")
def inbox_pull(tenant: str, source: str, pull: Pull) -> dict:
    if source in live.SOURCES:
        return live_connect(tenant, source, pull)
    return _filed(tenant, source, lambda: inbox.pull(source, pull.fields))


@app.get("/api/{tenant}/live")
def live_connections(tenant: str) -> dict:
    graph_of(tenant)
    return live.state(tenant)


@app.post("/api/{tenant}/live/{source}")
def live_connect(tenant: str, source: str, pull: Pull) -> dict:
    return _live(tenant, source, lambda: live.connect(tenant, source, pull.fields))


@app.post("/api/{tenant}/live/{source}/check")
def live_check(tenant: str, source: str) -> dict:
    return _live(tenant, source, lambda: live.check(tenant, source))


@app.delete("/api/{tenant}/live/{source}")
def live_disconnect(tenant: str, source: str) -> dict:
    return _live(tenant, source, lambda: live.disconnect(tenant, source) or {"connected": False})


def _live(tenant: str, source: str, action) -> dict:
    graph_of(tenant)
    if source not in live.SOURCES:
        raise HTTPException(404, f"{source} is not a kept connection")
    try:
        return action()
    except ValueError as problem:
        raise HTTPException(422, str(problem)) from problem


@app.get("/api/{tenant}/status")
def status_page(tenant: str) -> dict:
    return {"company": tenant, "updates": actions.status_page(graph_of(tenant))}


@app.post("/api/{tenant}/inbox/{source}/file")
def inbox_file(tenant: str, source: str, name: str, raw: bytes = Body(media_type="application/octet-stream")) -> dict:
    return _filed(tenant, source, lambda: inbox.read_file(source, name, raw))


@app.post("/api/{tenant}/inbox/{source}/example")
def inbox_example(tenant: str, source: str) -> dict:
    file = _inbox_example(tenant, source) if source in inbox.SOURCES else None
    if file is None or not file.exists():
        raise HTTPException(404, f"no sample for: {source}")
    return _filed(tenant, source, lambda: inbox.read_file(source, file.name, file.read_bytes()))


def _inbox_example(tenant: str, source: str) -> Path:
    return world.world_of(tenant) / "inbox" / inbox.EXAMPLES[source]


def _filed(tenant: str, source: str, read_items) -> dict:
    if source not in inbox.SOURCES:
        raise HTTPException(404, f"unknown inbox: {source}")
    graph = graph_of(tenant)
    try:
        return inbox.file(graph, source, read_items())
    except ValueError as problem:
        raise HTTPException(422, str(problem)) from problem


@app.get("/api/{tenant}/services")
def services(tenant: str) -> list[str]:
    return [row["id"] for row in read(graph_of(tenant), "MATCH (s:Service) RETURN s.id AS id ORDER BY id")]


@app.get("/api/{tenant}/scenarios")
def scenarios(tenant: str) -> list[dict]:
    return [{"id": scenario["id"], "title": scenario["title"], "story": scenario.get("story"), "basis": scenario.get("basis"), **parse_alerts(scenario["alert"])[0]} for scenario in world.scenarios(world.world_of(tenant))]


@app.post("/api/{tenant}/scenarios/{scenario}/fire")
def fire(tenant: str, scenario: str) -> dict:
    graph = graph_of(tenant)
    chosen = next((item for item in world.scenarios(world.world_of(tenant)) if item["id"] == scenario), None)
    if chosen is None:
        raise HTTPException(404, f"unknown scenario: {scenario}")
    world.apply_scenario(graph, chosen)
    return start(tenant, parse_alerts(chosen["alert"])[0])


@app.post("/api/{tenant}/hooks/alerts")
def alert_webhook(tenant: str, payload: dict) -> list[dict]:
    graph_of(tenant)
    return [start(tenant, alert) for alert in parse_alerts(payload)]


@app.get("/api/{tenant}/investigations")
def investigations(tenant: str) -> list[dict]:
    return memory.overview(graph_of(tenant))["investigations"]


@app.get("/api/{tenant}/investigations/{investigation}")
def investigation_state(tenant: str, investigation: str) -> dict:
    found = state(graph_of(tenant), investigation)
    if found is None:
        raise HTTPException(404, f"unknown investigation: {investigation}")
    return found


@app.post("/api/{tenant}/investigations/{investigation}/confirm")
def confirm(tenant: str, investigation: str, approval: Approval) -> dict:
    graph_of(tenant)
    return _or_conflict(lambda: agents.confirm(tenant, investigation, approval.user))


@app.post("/api/{tenant}/investigations/{investigation}/resolve")
def resolve_incident(tenant: str, investigation: str, approval: Approval) -> dict:
    graph = graph_of(tenant)
    return _or_conflict(lambda: resolve(graph, investigation, approval.user))


@app.post("/api/{tenant}/actions/{action}/approve")
def approve(tenant: str, action: str, approval: Approval) -> dict:
    graph = graph_of(tenant)
    return _or_conflict(lambda: actions.approve(graph, action, approval.user, approval.body))


@app.post("/api/{tenant}/remediations/{remediation}/merge")
def merge(tenant: str, remediation: str, approval: Approval) -> dict:
    graph = graph_of(tenant)
    return _or_conflict(lambda: fixer.merge(graph, remediation, approval.user))


@app.get("/api/{tenant}/outbox")
def outbox(tenant: str) -> list[dict]:
    return actions.outbox(graph_of(tenant))


@app.get("/api/{tenant}/search")
def search(tenant: str, q: str, viewer: Viewer = None) -> list[dict]:
    graph = graph_of(tenant)
    seen = access.view(graph, viewer)
    return [hit for hit in queries.find_entity(graph, q) if seen.sees(f"{hit['kind']}:{hit['id']}")]


@app.get("/api/{tenant}/entities/{kind}/{id}")
def entity(tenant: str, kind: str, id: str, viewer: Viewer = None) -> dict:
    graph = graph_of(tenant)
    found = _or_conflict(lambda: queries.entity(graph, kind, id))
    if found is None:
        raise HTTPException(404, f"no {kind} with id {id}")
    seen = access.view(graph, viewer)
    if not seen.sees(f"{kind}:{id}"):
        raise HTTPException(403, "This comes only from mail or chats you are not on, and nobody on them has shared it.")
    return access.narrow(found, seen) | {"trust": trust.of(graph, kind, id)}


@app.get("/api/{tenant}/prs/{pr}/reach")
def change_reach(tenant: str, pr: str, viewer: Viewer = None) -> list[dict]:
    graph = graph_of(tenant)
    return queries.redact("change_reach", queries.run(graph, "change_reach", pr=pr), access.view(graph, viewer).hidden)[0]


@app.get("/api/tools")
def tools() -> list[dict]:
    return [{"name": name, "doc": query.doc, "params": parameters(name), "cypher": query.cypher.strip()} for name, query in queries.QUERIES.items()]


@app.post("/api/{tenant}/tools/{name}")
def call_tool(tenant: str, name: str, call: ToolCall) -> dict:
    graph = graph_of(tenant)
    if name not in queries.QUERIES:
        raise HTTPException(404, f"unknown tool: {name}")
    missing = [param for param in parameters(name) if param not in call.params]
    if missing:
        raise HTTPException(422, f"missing parameters: {', '.join(missing)}")
    rows, withheld = queries.redact(name, queries.run(graph, name, **{param: call.params[param] for param in parameters(name)}), access.view(graph, call.user).hidden)
    refs = queries.refs(name, rows)
    memory.remember_turn(graph, call.user, call.session, "user", f"{name} {json.dumps(call.params)}", refs)
    return {"rows": rows, "refs": refs, "withheld": withheld}


@app.get("/api/{tenant}/memory")
def memory_overview(tenant: str, viewer: Viewer = None) -> dict:
    graph = graph_of(tenant)
    found, seen = memory.overview(graph), access.view(graph, viewer)
    return found | {"notes": [note for note in seen.only_seen(found["notes"], "origin") if seen.sees(f"Note:{note['id']}")]}


def _reviewable(pairs: list[dict], seen: access.View) -> list[dict]:
    return [pair for pair in pairs if seen.sees(f"{pair['kind']}:{pair['newer']}") and seen.sees(f"{pair['kind']}:{pair['older']}")]


class Verification(BaseModel):
    kind: str
    id: str
    user: str
    days: int | None = None


class Share(BaseModel):
    record: str
    user: str


class Settlement(BaseModel):
    newer: str
    older: str
    replace: bool
    user: str


@app.get("/api/{tenant}/brief/{person}")
def brief(tenant: str, person: str, viewer: Viewer = None) -> dict:
    graph = graph_of(tenant)
    found, seen = memory.brief(graph, person), access.view(graph, viewer)
    return found | {
        "promises": [promise for promise in found["promises"] if seen.sees(f"Commitment:{promise['id']}")],
        "recent": [item for item in found["recent"] if seen.sees(f"{item['kind']}:{item['id']}")],
        "review": _reviewable(found["review"], seen),
        "to_check": [item for item in found["to_check"] if seen.sees(f"{item['kind']}:{item['id']}")],
    }


@app.get("/api/{tenant}/review")
def review(tenant: str, viewer: Viewer = None) -> list[dict]:
    graph = graph_of(tenant)
    return _reviewable(memory.to_review(graph), access.view(graph, viewer))


@app.post("/api/{tenant}/review")
def settle_review(tenant: str, settlement: Settlement) -> dict:
    graph = graph_of(tenant)
    waiting = _reviewable(memory.to_review(graph), access.view(graph, settlement.user))
    if not any(pair["newer"] == settlement.newer and pair["older"] == settlement.older for pair in waiting):
        raise HTTPException(404, "That pair is not waiting for your review.")
    memory.settle(graph, settlement.newer, settlement.older, settlement.replace, settlement.user)
    return {"settled": True}


@app.get("/api/{tenant}/areas")
def list_areas(tenant: str) -> list[dict]:
    return areas.refresh(graph_of(tenant))


@app.post("/api/{tenant}/areas")
def write_areas(tenant: str) -> list[dict]:
    return areas.refresh(graph_of(tenant), written=True)


@app.get("/api/{tenant}/checks")
def run_checks(tenant: str, viewer: Viewer = None) -> list[dict]:
    graph = graph_of(tenant)
    seen = access.view(graph, viewer)
    return [finding for finding in checks.findings(graph) if all(map(seen.sees, finding["refs"])) and seen.records.isdisjoint(finding["records"])]


@app.post("/api/{tenant}/verify")
def verify(tenant: str, verification: Verification) -> dict:
    graph = graph_of(tenant)
    if not access.view(graph, verification.user).sees(f"{verification.kind}:{verification.id}"):
        raise HTTPException(403, "You cannot verify something you cannot read.")
    try:
        return _or_conflict(lambda: trust.verify(graph, verification.kind, verification.id, verification.user, verification.days))
    except PermissionError as refusal:
        raise HTTPException(403, str(refusal)) from refusal


@app.post("/api/{tenant}/share")
def share(tenant: str, sharing: Share) -> dict:
    if not access.share(graph_of(tenant), sharing.record, sharing.user):
        raise HTTPException(403, "Only someone who is on this item can share it with everyone.")
    return {"shared": True}


@app.get("/api/{tenant}/turns")
def turns(tenant: str, user: str = "demo") -> list[dict]:
    return memory.recall_turns(graph_of(tenant), user)


@app.get("/api/evaluation")
def evaluation() -> dict:
    reading = {"reading": json.loads(evaluate.READING.read_text())} if evaluate.READING.exists() else {}
    return (json.loads(evaluate.RESULTS.read_text()) if evaluate.RESULTS.exists() else {}) | reading


@app.post("/api/evaluation/run")
def run_evaluation() -> dict:
    return evaluate.evaluate()


@app.post("/api/load/run")
def run_load() -> dict:
    return load.run()


def _or_conflict(action):
    try:
        return action()
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


if (WEB / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/{page:path}", include_in_schema=False)
    def web(page: str) -> FileResponse:
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})
