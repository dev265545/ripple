import csv
import hashlib
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import message_from_bytes
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

import yaml
from falkordb import Graph

from ripple import model
from ripple.graph import now, read, write

Ref = tuple[str, str]
Resolve = Callable[[str, str], Ref]

RISK_PATTERNS = {
    "config": r"config|\.ya?ml$|\.cron$",
    "pool": r"\bpool\b",
    "migration": r"migrations?/|\.sql$",
    "retry": r"\bretr(y|ies)\b",
    "timeout": r"\btimeout\b",
    "scaling": r"\breplicas?\b",
}


@dataclass
class Record:
    key: str
    uri: str
    raw: str
    text: str = ""
    nodes: list[tuple] = field(default_factory=list)
    edges: list[tuple] = field(default_factory=list)

    def node(self, label: str, id: str, quote: str | None = None, **props) -> Ref:
        self.nodes.append((label, id, quote, props))
        return label, id

    def edge(self, source: Ref, kind: str, target: Ref, key: dict | None = None, **props) -> None:
        self.edges.append((source, kind, target, key or {}, props))


def hr(path: Path, resolve: Resolve) -> Iterable[Record]:
    for row in csv.DictReader(path.open()):
        record = Record(row["id"], f"{path.name}#{row['id']}", json.dumps(row))
        person = record.node("Person", row["id"], name=row["name"], email=row["email"], role=row["role"])
        record.edge(person, "MEMBER_OF", record.node("Team", row["team"], name=row["team"]))
        if row["manager"]:
            record.edge(person, "REPORTS_TO", ("Person", row["manager"]))
        identities = [f"email:{row['email']}", f"name:{row['name']}"]
        if row["git_handle"]:
            identities.append(f"git:{row['git_handle']}")
        for identity in identities:
            record.edge(person, "HAS_IDENTITY", record.node("Identity", identity))
        yield record


def catalog(path: Path, resolve: Resolve) -> Iterable[Record]:
    for entity in yaml.safe_load_all(path.read_text()):
        name, spec = entity["metadata"]["name"], entity["spec"]
        record = Record(name, f"{path.name}#{name}", json.dumps(entity, sort_keys=True))
        description = entity["metadata"].get("description")
        if entity["kind"] == "Resource":
            record.node("Vendor", name, name=description)
            yield record
            continue
        annotations = entity["metadata"].get("annotations", {})
        tier = int(next((value for key, value in annotations.items() if key.endswith("/tier")), 3))
        service = record.node("Service", name, name=name, description=description, tier=tier, type=spec["type"])
        record.edge(record.node("Team", spec["owner"], name=spec["owner"]), "OWNS", service)
        record.edge(record.node("Repo", name, name=name), "BUILDS", service)
        for folder in next((value.split(",") for key, value in annotations.items() if key.endswith("/paths")), []):
            record.edge(service, "HAS_IDENTITY", record.node("Identity", f"path:{folder.strip()}"))
        for dependency in spec.get("dependsOn", []):
            kind, target = dependency.split(":")
            record.edge(service, "DEPENDS_ON", ("Service" if kind == "component" else "Vendor", target))
        yield record


def product_map(path: Path, resolve: Resolve) -> Iterable[Record]:
    for product in yaml.safe_load(path.read_text())["products"]:
        record = Record(product["name"], f"{path.name}#{product['name']}", json.dumps(product, sort_keys=True))
        parent = record.node("Product", product["name"], name=product["name"])
        for feature in product["features"]:
            node = record.node("Feature", feature["name"], name=feature["name"])
            record.edge(parent, "HAS", node)
            for service in feature["served_by"]:
                record.edge(node, "SERVED_BY", ("Service", service))
        yield record


def git(path: Path, resolve: Resolve) -> Iterable[Record]:
    for pull in json.loads(path.read_text()):
        id, repo = f"PR-{pull['number']}", pull["base"]["repo"]["name"]
        record = Record(id, f"{path.name}#{id}", json.dumps(pull, sort_keys=True))
        haystack = [pull["title"].lower(), *pull["files"]]
        risk = sorted(flag for flag, pattern in RISK_PATTERNS.items() if any(re.search(pattern, text) for text in haystack))
        node = record.node("PR", id, title=pull["title"], merged_at=pull["merged_at"], repo=repo, files=pull["files"], risk=risk, body=pull.get("body", ""))
        for service in _services_changed(resolve, repo, pull["files"]):
            record.edge(node, "CHANGES", service)
        record.edge(_committer(record, resolve, pull["user"]["login"]), "AUTHORED", node)
        for review in pull["reviews"]:
            record.edge(_committer(record, resolve, review["user"]["login"]), "REVIEWED", node)
        for decision in re.findall(r"Implements (ADR-\d+)", pull.get("body", "")):
            record.edge(node, "IMPLEMENTS", ("Decision", decision))
        for incident in re.findall(r"Fixes (INC-\d+)", pull.get("body", "")):
            record.edge(node, "FIXES", ("Incident", incident))
        yield record


def _services_changed(resolve: Resolve, repo: str, files: list[str]) -> list[Ref]:
    """In a repository shared by several services, the ones whose catalog folders hold the changed files; else the service named after it."""
    folders = {"/".join(file.split("/")[:depth]) for file in files for depth in (1, 2, 3)}
    owners = {resolve("Service", f"path:{repo}/{folder}") for folder in folders}
    return sorted(owner for owner in owners if not owner[1].startswith("path:")) or [("Service", repo)]


def _committer(record: Record, resolve: Resolve, login: str) -> Ref:
    """The person HR lists under this login, else a person known only by the login."""
    found = resolve("Person", f"git:{login}")
    return record.node("Person", found[1], name=login) if found[1] == f"git:{login}" else found


def deploys(path: Path, resolve: Resolve) -> Iterable[Record]:
    for deploy in json.loads(path.read_text()):
        record = Record(deploy["id"], f"{path.name}#{deploy['id']}", json.dumps(deploy, sort_keys=True))
        node = record.node("Deploy", deploy["id"], at=deploy["at"], env=deploy["env"], status=deploy["status"])
        record.edge(node, "SHIPPED", ("PR", f"PR-{deploy['pr']}"))
        record.edge(node, "DEPLOYED_TO", ("Service", deploy["service"]))
        yield record


def oncall(path: Path, resolve: Resolve) -> Iterable[Record]:
    for shift in json.loads(path.read_text())["shifts"]:
        key = f"{shift['service']}@{shift['start']}"
        record = Record(key, f"{path.name}#{key}", json.dumps(shift, sort_keys=True))
        record.edge(resolve("Person", f"email:{shift['email']}"), "ON_CALL_FOR", ("Service", shift["service"]), key={"starts_at": shift["start"]}, ends_at=shift["end"])
        yield record


CRM_COLUMNS = ["id", "name", "domain", "plan", "monthly_revenue_usd", "account_manager", "features"]


def crm(path: Path, resolve: Resolve) -> Iterable[Record]:
    for row in csv.DictReader(path.open()):
        record = Record(row["id"], f"{path.name}#{row['id']}", json.dumps(row))
        extra = {name: value for name, value in row.items() if name not in CRM_COLUMNS and value}
        customer = record.node("Customer", row["id"], name=row["name"], domain=row["domain"], plan=row["plan"], monthly_revenue=int(row["monthly_revenue_usd"] or 0), **extra)
        for identity in (f"name:{row['name']}", f"domain:{row['domain']}"):
            record.edge(customer, "HAS_IDENTITY", record.node("Identity", identity))
        record.edge(resolve("Person", f"name:{row['account_manager']}"), "MANAGES_ACCOUNT", customer)
        for feature in row["features"].split(";"):
            record.edge(customer, "USES", ("Feature", feature))
        yield record


def projects(path: Path, resolve: Resolve) -> Iterable[Record]:
    links = {"services": ("INVOLVES", "Service"), "prs": ("INCLUDES", "PR"), "decisions": ("FOLLOWS", "Decision"), "requirements": ("DELIVERS", "Requirement"), "customers": ("FOR", "Customer")}
    for project in json.loads(path.read_text()):
        record = Record(project["id"], f"{path.name}#{project['id']}", json.dumps(project, sort_keys=True))
        node = record.node("Project", project["id"], name=project["name"], status=project["status"], goal=project["goal"], started_at=project["started"], due_at=project.get("due"))
        record.edge(resolve("Person", f"email:{project['lead']}"), "LEADS", node)
        record.edge(("Team", project["team"]), "WORKS_ON", node)
        for field, (kind, label) in links.items():
            for id in project.get(field, []):
                record.edge(node, kind, (label, id))
        yield record


def calendar(path: Path, resolve: Resolve) -> Iterable[Record]:
    for block in path.read_text().split("BEGIN:VEVENT")[1:]:
        event = dict(line.split(":", 1) for line in block.split("END:VEVENT")[0].strip().splitlines())
        record = Record(event["UID"], f"{path.name}#{event['UID']}", json.dumps(event, sort_keys=True))
        kind, _, subject = event["CATEGORIES"].partition(":")
        node = record.node("Event", event["UID"], title=event["SUMMARY"], kind=kind, starts_at=_ics_time(event["DTSTART"]), ends_at=_ics_time(event["DTEND"]))
        if kind == "customer":
            record.edge(("Customer", subject), "HAS_EVENT", node)
        yield record


def vendor_status(path: Path, resolve: Resolve) -> Iterable[Record]:
    for outage in json.loads(path.read_text())["outages"]:
        record = Record(outage["id"], f"{path.name}#{outage['id']}", json.dumps(outage, sort_keys=True))
        node = record.node("Outage", outage["id"], title=outage["title"], starts_at=outage["start"], ends_at=outage["end"])
        record.edge(node, "OF", ("Vendor", outage["vendor"]))
        yield record


def documents(path: Path, resolve: Resolve) -> Iterable[Record]:
    for file in sorted(path.rglob("*.md")):
        text = file.read_text()
        extracted = extract(file)
        record = Record(extracted["id"], str(file.relative_to(path.parent)), text + json.dumps(extracted, sort_keys=True), text)
        doc = record.node("Doc", extracted["id"], title=extracted["title"], type=extracted["type"], text=text)
        _apply_extraction(record, doc, text, extracted, resolve)
        yield record


def emails(path: Path, resolve: Resolve) -> Iterable[Record]:
    for file in sorted(path.glob("*.eml")):
        message = message_from_bytes(file.read_bytes())
        body = message.get_payload().strip()
        extracted = extract(file)
        id = message["Message-ID"].strip("<>").split("@")[0]
        record = Record(id, str(file.relative_to(path.parent)), file.read_text() + json.dumps(extracted, sort_keys=True), file.read_text())
        sent_at = _iso(parsedate_to_datetime(message["Date"]))
        mail = record.node("Email", id, subject=message["Subject"], sent_at=sent_at, body=body)
        record.edge(_correspondent(message["From"], resolve), "SENT", mail)
        for _, address in getaddresses([message["To"]]):
            record.edge(mail, "SENT_TO", _correspondent(address, resolve))
        _apply_extraction(record, mail, body, extracted, resolve)
        yield record


def extract(file: Path) -> dict:
    """Static stand-in for model extraction: reads the hand-written sidecar next to the file."""
    return json.loads(file.with_suffix(".extracted.json").read_text())


def _apply_extraction(record: Record, origin: Ref, text: str, extracted: dict, resolve: Resolve) -> None:
    def ref(pair: list[str]) -> Ref:
        label, id = pair
        return resolve(label, id) if ":" in id else (label, id)

    def checked(quote: str | None) -> str | None:
        if quote is not None and quote not in text:
            raise ValueError(f"{record.uri}: quote not found in source text: {quote!r}")
        return quote

    for node in extracted["nodes"]:
        record.node(node["label"], node["id"], checked(node.get("quote")), inferred=True, **node["props"])
    for link in extracted["links"]:
        record.edge(ref(link["from"]), link["type"], ref(link["to"]), inferred=True, quote=checked(link.get("quote")))
    for label, id, *quote in extracted["mentions"]:
        record.edge(origin, "MENTIONS", ref([label, id]), quote=checked(quote[0]) if quote else None)


def _correspondent(address: str, resolve: Resolve) -> Ref:
    email = getaddresses([address])[0][1]
    person = resolve("Person", f"email:{email}")
    if person[1] != f"email:{email}":
        return person
    return resolve("Customer", f"domain:{email.split('@')[1]}")


def _ics_time(value: str) -> str:
    return _iso(datetime.strptime(value, "%Y%m%dT%H%M%SZ"))


def _iso(moment: datetime) -> str:
    if moment.tzinfo:
        moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


SOURCES: dict[str, tuple[str, str, Callable]] = {
    "hr": ("HR directory", "people.csv", hr),
    "catalog": ("Service catalog", "catalog.yaml", catalog),
    "product_map": ("Product map", "product_map.yaml", product_map),
    "crm": ("CRM", "customers.csv", crm),
    "git": ("Git host", "prs.json", git),
    "deploys": ("Deploy log", "deploys.json", deploys),
    "oncall": ("On-call schedule", "oncall.json", oncall),
    "projects": ("Projects", "projects.json", projects),
    "calendar": ("Shared calendar", "calendar.ics", calendar),
    "vendor_status": ("Vendor status feeds", "vendor_status.json", vendor_status),
    "documents": ("Documents", "docs", documents),
    "email": ("Email", "email", emails),
    "uploads": ("Uploaded documents", "uploads", documents),
}
EXPORT_FILES = {name: file for name, (_, file, connector) in SOURCES.items() if "." in file}
MAX_EXPORT = 2_000_000
LINKABLE = ["Service", "Vendor", "Person", "Customer", "PR", "Decision", "Incident", "Feature", "Contract", "Requirement", "Project"]
MAX_UPLOAD = 200_000


def sync_all(graph: Graph, world: Path) -> dict[str, dict]:
    return {name: sync(graph, name, world / file) for name, (_, file, _) in SOURCES.items() if (world / file).exists()}


def sync(graph: Graph, name: str, path: Path) -> dict:
    title, _, connector = SOURCES[name]
    write(graph, "MERGE (s:Source {id: $id}) SET s.name = $name", id=name, name=title)
    stats = {"records": 0, "changed": 0}
    # ponytail: one query per node and edge; batch with UNWIND when the world outgrows a few thousand records
    for record in connector(path, lambda label, identity: _resolve(graph, label, identity)):
        stats["records"] += 1
        stats["changed"] += store(graph, name, record)
    write(graph, "MATCH (s:Source {id: $id}) SET s.last_sync = $at, s.uri = $uri", id=name, at=now(), uri=str(path))
    return stats


def _resolve(graph: Graph, label: str, identity: str) -> Ref:
    found = read(graph, "MATCH (:Identity {id: $id})<-[:HAS_IDENTITY]-(n) RETURN labels(n)[0] AS label, n.id AS id", id=identity)
    return (found[0]["label"], found[0]["id"]) if found else (label, identity)


def unchanged(graph: Graph, source: str, record: Record) -> bool:
    known = read(graph, "MATCH (r:SourceRecord {id: $id}) RETURN r.hash AS hash", id=f"{source}:{record.key}")
    return bool(known) and known[0]["hash"] == hashlib.sha1(record.raw.encode()).hexdigest()


def store(graph: Graph, source: str, record: Record) -> int:
    record_id = f"{source}:{record.key}"
    digest = hashlib.sha1(record.raw.encode()).hexdigest()
    known = read(graph, "MATCH (r:SourceRecord {id: $id}) RETURN r.hash AS hash", id=record_id)
    if known and known[0]["hash"] == digest:
        return 0
    write(
        graph,
        "MATCH (s:Source {id: $source}) MERGE (r:SourceRecord {id: $id}) SET r.hash = $hash, r.uri = $uri, r.fetched_at = $at, r.text = $text MERGE (r)-[:FROM]->(s)",
        source=source, id=record_id, hash=digest, uri=record.uri, at=now(), text=record.text or record.raw,
    )
    for label, id, quote, props in record.nodes:
        write(
            graph,
            f"MATCH (r:SourceRecord {{id: $record}}) MERGE (n:{label} {{id: $id}}) SET n += $props MERGE (n)-[e:EVIDENCED_BY]->(r) SET e.quote = $quote, e.rev = $hash",
            record=record_id, id=id, props=props, quote=quote, hash=digest,
        )
    for (source_label, source_id), kind, (target_label, target_id), key, props in record.edges:
        pattern = " {" + ", ".join(f"{name}: $key.{name}" for name in key) + "}" if key else ""
        write(
            graph,
            f"MERGE (a:{source_label} {{id: $a}}) MERGE (b:{target_label} {{id: $b}}) MERGE (a)-[e:{kind}{pattern}]->(b) SET e += $props, e.src = $record, e.rev = $hash",
            a=source_id, b=target_id, key=key, props=props, record=record_id, hash=digest,
        )
    if known:
        _retract(graph, record_id, digest)
    return 1


def _retract(graph: Graph, record: str, digest: str) -> None:
    """A record that changed takes back what it no longer says; a thing no other record backs goes with it."""
    # ponytail: scans every relationship for its src; index e.src if graphs grow past ~100k edges
    write(graph, "MATCH ()-[e]->() WHERE e.src = $record AND e.rev <> $hash DELETE e", record=record, hash=digest)
    orphans = read(graph, "MATCH (n)-[e:EVIDENCED_BY]->(:SourceRecord {id: $record}) WHERE e.rev <> $hash RETURN labels(n)[0] AS label, n.id AS id", record=record, hash=digest)
    write(graph, "MATCH (n)-[e:EVIDENCED_BY]->(:SourceRecord {id: $record}) WHERE e.rev <> $hash DELETE e", record=record, hash=digest)
    for orphan in orphans:
        write(graph, f"MATCH (n:{orphan['label']} {{id: $id}}) WHERE NOT (n)-[:EVIDENCED_BY]->() DETACH DELETE n", id=orphan["id"])


def replace_export(graph: Graph, world: Path, name: str, text: str) -> dict:
    """Saves an uploaded export as the source's file and syncs it; a file the connector cannot read is put back."""
    if not text.strip() or len(text) > MAX_EXPORT:
        raise ValueError(f"The file must be non-empty and under {MAX_EXPORT:,} characters.")
    path = world / EXPORT_FILES[name]
    previous = path.read_text() if path.exists() else None
    path.write_text(text)
    try:
        # ponytail: a file that fails halfway leaves the records before the bad one in the graph
        return sync(graph, name, path)
    except Exception as problem:
        path.unlink() if previous is None else path.write_text(previous)
        detail = f"missing field {problem}" if isinstance(problem, KeyError) else str(problem)
        raise ValueError(f"Could not read this as {SOURCES[name][0]}: {detail}") from problem


def source_overview(graph: Graph) -> list[dict]:
    return read(
        graph,
        """
        MATCH (s:Source)
        OPTIONAL MATCH (s)<-[:FROM]-(r:SourceRecord)
        WITH s, count(r) AS records
        OPTIONAL MATCH (s)<-[:FROM]-(:SourceRecord)<-[:EVIDENCED_BY]-(n)
        RETURN s.id AS id, s.name AS name, s.uri AS uri, s.last_sync AS last_sync, records, count(DISTINCT n) AS nodes
        ORDER BY name
        """,
    )


def sourced_graph(graph: Graph) -> dict:
    """Every thing a source record evidences, with the sources it came from, and the relationships between them."""
    nodes = read(
        graph,
        """
        MATCH (n)-[:EVIDENCED_BY]->(:SourceRecord)-[:FROM]->(s:Source)
        WHERE NOT n:Identity
        WITH n, s ORDER BY s.id
        RETURN labels(n)[0] AS kind, n.id AS id, coalesce(n.name, n.title, n.id) AS name, collect(DISTINCT s.id) AS sources
        ORDER BY kind, id
        """,
    )
    edges = read(
        graph,
        """
        MATCH (a)-[r]->(b)
        WHERE (a)-[:EVIDENCED_BY]->() AND (b)-[:EVIDENCED_BY]->() AND type(r) <> 'EVIDENCED_BY' AND NOT a:Identity AND NOT b:Identity
        RETURN DISTINCT labels(a)[0] + ':' + a.id AS source, type(r) AS relation, labels(b)[0] + ':' + b.id AS target
        ORDER BY source, relation, target
        """,
    )
    area = {row["ref"]: row["title"] for row in read(graph, "MATCH (n)-[:IN_AREA]->(a:Area) RETURN labels(n)[0] + ':' + n.id AS ref, a.title AS title")}
    nodes = [node | {"area": area.get(f"{node['kind']}:{node['id']}")} for node in nodes]
    return {"sources": read(graph, "MATCH (s:Source) RETURN s.id AS id, s.name AS name ORDER BY name"), "nodes": nodes, "edges": edges}


def named_entities(graph: Graph, text: str) -> list[dict]:
    """Entities the text names by id or name, each with the line that names it, in order of appearance."""
    # ponytail: exact id/name matching only; aliases and fuzzy names need the model-backed extractor
    known = read(graph, "MATCH (n) WHERE labels(n)[0] IN $kinds RETURN labels(n)[0] AS kind, n.id AS id, coalesce(n.name, n.id) AS name", kinds=LINKABLE)
    found = []
    for entity in known:
        terms = "|".join(re.escape(term) for term in {entity["id"], entity["name"]} if len(term) >= 4)
        match = terms and re.search(rf"(?<![\w-])({terms})(?![\w-])", text, re.IGNORECASE)
        if match:
            start = text.rfind("\n", 0, match.start()) + 1
            end = text.find("\n", match.end())
            found.append({**entity, "quote": text[start : end if end != -1 else len(text)].strip(), "at": match.start()})
    return sorted(found, key=lambda entity: entity["at"])


def add_document(graph: Graph, folder: Path, name: str, text: str) -> dict:
    """Any text is a source: store it, link the entities it names with the sentence as evidence, and ingest it."""
    if not text.strip() or len(text) > MAX_UPLOAD:
        raise ValueError(f"a document must be between 1 and {MAX_UPLOAD} characters")
    slug = re.sub(r"[^a-z0-9]+", "-", Path(name).stem.lower()).strip("-") or "document"
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / f"{slug}.md"
    earlier = json.loads(file.with_suffix(".extracted.json").read_text()) if file.exists() and file.read_text() == text else None
    file.write_text(text)
    entities = named_entities(graph, text)
    reading = understand(graph, text, f"COM-{slug}") if model.settings() else {"promises": [], "things": [], "links": []}
    promises = reading["promises"]
    sidecar = {
        "id": f"UP-{slug}",
        "type": "upload",
        "title": (text.strip().splitlines()[0].lstrip("# ").strip() if Path(name).suffix else name.strip())[:120],
        "nodes": reading["things"] + [{"label": "Commitment", "id": promise["id"], "quote": promise["quote"], "props": {"text": promise["text"], "made_at": now(), **({"valid_to": promise["valid_to"]} if promise["valid_to"] else {})}} for promise in promises],
        "links": reading["links"] + [link for promise in promises for link in ({"from": ["Person", promise["made_by"]], "type": "MADE", "to": ["Commitment", promise["id"]]}, {"from": ["Commitment", promise["id"]], "type": "MADE_TO", "to": ["Customer", promise["customer"]]})],
        "mentions": [[entity["kind"], entity["id"], entity["quote"]] for entity in entities],
    }
    # Models do not read the same text the same way twice; a thinner second reading does not replace a fuller first one.
    if earlier and len(earlier["nodes"]) + len(earlier["links"]) > len(sidecar["nodes"]) + len(sidecar["links"]):
        sidecar, promises = earlier, []
    file.with_suffix(".extracted.json").write_text(json.dumps(sidecar, indent=1))
    stats = sync(graph, "uploads", folder)
    things, links = [node for node in sidecar["nodes"] if node["label"] != "Commitment"], [link for link in sidecar["links"] if link["type"] not in ("MADE", "MADE_TO")]
    return {"doc": sidecar["id"], "record": f"uploads:{sidecar['id']}", "title": sidecar["title"], "linked": entities, "promises": promises, "things": things, "links": links, "model": model.name(), **stats}


READING_INSTRUCTIONS = """Read the document for three things this company will need later.
Reply with JSON:
{"promises": [{"text": one plain sentence, "quote": the exact sentence copied character for character from the document,
  "customer": customer id, "made_by": person id, "valid_to": ISO date-time the promise ends or null,
  "replaces": id of a listed live promise to the same customer that this one changes, withdraws or contradicts, or null}],
 "decisions": [{"text": one plain sentence saying what was decided, "quote": the exact sentence copied character for character from the document,
  "decided_by": person id, "replaces": id of a listed decision this one changes or reverses, or null}],
 "things": [{"kind": kind, "id": id, "quote": exact sentence, "props": {property: value}}],
 "links": [{"from": [kind, id], "type": link type, "to": [kind, id], "quote": exact sentence}],
 "note": one sentence under 30 words saying what this document tells the company that will matter later, or null}
A thing is something this document itself defines, such as the contract it is, the incident it reviews or the decision it records; kind is one of the kinds below, id is the identifier the document gives it or a short one you make up, and props may hold only the properties listed for its kind:
{things}
A link joins two of your things, or one of them and something named in the document, and must be one of:
{links}
Link every person the document says decided or requested something, by their listed id. Every thing and every link carries a quote: the exact sentence it rests on, copied character for character from the document.
A promise is a commitment this company made to a listed customer, by a listed person. A decision is a choice the company settled on about how it builds or runs things, made by a listed person; a question, a plan to look into something, or a status update is not a decision.
Use only the ids listed. Empty lists are a fine answer. The note may only state what the document says."""
THINGS = {
    "Contract": {"title"},
    "SLA": {"uptime_target", "credit_percent"},
    "Incident": {"title", "started_at", "resolved_at", "status", "symptom", "summary"},
    "Decision": {"title", "status", "decided_at", "risk"},
    "Requirement": {"text", "target"},
}
LINKS = {
    ("Customer", "HAS_CONTRACT", "Contract"), ("Contract", "GUARANTEES", "SLA"), ("SLA", "COVERS", "Feature"),
    ("Incident", "AFFECTS", "Service"), ("Incident", "CAUSED_BY", "PR"), ("PR", "FIXES", "Incident"),
    ("Person", "DECIDED", "Decision"), ("Decision", "GOVERNS", "Service"), ("Decision", "SUPERSEDES", "Decision"), ("Decision", "MOTIVATED_BY", "Incident"),
    ("Customer", "REQUESTED", "Requirement"), ("Person", "REQUESTED", "Requirement"), ("Requirement", "APPLIES_TO", "Service"),
}
NAMED_BEFORE_KNOWN = {"Decision", "Incident", "PR"}
READING_INSTRUCTIONS = READING_INSTRUCTIONS.replace("{things}", "\n".join(f"{kind}: {', '.join(sorted(props))}" for kind, props in THINGS.items())).replace(
    "{links}", "\n".join(f"{source} {kind} {target}" for source, kind, target in sorted(LINKS))
)
MAX_NOTE = 300
MAX_LISTED = 40


def understand(graph: Graph, text: str, prefix: str) -> dict:
    """Model reading: a promise or decision is kept only when its quote is in the text word for word and its people are known."""
    nothing = {"promises": [], "decisions": [], "note": None, "things": [], "links": []}
    named = {(entity["kind"], entity["id"]): entity["name"] for entity in named_entities(graph, text)}
    customers = {row["id"]: row["name"] for row in read(graph, "MATCH (c:Customer) RETURN c.id AS id, c.name AS name")}
    people = {row["id"]: row["name"] for row in read(graph, "MATCH (p:Person) RETURN p.id AS id, p.name AS name")}
    live = {row["id"]: row for row in read(graph, "MATCH (m:Commitment)-[:MADE_TO]->(c:Customer) WHERE m.valid_to IS NULL OR m.valid_to >= $at RETURN m.id AS id, m.text AS text, c.id AS customer ORDER BY m.made_at DESC LIMIT $limit", at=now(), limit=MAX_LISTED)}
    decided = {row["id"]: row["title"] for row in read(graph, "MATCH (d:Decision) WHERE coalesce(d.status, 'accepted') = 'accepted' RETURN d.id AS id, d.title AS title ORDER BY id LIMIT $limit", limit=MAX_LISTED)}
    listing = f"Customers: {json.dumps(customers)}\nPeople: {json.dumps(people)}\nLive promises: {json.dumps(list(live.values()))}\nDecisions: {json.dumps(decided)}\nNamed in this document: {json.dumps([[kind, id, name] for (kind, id), name in named.items()])}"
    try:
        reply = model.chat([{"role": "system", "content": f"{READING_INSTRUCTIONS}\n{listing}"}, {"role": "user", "content": text}], json_reply=True)
        parsed = json.loads(reply["content"])
        found, choices, note = parsed.get("promises") or [], parsed.get("decisions") or [], parsed.get("note")
    except (model.ModelUnavailable, KeyError, TypeError, ValueError):
        return nothing
    quoted = lambda item: isinstance(item, dict) and isinstance(item.get("quote"), str) and item["quote"] in text and item.get("text")
    promises = [
        {
            "id": f"{prefix}-{index}", "text": str(item["text"]), "quote": item["quote"], "customer": item["customer"], "customer_name": customers[item["customer"]],
            "made_by": item["made_by"], "made_by_name": people[item["made_by"]], "valid_to": item.get("valid_to") or None,
            "replaces": item["replaces"] if item.get("replaces") in live and live[item["replaces"]]["customer"] == item["customer"] else None,
        }
        for index, item in enumerate((item for item in found if quoted(item) and item.get("customer") in customers and item.get("made_by") in people), start=1)
    ]
    decisions = [
        {"id": f"DEC-{prefix.removeprefix('COM-')}-{index}", "text": str(item["text"]), "quote": item["quote"], "decided_by": item["decided_by"], "decided_by_name": people[item["decided_by"]], "replaces": item["replaces"] if item.get("replaces") in decided else None}
        for index, item in enumerate((item for item in choices if quoted(item) and item.get("decided_by") in people), start=1)
    ]
    return {"promises": promises, "decisions": decisions, "note": note.strip()[:MAX_NOTE] if isinstance(note, str) and note.strip() else None, **structure(parsed, text, set(named), prefix.removeprefix("COM-"))}


def _plain_value(name: str, value):
    """Models write 99.9 as "99.9%" and Accepted for accepted; queries compare the plain forms."""
    if name == "status":
        return str(value).lower()
    number = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%?\s*", value) if isinstance(value, str) else None
    return float(number[1]) if number else value


def structure(parsed: dict, text: str, named: set[Ref], slug: str) -> dict:
    """The things and links a model read out of a document, minus any with a quote not in the text, a kind outside the schema or an end nothing backs."""
    quoted = lambda item: isinstance(item, dict) and isinstance(item.get("quote"), str) and item["quote"] in text
    ids, things, links = {}, [], []
    def declare(kind: str, given: str, quote: str, props: dict) -> list[str]:
        ids[kind, given] = given if re.fullmatch(r"[\w.-]{5,}", given) and given in text else f"{kind.upper()}-{slug}-{len(things) + 1}"
        things.append({"label": kind, "id": ids[kind, given], "quote": quote, "props": {name: _plain_value(name, value) for name, value in props.items() if name in THINGS[kind] and isinstance(value, (str, int, float))}})
        return [kind, ids[kind, given]]

    for item in parsed.get("things") or []:
        kind, given = (item.get("kind"), item.get("id")) if quoted(item) else (None, None)
        if kind in THINGS and isinstance(given, str) and (kind, given) not in ids:
            declare(kind, given, item["quote"], item.get("props") or {})

    def end(pair, quote: str) -> list[str] | None:
        kind, id = pair
        if (kind, id) in ids:
            return [kind, ids[kind, id]]
        if (kind, id) in named or (kind in NAMED_BEFORE_KNOWN and isinstance(id, str) and id in text):
            return [kind, id]
        # A link may be the only place the model mentions a thing it found; the link's sentence then stands behind the thing too.
        return declare(kind, id, quote, {}) if kind in THINGS and kind not in NAMED_BEFORE_KNOWN and isinstance(id, str) else None

    for item in parsed.get("links") or []:
        try:
            known = quoted(item) and (item["from"][0], item.get("type"), item["to"][0]) in LINKS
            source, target = (end(item["from"], item["quote"]), end(item["to"], item["quote"])) if known else (None, None)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        link = {"from": source, "type": item.get("type"), "to": target, "quote": item["quote"]} if source and target else None
        if link and link not in links:
            links.append(link)
    return {"things": things, "links": links}


def records(graph: Graph, source: str) -> list[dict]:
    return read(
        graph,
        """
        MATCH (:Source {id: $source})<-[:FROM]-(r:SourceRecord)
        OPTIONAL MATCH (n)-[:EVIDENCED_BY]->(r)
        RETURN r.id AS id, r.uri AS uri, r.hash AS hash, r.fetched_at AS fetched_at, count(n) AS nodes ORDER BY uri
        """,
        source=source,
    )


def record_trace(graph: Graph, record: str) -> dict | None:
    """What one source record put into the graph: its nodes, its relationships, and the quotes behind them."""
    head = read(graph, "MATCH (r:SourceRecord {id: $id})-[:FROM]->(s:Source) RETURN r.uri AS uri, r.hash AS hash, r.fetched_at AS fetched_at, r.text AS text, s.name AS source", id=record)
    if not head:
        return None
    nodes = read(
        graph,
        """
        MATCH (n)-[e:EVIDENCED_BY]->(:SourceRecord {id: $id})
        RETURN labels(n)[0] AS kind, n.id AS id, coalesce(n.name, n.title, n.subject, n.id) AS name, e.quote AS quote,
               coalesce(n.inferred, false) AS inferred
        ORDER BY kind, id
        """,
        id=record,
    )
    # ponytail: scans every relationship for its src; index r.src if graphs grow past ~100k edges
    edges = read(
        graph,
        """
        MATCH (a)-[e]->(b) WHERE e.src = $id
        RETURN labels(a)[0] + ':' + a.id AS source, type(e) AS relation, labels(b)[0] + ':' + b.id AS target, e.quote AS quote,
               coalesce(e.inferred, false) AS inferred
        ORDER BY relation, source, target
        """,
        id=record,
    )
    return {**head[0], "id": record, "nodes": [node for node in nodes if node["kind"] != "Identity"], "edges": [edge for edge in edges if not edge["target"].startswith("Identity:")]}
