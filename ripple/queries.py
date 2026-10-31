import re
from dataclasses import dataclass
from uuid import uuid4

from falkordb import Graph
from redis.exceptions import ResponseError

from ripple.graph import FULLTEXT, LABELS, read


@dataclass(frozen=True)
class Query:
    doc: str
    cypher: str
    # column -> label of the node ids it holds; "*other" reads the label from another column
    refs: dict[str, str]


QUERIES = {
    "suspect_changes": Query(
        "Recent changes on a service or anything it depends on, nearest first, with the dependency path walked.",
        """
        MATCH path = (s:Service {id: $service})-[:DEPENDS_ON*0..3]->(d:Service)
        MATCH (a:Person)-[:AUTHORED]->(pr:PR)-[:CHANGES]->(d)
        WHERE pr.merged_at >= $since AND pr.merged_at <= $at
        OPTIONAL MATCH (dep:Deploy)-[:SHIPPED]->(pr)
        RETURN pr.id AS pr, pr.title AS title, a.id AS author, a.name AS author_name, d.id AS service,
               pr.risk AS risk, [n IN nodes(path) | n.id] AS via, length(path) AS hops,
               pr.merged_at AS merged_at, min(dep.at) AS deployed_at
        ORDER BY hops, merged_at DESC
        """,
        {"pr": "PR", "author": "Person", "service": "Service", "via": "Service"},
    ),
    "vendor_outages": Query(
        "Third-party vendors a service relies on, directly or through dependencies, with any outage open at that time.",
        """
        MATCH path = (s:Service {id: $service})-[:DEPENDS_ON*0..3]->(d:Service)-[:DEPENDS_ON]->(v:Vendor)
        OPTIONAL MATCH (o:Outage)-[:OF]->(v)
        WHERE o.starts_at <= $at AND (o.ends_at IS NULL OR o.ends_at >= $at)
        RETURN v.id AS vendor, v.name AS name, d.id AS used_by, [n IN nodes(path)[..-1] | n.id] AS via,
               length(path) AS hops, o.id AS outage, o.title AS outage_title, o.starts_at AS since
        ORDER BY hops
        """,
        {"vendor": "Vendor", "used_by": "Service", "via": "Service", "outage": "Outage"},
    ),
    "customer_events": Query(
        "Customer events (sales, launches) running at that time for customers whose traffic reaches a service.",
        """
        MATCH (s:Service {id: $service})<-[:DEPENDS_ON*0..4]-(u:Service)<-[:SERVED_BY]-(f:Feature)<-[:USES]-(c:Customer)-[:HAS_EVENT]->(e:Event)
        WHERE e.starts_at <= $at AND e.ends_at >= $at
        RETURN DISTINCT e.id AS event, e.title AS title, c.id AS customer, c.name AS customer_name,
               e.starts_at AS starts_at, e.ends_at AS ends_at
        """,
        {"event": "Event", "customer": "Customer"},
    ),
    "customer_history": Query(
        "Everything written to, by or about a customer in email, chat and files, newest first, with the sentence that names them and the note kept on it.",
        """
        MATCH (c:Customer {id: $customer})-[e:SENT|SENT_TO|MENTIONS|TOOK_PART_IN]-(o)
        WHERE o:Email OR o:Doc OR o:Conversation
        OPTIONAL MATCH (o)-[:HAS_NOTE]->(n:Note)
        OPTIONAL MATCH (o)-[:EVIDENCED_BY]->(:SourceRecord)-[:FROM]->(s:Source)
        RETURN DISTINCT labels(o)[0] AS kind, o.id AS item, coalesce(o.subject, o.title) AS title, coalesce(o.sent_at, o.started_at) AS at,
               s.name AS read_from, e.quote AS quote, n.text AS note
        ORDER BY at DESC LIMIT 30
        """,
        {"item": "*kind"},
    ),
    "change_detail": Query(
        "Files, reviewers and production deploy time of one change.",
        """
        MATCH (pr:PR {id: $pr})-[:CHANGES]->(s:Service)
        OPTIONAL MATCH (dep:Deploy)-[:SHIPPED]->(pr)
        OPTIONAL MATCH (r:Person)-[:REVIEWED]->(pr)
        RETURN pr.id AS pr, pr.title AS title, s.id AS service, pr.files AS files, pr.risk AS risk,
               pr.merged_at AS merged_at, min(dep.at) AS deployed_at, collect(DISTINCT r.id) AS reviewers
        """,
        {"pr": "PR", "service": "Service", "reviewers": "Person"},
    ),
    "decision_trace": Query(
        "The decision a change implements, who decided it, what it replaced, the incident that motivated it and its recorded risk.",
        """
        MATCH (pr:PR {id: $pr})-[:IMPLEMENTS]->(d:Decision)
        OPTIONAL MATCH (who:Person)-[:DECIDED]->(d)
        OPTIONAL MATCH (d)-[:SUPERSEDES*1..10]->(old:Decision)
        OPTIONAL MATCH (d)-[:MOTIVATED_BY]->(i:Incident)
        RETURN d.id AS decision, d.title AS title, d.status AS status, d.decided_at AS decided_at,
               d.risk AS risk, who.id AS decided_by, who.name AS decided_by_name,
               collect(DISTINCT old.id) AS supersedes, collect(DISTINCT i.id) AS motivated_by
        """,
        {"decision": "Decision", "decided_by": "Person", "supersedes": "Decision", "motivated_by": "Incident"},
    ),
    "governing_decisions": Query(
        "Accepted decisions that govern a service, with their recorded risk.",
        """
        MATCH (d:Decision {status: 'accepted'})-[:GOVERNS]->(s:Service {id: $service})
        OPTIONAL MATCH (who:Person)-[:DECIDED]->(d)
        RETURN d.id AS decision, d.title AS title, d.risk AS risk, who.id AS decided_by, who.name AS decided_by_name
        ORDER BY decision
        """,
        {"decision": "Decision", "decided_by": "Person"},
    ),
    "requirements_at_risk": Query(
        "Stated requirements on a service or on services that depend on it.",
        """
        MATCH (s:Service {id: $service})<-[:DEPENDS_ON*0..4]-(u:Service)<-[:APPLIES_TO]-(r:Requirement)
        OPTIONAL MATCH (c:Customer)-[:REQUESTED]->(r)
        RETURN DISTINCT r.id AS requirement, r.text AS text, r.target AS target, u.id AS service,
               c.id AS requested_by, c.name AS requested_by_name
        ORDER BY requirement
        """,
        {"requirement": "Requirement", "service": "Service", "requested_by": "Customer"},
    ),
    "similar_incidents": Query(
        "Resolved incidents on a service or its dependencies, with what caused and what fixed each.",
        """
        MATCH (s:Service {id: $service})-[:DEPENDS_ON*0..3]->(d:Service)<-[:AFFECTS]-(i:Incident {status: 'resolved'})
        OPTIONAL MATCH (i)-[:CAUSED_BY]->(cause)
        OPTIONAL MATCH (fix:PR)-[:FIXES]->(i)
        RETURN DISTINCT i.id AS incident, i.title AS title, i.symptom AS symptom, d.id AS service,
               cause.id AS cause, labels(cause)[0] AS cause_kind, fix.id AS fix, fix.title AS fix_title,
               i.started_at AS started_at
        ORDER BY started_at DESC
        """,
        {"incident": "Incident", "service": "Service", "cause": "*cause_kind", "fix": "PR"},
    ),
    "who_to_page": Query(
        "Owning team and the person on call for a service at that time.",
        """
        MATCH (t:Team)-[:OWNS]->(s:Service {id: $service})
        OPTIONAL MATCH (p:Person)-[o:ON_CALL_FOR]->(s)
        WHERE o.starts_at <= $at AND o.ends_at > $at
        RETURN s.id AS service, t.id AS team, p.id AS on_call, p.name AS on_call_name, p.email AS email
        """,
        {"service": "Service", "team": "Team", "on_call": "Person"},
    ),
    "expertise": Query(
        "People who have authored or reviewed the most changes on a service.",
        """
        MATCH (p:Person)-[r:AUTHORED|REVIEWED]->(:PR)-[:CHANGES]->(:Service {id: $service})
        RETURN p.id AS person, p.name AS name, count(r) AS touches
        ORDER BY touches DESC, name LIMIT 5
        """,
        {"person": "Person"},
    ),
    "who_knows": Query(
        "People who know a service best, counting the changes they wrote or reviewed, decisions they made about it, mail and chats where they discussed it, and on-call shifts.",
        """
        MATCH (s:Service {id: $service})
        MATCH (p:Person)-[r:AUTHORED|REVIEWED|DECIDED|SENT|TOOK_PART_IN|ON_CALL_FOR]->(x)
        WHERE x = s OR (x)-[:CHANGES|GOVERNS|MENTIONS]->(s)
        RETURN p.id AS person, p.name AS name,
               sum(CASE WHEN type(r) IN ['AUTHORED', 'REVIEWED'] THEN 1 ELSE 0 END) AS changes,
               sum(CASE WHEN type(r) = 'DECIDED' THEN 1 ELSE 0 END) AS decisions,
               sum(CASE WHEN type(r) IN ['SENT', 'TOOK_PART_IN'] THEN 1 ELSE 0 END) AS discussions,
               sum(CASE WHEN type(r) = 'ON_CALL_FOR' THEN 1 ELSE 0 END) AS shifts,
               sum(CASE type(r) WHEN 'DECIDED' THEN 3 WHEN 'AUTHORED' THEN 2 WHEN 'REVIEWED' THEN 2 ELSE 1 END) AS score
        ORDER BY score DESC, name LIMIT 8
        """,
        {"person": "Person"},
    ),
    "single_experts": Query(
        "Services where only one person has written or reviewed changes: knowledge that leaves when they do.",
        """
        MATCH (p:Person)-[:AUTHORED|REVIEWED]->(:PR)-[:CHANGES]->(s:Service)
        WITH s, collect(DISTINCT p) AS experts
        WHERE size(experts) = 1
        RETURN s.id AS service, s.tier AS tier, experts[0].id AS person, experts[0].name AS name
        ORDER BY tier, service
        """,
        {"service": "Service", "person": "Person"},
    ),
    "promises_as_of": Query(
        "Promises to a customer that were in force on a given date, including ones later replaced, with the sentence each rests on.",
        """
        MATCH (c:Customer {id: $customer})<-[:MADE_TO]-(m:Commitment)
        WHERE m.made_at <= $at AND (m.valid_to IS NULL OR m.valid_to > $at)
        OPTIONAL MATCH (p:Person)-[:MADE]->(m)
        OPTIONAL MATCH (m)-[e:EVIDENCED_BY]->(r:SourceRecord)
        OPTIONAL MATCH (newer:Commitment)-[:SUPERSEDES]->(m)
        RETURN m.id AS commitment, m.text AS text, p.id AS made_by, p.name AS made_by_name, m.made_at AS made_at, m.valid_to AS valid_to,
               newer.id AS replaced_by, e.quote AS quote, r.uri AS source
        ORDER BY made_at DESC
        """,
        {"commitment": "Commitment", "made_by": "Person", "replaced_by": "Commitment"},
    ),
    "project_status": Query(
        "One project: who leads it, the services, changes, decisions and customers it involves, and incidents on its services.",
        """
        MATCH (j:Project {id: $project})
        OPTIONAL MATCH (lead:Person)-[:LEADS]->(j)
        OPTIONAL MATCH (j)-[:INVOLVES]->(s:Service)
        OPTIONAL MATCH (j)-[:INCLUDES]->(pr:PR)
        OPTIONAL MATCH (j)-[:FOLLOWS]->(d:Decision)
        OPTIONAL MATCH (j)-[:FOR]->(c:Customer)
        OPTIONAL MATCH (i:Incident)-[:AFFECTS]->(s)
        RETURN j.id AS project, j.name AS name, j.status AS status, j.goal AS goal, j.due_at AS due_at, lead.id AS lead, lead.name AS lead_name,
               collect(DISTINCT s.id) AS services, collect(DISTINCT pr.id) AS changes, collect(DISTINCT d.id) AS decisions,
               collect(DISTINCT c.id) AS customers, collect(DISTINCT i.id) AS incidents
        """,
        {"project": "Project", "lead": "Person", "services": "Service", "changes": "PR", "decisions": "Decision", "customers": "Customer", "incidents": "Incident"},
    ),
    "timeline": Query(
        "Everything dated that touches a service, oldest first: changes, deploys, decisions, incidents, mail and chats that name it.",
        """
        MATCH (s:Service {id: $service})-[r]-(x)
        WHERE x:PR OR x:Decision OR x:Incident OR x:Email OR x:Conversation OR x:Deploy OR x:Project
        RETURN DISTINCT labels(x)[0] AS kind, x.id AS item, coalesce(x.title, x.subject, x.name, x.id) AS title,
               coalesce(x.merged_at, x.decided_at, x.started_at, x.sent_at, x.at) AS at, type(r) AS link
        ORDER BY at
        """,
        {"item": "*kind"},
    ),
    "blast_radius": Query(
        "Services that depend on a service, directly or transitively, and the teams that own them.",
        """
        MATCH path = (s:Service {id: $service})<-[:DEPENDS_ON*1..5]-(u:Service)<-[:OWNS]-(t:Team)
        RETURN u.id AS service, t.id AS team, min(length(path)) - 1 AS hops
        ORDER BY hops, service
        """,
        {"service": "Service", "team": "Team"},
    ),
    "dependency_path": Query(
        "Shortest dependency path from one service to another.",
        """
        MATCH (a:Service {id: $source}), (b:Service {id: $target})
        WITH shortestPath((a)-[:DEPENDS_ON*]->(b)) AS path
        RETURN [n IN nodes(path) | n.id] AS via, length(path) AS hops
        """,
        {"via": "Service"},
    ),
    "critical_services": Query(
        "Services ranked by how much of the dependency graph runs through them (betweenness centrality).",
        """
        CALL algo.betweenness({nodeLabels: ['Service'], relationshipTypes: ['DEPENDS_ON']}) YIELD node, score
        RETURN node.id AS service, score ORDER BY score DESC, service LIMIT 5
        """,
        {"service": "Service"},
    ),
    "affected_customers": Query(
        "Customers using a feature served by a service or by anything that depends on it.",
        """
        MATCH (s:Service {id: $service})<-[:DEPENDS_ON*0..4]-(u:Service)<-[:SERVED_BY]-(f:Feature)<-[:USES]-(c:Customer)
        OPTIONAL MATCH (m:Person)-[:MANAGES_ACCOUNT]->(c)
        RETURN c.id AS customer, c.name AS name, c.plan AS plan, c.monthly_revenue AS monthly_revenue,
               m.id AS account_manager, m.name AS account_manager_name, collect(DISTINCT f.id) AS features
        ORDER BY monthly_revenue DESC
        """,
        {"customer": "Customer", "account_manager": "Person", "features": "Feature"},
    ),
    "sla_exposure": Query(
        "Contracts whose SLA covers an affected feature, with the monthly service credit at risk.",
        """
        MATCH (s:Service {id: $service})<-[:DEPENDS_ON*0..4]-(u:Service)<-[:SERVED_BY]-(f:Feature)<-[:COVERS]-(sla:SLA)<-[:GUARANTEES]-(k:Contract)<-[:HAS_CONTRACT]-(c:Customer)
        RETURN c.id AS customer, c.name AS name, k.id AS contract, sla.id AS sla,
               sla.uptime_target AS uptime_target, sla.credit_percent AS credit_percent,
               c.monthly_revenue AS monthly_revenue, collect(DISTINCT f.id) AS features,
               round(c.monthly_revenue * sla.credit_percent) / 100.0 AS credit_at_risk
        ORDER BY credit_at_risk DESC
        """,
        {"customer": "Customer", "contract": "Contract", "sla": "SLA", "features": "Feature"},
    ),
    "commitments_at_risk": Query(
        "Live promises made to customers affected by a service, with the exact sentence and where it was written.",
        """
        MATCH (s:Service {id: $service})<-[:DEPENDS_ON*0..4]-(:Service)<-[:SERVED_BY]-(:Feature)<-[:USES]-(c:Customer)<-[:MADE_TO]-(m:Commitment)<-[:MADE]-(p:Person)
        WHERE m.made_at <= $at AND (m.valid_to IS NULL OR m.valid_to >= $at)
        MATCH (m)-[e:EVIDENCED_BY]->(r:SourceRecord)
        RETURN DISTINCT m.id AS commitment, m.text AS text, c.id AS customer, c.name AS customer_name,
               p.id AS made_by, p.name AS made_by_name, m.made_at AS made_at, e.quote AS quote, r.uri AS source
        ORDER BY made_at DESC
        """,
        {"commitment": "Commitment", "customer": "Customer", "made_by": "Person"},
    ),
    "recall_playbooks": Query(
        "Playbooks learned from earlier incidents with the same symptom on this service or its dependencies.",
        """
        MATCH (s:Service {id: $service})-[:DEPENDS_ON*0..3]->(d:Service)<-[:APPLIES_TO]-(p:Playbook {symptom: $symptom})
        MATCH (p)-[:LEARNED_IN]->(v:Investigation)
        RETURN DISTINCT p.id AS playbook, d.id AS service, p.risk AS risk, p.tools AS tools,
               p.wins AS wins, p.losses AS losses, v.id AS learned_in
        ORDER BY wins - losses DESC, playbook
        """,
        {"playbook": "Playbook", "service": "Service", "learned_in": "Investigation"},
    ),
    "recall_facts": Query(
        "Facts learned in earlier investigations about a service or its dependencies.",
        """
        MATCH (s:Service {id: $service})-[:DEPENDS_ON*0..3]->(d:Service)<-[:ABOUT]-(f:Fact)
        WHERE f.valid_to IS NULL
        RETURN DISTINCT f.id AS fact, f.text AS text, d.id AS service, f.confidence AS confidence
        ORDER BY fact
        """,
        {"fact": "Fact", "service": "Service"},
    ),
    "code_impact": Query(
        "The functions, classes and constants a pull request changed, the code that uses each of them up to three calls away, and the tests that cover it.",
        """
        MATCH (:PR {id: $pr})-[:TOUCHES]->(c:Symbol)<-[:DEFINES]-(f:File {test: false})
        OPTIONAL MATCH (u)-[:REFERENCES*1..3]->(c)
        OPTIONAL MATCH (uf:File)-[:DEFINES*0..1]->(u)
        RETURN c.id AS symbol, c.name AS name, c.kind AS kind, f.id AS file, c.line AS line, c.code AS code,
               collect(DISTINCT CASE WHEN 'Symbol' IN labels(u) THEN u.id END) AS used_by,
               collect(DISTINCT CASE WHEN NOT uf.test THEN uf.id END) AS used_in,
               collect(DISTINCT CASE WHEN uf.test THEN uf.id END) AS tests
        ORDER BY file, line
        """,
        {"symbol": "Symbol", "file": "File", "used_by": "Symbol", "used_in": "File", "tests": "File"},
    ),
    "code_context": Query(
        "The code that runs alongside what a pull request changed: everything its users call, grouped by file.",
        """
        MATCH (:PR {id: $pr})-[:TOUCHES]->(c:Symbol)
        MATCH (c)<-[:REFERENCES*0..2]-(u)-[:REFERENCES*0..2]->(s:Symbol)<-[:DEFINES]-(f:File)
        RETURN f.id AS file, f.path AS path, f.test AS test, collect(DISTINCT s.id) AS symbols
        ORDER BY test, path
        """,
        {"file": "File", "symbols": "Symbol"},
    ),
    "code_history": Query(
        "Earlier pull requests that changed code a pull request's change runs through, up to two calls away.",
        """
        MATCH (:PR {id: $pr})-[:TOUCHES]->(c:Symbol)<-[:REFERENCES*0..2]-(u)-[:REFERENCES*0..2]->(s:Symbol)<-[:TOUCHES]-(earlier:PR)
        WHERE earlier.id <> $pr AND earlier.merged_at < $before
        OPTIONAL MATCH (a:Person)-[:AUTHORED]->(earlier)
        RETURN earlier.id AS pr, earlier.title AS title, earlier.merged_at AS merged_at, a.id AS author, a.name AS author_name,
               collect(DISTINCT s.id) AS symbols
        ORDER BY merged_at DESC
        """,
        {"pr": "PR", "author": "Person", "symbols": "Symbol"},
    ),
    "change_reach": Query(
        "Everything one pull request can reach: from the code it touched to its service, the services that depend on it, the features they serve, and the customers, SLAs and promises live when it merged.",
        """
        MATCH (pr:PR {id: $pr})-[:CHANGES]->(s:Service)
        OPTIONAL MATCH (pr)-[:TOUCHES]->(c:Symbol)
        WITH pr, s, collect(DISTINCT c.id) AS symbols
        MATCH path = (up:Service)-[:DEPENDS_ON*0..3]->(s)
        OPTIONAL MATCH (up)<-[:SERVED_BY]-(f:Feature)<-[:USES]-(cu:Customer)
        OPTIONAL MATCH (cu)-[:HAS_CONTRACT]->(:Contract)-[:GUARANTEES]->(sla:SLA)-[:COVERS]->(f)
        OPTIONAL MATCH (cm:Commitment)-[:MADE_TO]->(cu)
        WHERE cm.made_at <= pr.merged_at
        RETURN symbols, up.id AS service, min(length(path)) AS hops, collect(DISTINCT f.id) AS features,
               collect(DISTINCT cu.id) AS customers, collect(DISTINCT sla.id) AS slas, collect(DISTINCT cm.id) AS commitments
        ORDER BY hops, service
        """,
        {"symbols": "Symbol", "service": "Service", "features": "Feature", "customers": "Customer", "slas": "SLA", "commitments": "Commitment"},
    ),
    "areas": Query(
        "The parts the company's graph falls into, largest first, each with a summary. Use it for broad questions about the company as a whole.",
        """
        MATCH (a:Area)
        RETURN a.id AS area, a.title AS title, a.summary AS summary, a.size AS size, a.members AS most_connected
        ORDER BY size DESC
        """,
        {"area": "Area"},
    ),
}

HIDDEN = ["SourceRecord", "Source", "Identity", "Step", "Task"]


def run(graph: Graph, name: str, **params) -> list[dict]:
    return read(graph, QUERIES[name].cypher, **params)


WRITTEN = "graph_query"
WRITTEN_DOC = "Run one read-only Cypher query you write yourself, for questions no other tool answers. Use only the labels, links and properties in the schema. Return plain properties, always with the id, and end with a LIMIT."
WRITTEN_ROWS = 50
WRITTEN_TIMEOUT_MS = 2000
# What the agents and the chat write for themselves; left out of the schema a model is shown
WORKING = ["Action", "Finding", "Hypothesis", "Investigation", "Playbook", "PlaybookStep", "Remediation", "Session", "Turn", "User", "Symbol", "File", "Area", "Note", "Fact"]


def schema(graph: Graph) -> str:
    """Labels with their properties and the links between them, read from what the graph holds now."""
    # ponytail: two full scans per question; cache per tenant once a graph is too large for that
    left_out = HIDDEN + WORKING
    properties: dict[str, set] = {}
    for row in read(graph, "MATCH (n) WHERE NOT labels(n)[0] IN $left_out RETURN DISTINCT labels(n)[0] AS label, keys(n) AS properties", left_out=left_out):
        properties.setdefault(row["label"], set()).update(row["properties"])
    links: dict[tuple, set] = {}
    for row in read(graph, "MATCH (a)-[r]->(b) WHERE NOT labels(a)[0] IN $left_out AND NOT labels(b)[0] IN $left_out RETURN DISTINCT labels(a)[0] AS a, type(r) AS link, labels(b)[0] AS b", left_out=left_out):
        links.setdefault((row["a"], row["link"]), set()).add(row["b"])
    return "\n".join([*[f"(:{label} {{{', '.join(sorted(names))}}})" for label, names in sorted(properties.items())], *[f"(:{a})-[:{link}]->(:{'|'.join(sorted(to))})" for (a, link), to in sorted(links.items())]])


def written(graph: Graph, cypher: str, hidden: frozenset[str] = frozenset(), records: frozenset[str] = frozenset()) -> list[dict]:
    """Runs model-written Cypher read-only with a time limit and a row cap, on a copy without whatever this viewer may not see."""
    if not hidden and not records:
        return _read_only(graph, cypher)
    # ponytail: one graph copy per query for viewers with hidden items; keep a copy per viewer once graphs are large
    view = graph.copy(f"view:{uuid4().hex}")
    try:
        view.query("MATCH (n) WHERE labels(n)[0] + ':' + n.id IN $hidden OR (n:SourceRecord AND n.id IN $records) DETACH DELETE n", {"hidden": list(hidden), "records": list(records)})
        return _read_only(view, cypher)
    finally:
        view.delete()


def _read_only(graph: Graph, cypher: str) -> list[dict]:
    try:
        result = graph.ro_query(cypher, timeout=WRITTEN_TIMEOUT_MS)
    except ResponseError as problem:
        raise ValueError(str(problem)) from problem
    columns = [column[1] for column in result.header]
    return [dict(zip(columns, map(_plain, row))) for row in result.result_set[:WRITTEN_ROWS]]


def _plain(value):
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return getattr(value, "properties", value)


def written_refs(graph: Graph, rows: list[dict]) -> list[str]:
    """The things the rows name, found by matching returned values to ids in the graph."""
    values = {item for row in rows for value in row.values() for item in (value if isinstance(value, list) else [value]) if isinstance(item, str)}
    return [row["ref"] for row in read(graph, "MATCH (n) WHERE n.id IN $values AND NOT labels(n)[0] IN $hidden RETURN labels(n)[0] + ':' + n.id AS ref", values=list(values), hidden=HIDDEN)]


def refs(name: str, rows: list[dict]) -> list[str]:
    found: dict[str, None] = {}
    for row in rows:
        for column, label in QUERIES[name].refs.items():
            value = row.get(column)
            if label.startswith("*"):
                label = row.get(label[1:])
            for id in value if isinstance(value, list) else [value]:
                if id is not None and label:
                    found[f"{label}:{id}"] = None
    return list(found)


def redact(name: str, rows: list[dict], hidden: frozenset[str]) -> tuple[list[dict], int]:
    """Rows about a hidden thing are dropped and hidden ids leave list columns; also returns how many were taken out."""
    kept, withheld = [], 0
    for row in rows if hidden else []:
        row, gone = dict(row), False
        for column, label in QUERIES[name].refs.items():
            label = row.get(label[1:]) if label.startswith("*") else label
            if isinstance(row.get(column), list):
                seen = [id for id in row[column] if f"{label}:{id}" not in hidden]
                withheld += len(row[column]) - len(seen)
                row[column] = seen
            elif f"{label}:{row.get(column)}" in hidden:
                gone = True
        withheld += gone
        if not gone:
            kept.append(row)
    return (kept, withheld) if hidden else (rows, 0)


def find_entity(graph: Graph, text: str) -> list[dict]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    if not words:
        return []
    by_id = read(
        graph,
        "MATCH (n) WHERE toLower(n.id) = $id AND labels(n)[0] IN $labels "
        "RETURN labels(n)[0] AS kind, n.id AS id, coalesce(n.name, n.title, n.subject, n.text, n.id) AS name, 100.0 AS score",
        id=text.strip().lower(), labels=list(FULLTEXT),
    )
    text = " ".join(f"{word}*" if len(word) > 1 else word for word in words)
    matches = by_id
    for label in FULLTEXT:
        try:
            matches += read(
                graph,
                "CALL db.idx.fulltext.queryNodes($label, $text) YIELD node, score "
                "RETURN $label AS kind, node.id AS id, coalesce(node.name, node.title, node.subject, node.text, node.id) AS name, score",
                label=label, text=text,
            )
        except ResponseError:
            continue
    unique = {(match["kind"], match["id"]): match for match in sorted(matches, key=lambda match: match["score"])}
    return sorted(unique.values(), key=lambda match: -match["score"])[:20]


def entity(graph: Graph, kind: str, id: str) -> dict | None:
    _check(kind)
    found = read(graph, f"MATCH (n:{kind} {{id: $id}}) RETURN properties(n) AS props", id=id)
    if not found:
        return None
    neighbours = read(
        graph,
        f"""
        MATCH (n:{kind} {{id: $id}})-[r]-(m)
        WHERE NOT labels(m)[0] IN $hidden
        RETURN type(r) AS relation, startNode(r) = n AS outgoing, labels(m)[0] AS kind, m.id AS id,
               coalesce(m.name, m.title, m.subject, m.text, m.statement, m.claim, m.id) AS name, r.quote AS quote, r.src AS src,
               coalesce(m.merged_at, m.decided_at, m.made_at, m.sent_at, m.started_at, m.starts_at, m.at, m.written_at, r.starts_at) AS at
        ORDER BY relation, kind, id
        """,
        id=id, hidden=HIDDEN,
    )
    sources = read(
        graph,
        f"""
        MATCH (n:{kind} {{id: $id}})-[e:EVIDENCED_BY]->(r:SourceRecord)-[:FROM]->(s:Source)
        OPTIONAL MATCH (p:Person)-[:CAN_READ]->(r)
        RETURN s.name AS source, r.id AS record, r.uri AS uri, e.quote AS quote, r.fetched_at AS fetched_at,
               coalesce(r.visibility, 'org') AS visibility, collect(p.name) AS readers
        """,
        id=id,
    )
    return {"kind": kind, "id": id, "props": found[0]["props"], "neighbours": neighbours, "sources": sources}


def _check(kind: str) -> None:
    if kind not in LABELS:
        raise ValueError(f"unknown kind: {kind}")
