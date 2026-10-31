import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from falkordb import Graph

from ripple import access, queries
from ripple.graph import now, read, write


CORRELATION_WINDOW = timedelta(hours=6)


def parse_alerts(payload: dict) -> list[dict]:
    """Alertmanager webhook payload to the fields an investigation needs."""
    return [
        {
            "service": alert["labels"]["service"],
            "symptom": alert["labels"]["alertname"],
            "severity": alert["labels"].get("severity", "warning"),
            "summary": alert["annotations"]["summary"],
            "at": _second_precision_utc(alert["startsAt"]),
        }
        for alert in payload["alerts"]
        if alert["status"] == "firing"
    ]


def _second_precision_utc(stamp: str, back: timedelta = timedelta(0)) -> str:
    return (datetime.fromisoformat(stamp).astimezone(UTC) - back).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve(graph: Graph, investigation: str, user: str) -> dict:
    """A human closes an incident that no merged change closed, such as a vendor outage that ended."""
    closed = write(
        graph,
        """
        MATCH (v:Investigation {id: $id, status: 'confirmed'})-[:INVESTIGATES]->(i:Incident {status: 'open'})
        SET i.status = 'resolved', i.resolved_at = $at, i.resolved_by = $user
        RETURN i.id AS incident, i.resolved_at AS resolved_at
        """,
        id=investigation, user=user, at=now(),
    )
    if not closed:
        raise ValueError(f"{investigation} must have a confirmed root cause and an open incident to be resolved")
    return closed[0]


def open_incident(graph: Graph, alert: dict) -> tuple[str, bool]:
    """Returns the investigation id and whether a new incident was opened for this alert."""
    alert_id = f"ALERT-{alert['service']}-{alert['at']}"
    # ponytail: lookup and create are two statements; two alerts in the same millisecond could open two incidents
    existing = read(
        graph,
        """
        MATCH (s:Service {id: $service})-[:DEPENDS_ON*0..3]-(:Service)<-[:AFFECTS]-(i:Incident {status: 'open'})<-[:INVESTIGATES]-(v:Investigation)
        WHERE i.started_at <= $at AND i.started_at >= $since
        RETURN v.id AS id, i.id AS incident LIMIT 1
        """,
        service=alert["service"], at=alert["at"], since=_second_precision_utc(alert["at"], back=CORRELATION_WINDOW),
    )
    if existing:
        write(
            graph,
            """
            MATCH (s:Service {id: $service}), (i:Incident {id: $incident})
            MERGE (a:Alert {id: $alert}) SET a.name = $symptom, a.severity = $severity, a.summary = $summary, a.at = $at, a.origin = $origin
            MERGE (a)-[:FIRED_ON]->(s) MERGE (i)-[:TRIGGERED_BY]->(a)
            """,
            incident=existing[0]["incident"], alert=alert_id, **{"origin": ""} | alert,
        )
        return existing[0]["id"], False
    created = write(
        graph,
        """
        MATCH (s:Service {id: $service})
        OPTIONAL MATCH (i:Incident)
        WITH s, toString(coalesce(max(toInteger(substring(i.id, 4))), 0) + 1) AS n
        CREATE (a:Alert {id: $alert, name: $symptom, severity: $severity, summary: $summary, at: $at, origin: $origin})-[:FIRED_ON]->(s)
        CREATE (opened:Incident {id: 'INC-' + n, title: $summary, started_at: $at, status: 'open', symptom: $symptom})-[:AFFECTS]->(s)
        CREATE (opened)-[:TRIGGERED_BY]->(a)
        CREATE (v:Investigation {id: 'INV-' + n, status: 'running', started_at: $now, service: $service,
                                 at: $at, symptom: $symptom, incident: 'INC-' + n, steps: 0, tasks: 0})-[:INVESTIGATES]->(opened)
        RETURN v.id AS id
        """,
        alert=alert_id, now=now(), **{"origin": ""} | alert,
    )
    investigation = created[0]["id"]
    add_task(graph, investigation, "triage", stage=1)
    return investigation, True


def add_task(graph: Graph, investigation: str, kind: str, stage: int, **payload) -> str:
    return write(
        graph,
        """
        MATCH (v:Investigation {id: $inv})
        SET v.tasks = v.tasks + 1
        WITH v
        CREATE (v)-[:HAS_TASK]->(t:Task {id: v.id + ':T' + toString(v.tasks), kind: $kind, stage: $stage,
                                         status: 'open', payload: $payload, created_at: $at})
        RETURN t.id AS id
        """,
        inv=investigation, kind=kind, stage=stage, payload=json.dumps(payload), at=now(),
    )[0]["id"]


def claim_task(graph: Graph, investigation: str, agent: str, kinds: list[str] | None = None) -> dict | None:
    """One statement, so two agents can never claim the same task. Later stages wait for earlier ones."""
    claimed = write(
        graph,
        """
        MATCH (v:Investigation {id: $inv})-[:HAS_TASK]->(u:Task)
        WHERE u.status IN ['open', 'claimed']
        WITH v, min(u.stage) AS stage
        MATCH (v)-[:HAS_TASK]->(t:Task {status: 'open'})
        WHERE t.stage = stage AND ($kinds IS NULL OR t.kind IN $kinds)
        WITH t ORDER BY t.id LIMIT 1
        SET t.status = 'claimed', t.claimed_by = $agent, t.claimed_at = $at
        RETURN t.id AS id, t.kind AS kind, t.payload AS payload
        """,
        inv=investigation, agent=agent, kinds=kinds, at=now(),
    )
    if not claimed:
        return None
    return {**claimed[0], "payload": json.loads(claimed[0]["payload"])}


def finish_task(graph: Graph, task: str, status: str, summary: str) -> None:
    write(graph, "MATCH (t:Task {id: $id}) SET t.status = $status, t.summary = $summary, t.finished_at = $at", id=task, status=status, summary=summary, at=now())


def release_stale_tasks(graph: Graph, investigation: str, claimed_before: str) -> int:
    return write(
        graph,
        """
        MATCH (:Investigation {id: $inv})-[:HAS_TASK]->(t:Task {status: 'claimed'})
        WHERE t.claimed_at < $before
        SET t.status = 'open', t.claimed_by = NULL
        RETURN count(t) AS released
        """,
        inv=investigation, before=claimed_before,
    )[0]["released"]


def unfinished_tasks(graph: Graph, investigation: str) -> int:
    return read(
        graph,
        "MATCH (:Investigation {id: $inv})-[:HAS_TASK]->(t:Task) WHERE t.status IN ['open', 'claimed'] RETURN count(t) AS n",
        inv=investigation,
    )[0]["n"]


def touched(graph: Graph, investigation: str) -> set[str]:
    return {
        f"{row['kind']}:{row['id']}"
        for row in read(
            graph,
            "MATCH (:Investigation {id: $inv})-[:HAS_STEP]->(:Step)-[:TOUCHED]->(n) RETURN DISTINCT labels(n)[0] AS kind, n.id AS id",
            inv=investigation,
        )
    }


def split(ref: str) -> tuple[str, str]:
    kind, _, id = ref.partition(":")
    return kind, id


def by_kind(refs: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for ref in refs:
        kind, id = split(ref)
        grouped.setdefault(kind, []).append(id)
    return grouped


class UncitedClaim(ValueError):
    pass


@dataclass
class Context:
    graph: Graph
    investigation: str
    agent: str
    incident: str
    service: str
    at: str
    symptom: str
    delay: float = 0.0

    @classmethod
    def load(cls, graph: Graph, investigation: str, agent: str, delay: float = 0.0) -> "Context":
        row = read(graph, "MATCH (v:Investigation {id: $id}) RETURN v.incident AS incident, v.service AS service, v.at AS at, v.symptom AS symptom", id=investigation)[0]
        return cls(graph, investigation, agent, delay=delay, **row)

    def root(self) -> dict:
        return read(
            self.graph,
            "MATCH (v:Investigation {id: $id}) RETURN v.root_kind AS kind, v.root_id AS id, v.root_service AS service, v.root_title AS title",
            id=self.investigation,
        )[0]

    def tool(self, name: str, **params) -> list[dict]:
        if self.delay:
            time.sleep(self.delay)
        rows, _ = queries.redact(name, queries.run(self.graph, name, **params), access.view(self.graph, None).hidden)
        self.step(name, params, rows, queries.refs(name, rows))
        return rows

    def step(self, tool: str, params: dict, rows: list[dict], refs: list[str]) -> str:
        step = write(
            self.graph,
            """
            MATCH (v:Investigation {id: $inv})
            SET v.steps = v.steps + 1
            WITH v
            CREATE (v)-[:HAS_STEP]->(st:Step {id: v.id + ':S' + toString(v.steps), seq: v.steps, agent: $agent,
                                              tool: $tool, params: $params, result: $result, rows: $rows, at: $at})
            WITH v, st
            OPTIONAL MATCH (v)-[:HAS_STEP]->(prev:Step {seq: st.seq - 1})
            FOREACH (p IN CASE WHEN prev IS NULL THEN [] ELSE [prev] END | CREATE (p)-[:NEXT]->(st))
            RETURN st.id AS id
            """,
            inv=self.investigation, agent=self.agent, tool=tool, params=json.dumps(params),
            result=json.dumps(rows), rows=len(rows), at=now(),
        )[0]["id"]
        for kind, ids in by_kind(refs).items():
            write(self.graph, f"MATCH (st:Step {{id: $step}}) UNWIND $ids AS id MATCH (n:{kind} {{id: id}}) MERGE (st)-[:TOUCHED]->(n)", step=step, ids=ids)
        return step

    def shared(self, tool: str) -> list[dict]:
        """Latest result any agent on this investigation got from a tool."""
        found = read(
            self.graph,
            "MATCH (:Investigation {id: $inv})-[:HAS_STEP]->(st:Step {tool: $tool}) RETURN st.result AS result ORDER BY st.seq DESC LIMIT 1",
            inv=self.investigation, tool=tool,
        )
        return json.loads(found[0]["result"]) if found else []

    def task(self, kind: str, stage: int, **payload) -> str:
        return add_task(self.graph, self.investigation, kind, stage, **payload)

    def hypothesis(self, subject: str, statement: str, score: float, factors: dict, supports: list[str]) -> str:
        id = f"{self.investigation}:H:{subject}"
        kind, subject_id = split(subject)
        write(
            self.graph,
            f"""
            MATCH (v:Investigation {{id: $inv}}), (n:{kind} {{id: $subject}})
            MERGE (h:Hypothesis {{id: $id}})
            SET h.statement = $statement, h.score = $score, h.factors = $factors, h.subject = $ref,
                h.status = coalesce(h.status, 'open'), h.agent = $agent
            MERGE (v)-[:HAS_HYPOTHESIS]->(h) MERGE (h)-[:ABOUT]->(n)
            """,
            inv=self.investigation, id=id, subject=subject_id, ref=subject, statement=statement,
            score=round(score, 3), factors=json.dumps(factors), agent=self.agent,
        )
        self._link(id, "Hypothesis", "SUPPORTED_BY", supports)
        return id

    def finding(self, kind: str, key: str, claim: str, cites: list[str], **props) -> str:
        """A claim is only stored if every node it cites was returned by a tool in this investigation."""
        unseen = set(cites) - touched(self.graph, self.investigation)
        if not cites or unseen:
            raise UncitedClaim(f"finding {kind}/{key} cites nothing fetched by a tool: {sorted(unseen) or 'no citations'}")
        id = f"{self.investigation}:F:{kind}:{key}"
        write(
            self.graph,
            """
            MATCH (v:Investigation {id: $inv})
            MERGE (f:Finding {id: $id})
            SET f.kind = $kind, f.claim = $claim, f.agent = $agent, f.at = $at, f += $props
            MERGE (v)-[:HAS_FINDING]->(f)
            WITH f OPTIONAL MATCH (f)-[old:CITES]->() DELETE old
            """,
            inv=self.investigation, id=id, kind=kind, claim=claim, agent=self.agent, at=now(), props=props,
        )
        self._link(id, "Finding", "CITES", cites)
        return id

    def _link(self, id: str, label: str, relation: str, refs: list[str]) -> None:
        for kind, ids in by_kind(refs).items():
            write(self.graph, f"MATCH (x:{label} {{id: $id}}) UNWIND $ids AS target MATCH (n:{kind} {{id: target}}) MERGE (x)-[:{relation}]->(n)", id=id, ids=ids)


def state(graph: Graph, investigation: str) -> dict | None:
    """Everything the incident room shows, read straight from the investigation subgraph."""
    head = read(
        graph,
        "MATCH (v:Investigation {id: $id})-[:INVESTIGATES]->(i:Incident) RETURN properties(v) AS investigation, properties(i) AS incident",
        id=investigation,
    )
    if not head:
        return None

    def collect(relation: str, order: str, extra: str = "") -> list[dict]:
        rows = read(
            graph,
            f"MATCH (:Investigation {{id: $id}})-[:{relation}]->(n) {extra} RETURN properties(n) AS props{', refs' if extra else ''} ORDER BY {order}",
            id=investigation,
        )
        return [{**row["props"], **({"refs": row["refs"]} if extra else {})} for row in rows]

    def with_refs(relation: str) -> str:
        return f"OPTIONAL MATCH (n)-[:{relation}]->(m) WITH n, collect(labels(m)[0] + ':' + m.id) AS refs"

    steps = collect("HAS_STEP", "n.seq", with_refs("TOUCHED"))
    for step in steps:
        step["params"], step["result"] = json.loads(step["params"]), json.loads(step["result"])
    hypotheses = collect("HAS_HYPOTHESIS", "n.score DESC", with_refs("SUPPORTED_BY"))
    for hypothesis in hypotheses:
        hypothesis["factors"] = json.loads(hypothesis["factors"])
    tasks = collect("HAS_TASK", "n.id")
    for task in tasks:
        task["payload"] = json.loads(task["payload"])
    return {
        **head[0],
        "tasks": tasks,
        "steps": steps,
        "hypotheses": hypotheses,
        "findings": collect("HAS_FINDING", "n.at", with_refs("CITES")),
        "actions": collect("PROPOSED", "n.id", "WHERE n:Action " + with_refs("JUSTIFIED_BY")),
        "remediations": collect("PROPOSED", "n.id", "WHERE n:Remediation OPTIONAL MATCH (n)-[r:RESPECTS|REOPENS_RISK_OF|REVERTS]->(m) WITH n, collect(type(r) + ':' + labels(m)[0] + ':' + m.id) AS refs"),
        "canvas": canvas(graph, investigation),
    }


def canvas(graph: Graph, investigation: str) -> dict:
    """The whole incident: what any step touched, the company-graph edges among it, and the fixes and messages proposed."""
    nodes = read(
        graph,
        """
        MATCH (:Investigation {id: $id})-[:HAS_STEP]->(st:Step)-[:TOUCHED]->(n)
        RETURN labels(n)[0] AS kind, n.id AS id, coalesce(n.name, n.title, n.text, n.id) AS name, min(st.seq) AS first_seq
        ORDER BY first_seq
        """,
        id=investigation,
    )
    edges = read(
        graph,
        """
        MATCH (v:Investigation {id: $id})-[:HAS_STEP]->(:Step)-[:TOUCHED]->(a)
        MATCH (a)-[r]->(b)<-[:TOUCHED]-(:Step)<-[:HAS_STEP]-(v)
        WHERE NOT type(r) IN ['MENTIONS', 'HAS_IDENTITY', 'EVIDENCED_BY']
        RETURN DISTINCT labels(a)[0] + ':' + a.id AS source, type(r) AS relation, labels(b)[0] + ':' + b.id AS target
        """,
        id=investigation,
    )
    fixes = read(
        graph,
        """
        MATCH (:Investigation {id: $id})-[:PROPOSED]->(f:Remediation)
        OPTIONAL MATCH (f)-[r:REVERTS|RESPECTS|REOPENS_RISK_OF]->(m)
        RETURN f.id AS id, f.title AS name, [x IN collect({relation: type(r), target: labels(m)[0] + ':' + m.id}) WHERE x.relation IS NOT NULL] AS links
        ORDER BY id
        """,
        id=investigation,
    )
    messages = read(
        graph,
        """
        MATCH (:Investigation {id: $id})-[:PROPOSED]->(a:Action)
        OPTIONAL MATCH (a)-[:JUSTIFIED_BY]->(:Finding)-[:CITES]->(c:Customer)
        RETURN a.id AS id, a.kind AS kind, a.to AS to, collect(DISTINCT c.id) AS customers
        ORDER BY id
        """,
        id=investigation,
    )
    for fix in fixes:
        nodes.append({"kind": "Fix", "id": fix["id"], "name": fix["name"]})
        edges += [{"source": f"Fix:{fix['id']}", **link} for link in fix["links"]]
    for message in messages:
        key = message["id"].rsplit(":", 1)[1]
        label = message["kind"].replace("_", " ").capitalize()
        nodes.append({"kind": "Message", "id": message["id"], "name": label if label == message["to"] else f"{label} to {message['to']}"})
        reaches = {"customer_notice": [("SENT_TO", f"Customer:{key}")], "page": [("PAGES", f"Person:{key}")]}.get(message["kind"], [("ABOUT", f"Customer:{customer}") for customer in message["customers"]])
        edges += [{"source": f"Message:{message['id']}", "relation": relation, "target": target} for relation, target in reaches]
    return {"nodes": nodes, "edges": edges}
