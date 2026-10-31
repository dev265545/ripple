import hashlib
import json

from falkordb import Graph

from ripple import access, model
from ripple.graph import now, read, write

MEMBERS = ["Person", "Team", "Service", "Vendor", "Customer", "Contract", "SLA", "Commitment", "Feature", "Product", "Project", "Decision", "Incident", "PR", "Requirement", "Repo"]
MANY = {"Person": "people", "PR": "changes", "SLA": "uptime guarantees", "Commitment": "promises", "Repo": "repositories"}
MIN_SIZE = 3
MAX_WRITTEN = 8
MAX_FACTS = 60
MAX_SUMMARY = 500
SHOWN = 8
INSTRUCTIONS = """You describe one part of a company from facts in its knowledge graph. Reply with JSON:
{"title": a name for this part in at most five words, "summary": two or three plain sentences on what this part is and who and what it involves,
 "findings": [{"text": one sentence stating something the facts show, "refs": [ids of the things it is about, copied exactly from the facts, such as "Service:ledger-db"]}]}
Give three to five findings. State only what the facts say. Every finding needs at least one ref."""


def refresh(graph: Graph, written: bool = False) -> list[dict]:
    """Clusters the graph with FalkorDB's label propagation and keeps one Area per cluster; a model rewrites a summary only when asked."""
    private = access.view(graph, None).hidden
    ranked = {row["ref"]: row["score"] for row in read(graph, "CALL algo.pageRank(NULL, NULL) YIELD node, score RETURN labels(node)[0] + ':' + node.id AS ref, score")}
    clusters: dict[int, list[dict]] = {}
    for row in read(
        graph,
        "CALL algo.labelPropagation({nodeLabels: $labels}) YIELD node, communityId "
        "RETURN communityId AS cluster, labels(node)[0] AS kind, node.id AS id, coalesce(node.name, node.title, node.text, node.id) AS name",
        labels=MEMBERS,
    ):
        ref = f"{row['kind']}:{row['id']}"
        if ref not in private:
            clusters.setdefault(row["cluster"], []).append(row | {"ref": ref})
    links = read(graph, "MATCH (a)-[]->(b) WHERE labels(a)[0] IN $labels AND labels(b)[0] IN $labels RETURN labels(a)[0] + ':' + a.id AS a, labels(b)[0] + ':' + b.id AS b", labels=MEMBERS)
    known = {row["id"]: row["hash"] for row in read(graph, "MATCH (a:Area) RETURN a.id AS id, a.hash AS hash")}
    kept = []
    for members in [joined for cluster in clusters.values() for joined in _joined(cluster, links)]:
        if len(members) < MIN_SIZE:
            continue
        members.sort(key=lambda member: (-ranked.get(member["ref"], 0), member["ref"]))
        teams = [member for member in members if member["kind"] == "Team"]
        centre = teams[0] if len(teams) == 1 else members[0]
        area = f"AREA-{centre['id']}"
        kept.append(area)
        digest = hashlib.sha1(json.dumps(sorted(member["ref"] for member in members)).encode()).hexdigest()
        if known.get(area) != digest:
            _store(graph, area, centre["name"], members, digest)
    write(graph, "MATCH (a:Area) WHERE NOT a.id IN $kept DETACH DELETE a", kept=kept)
    if written and model.settings():
        for row in read(graph, "MATCH (a:Area) WHERE a.written_by IS NULL RETURN a.id AS id ORDER BY a.size DESC LIMIT $limit", limit=MAX_WRITTEN):
            _write(graph, row["id"])
    return listing(graph)


def _joined(members: list[dict], links: list[dict]) -> list[list[dict]]:
    """Label propagation can leave unlinked things sharing a label; an area is only those joined to each other."""
    group = {member["ref"]: member["ref"] for member in members}

    def root(ref: str) -> str:
        while group[ref] != ref:
            ref = group[ref]
        return ref

    for link in links:
        if link["a"] in group and link["b"] in group:
            group[root(link["a"])] = root(link["b"])
    parts: dict[str, list[dict]] = {}
    for member in members:
        parts.setdefault(root(member["ref"]), []).append(member)
    return list(parts.values())


def listing(graph: Graph) -> list[dict]:
    open_incidents = {
        row["area"]: row["incidents"]
        for row in read(graph, "MATCH (i:Incident {status: 'open'})-[:AFFECTS]->(:Service)-[:IN_AREA]->(a:Area) RETURN a.id AS area, collect(DISTINCT i.id) AS incidents")
    }
    rows = read(graph, "MATCH (a:Area) RETURN a.id AS id, a.title AS title, a.summary AS summary, a.findings AS findings, a.size AS size, a.members AS members, a.built_at AS built_at, a.written_by AS written_by ORDER BY size DESC, id")
    return [row | {"findings": json.loads(row["findings"]), "open_incidents": open_incidents.get(row["id"], [])} for row in rows]


def _store(graph: Graph, area: str, title: str, members: list[dict], digest: str) -> None:
    write(
        graph,
        "MERGE (a:Area {id: $id}) SET a.title = $title, a.summary = $summary, a.findings = '[]', a.hash = $hash, a.size = $size, a.members = $shown, a.built_at = $at, a.written_by = NULL "
        "WITH a OPTIONAL MATCH ()-[e:IN_AREA]->(a) DELETE e",
        id=area, title=title, summary=_counted(members), hash=digest, size=len(members), shown=[member["ref"] for member in members[:SHOWN]], at=now(),
    )
    for kind in {member["kind"] for member in members}:
        write(
            graph,
            f"MATCH (a:Area {{id: $area}}), (n:{kind}) WHERE n.id IN $ids MERGE (n)-[:IN_AREA]->(a)",
            area=area, ids=[member["id"] for member in members if member["kind"] == kind],
        )


def _counted(members: list[dict]) -> str:
    """The summary a graph can give without a model: what the cluster is centred on and what it holds."""
    kinds: dict[str, int] = {}
    for member in members:
        kinds[member["kind"]] = kinds.get(member["kind"], 0) + 1
    holds = ", ".join(f"{count} {MANY.get(kind, kind.lower() + 's') if count > 1 else kind.lower()}" for kind, count in sorted(kinds.items(), key=lambda item: -item[1]))
    return f"Most connected: {', '.join(member['name'] for member in members[:3])}. Holds {holds}."


def _write(graph: Graph, area: str) -> None:
    """One model call per area. A finding must name only members, and a summary with no such finding is thrown away."""
    inside = "MATCH (x)-[:IN_AREA]->(:Area {id: $id}) MATCH (x)-[e]->(y) WHERE (y)-[:IN_AREA]->(:Area {id: $id}) AND type(e) <> 'IN_AREA'"
    facts = read(
        graph,
        f"{inside} RETURN labels(x)[0] + ':' + x.id AS a, coalesce(x.name, x.title, x.text, x.id) AS a_name, type(e) AS relation, "
        "labels(y)[0] + ':' + y.id AS b, coalesce(y.name, y.title, y.text, y.id) AS b_name ORDER BY a, relation, b LIMIT $limit",
        id=area, limit=MAX_FACTS,
    )
    members = {row["ref"] for row in read(graph, "MATCH (n)-[:IN_AREA]->(:Area {id: $id}) RETURN labels(n)[0] + ':' + n.id AS ref", id=area)}
    lines = "\n".join(f"{fact['a']} ({fact['a_name']}) {fact['relation']} {fact['b']} ({fact['b_name']})" for fact in facts)
    try:
        reply = model.chat([{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": lines}], json_reply=True)
        parsed = json.loads(reply["content"])
        title, summary = str(parsed["title"]).strip()[:60], str(parsed["summary"]).strip()[:MAX_SUMMARY]
        findings = [
            {"text": str(finding["text"]), "refs": finding["refs"]}
            for finding in parsed["findings"]
            if isinstance(finding, dict) and finding.get("text") and finding.get("refs") and members.issuperset(finding["refs"])
        ]
    except (model.ModelUnavailable, KeyError, TypeError, ValueError):
        return
    if title and summary and findings:
        write(
            graph,
            "MATCH (a:Area {id: $id}) SET a.title = $title, a.summary = $summary, a.findings = $findings, a.written_by = $by",
            id=area, title=title, summary=summary, findings=json.dumps(findings), by=reply.get("model", model.name()),
        )
