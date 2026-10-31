import re
from datetime import UTC, datetime, timedelta

from falkordb import Graph

from ripple import areas, ingest, trust
from ripple.graph import now, read, write

MEASURE = re.compile(r"(\d{1,2}:\d{2}|\d+(?:\.\d+)?)\s?(%|percent|minutes?|hours?|working days?|business days?|days?|UTC)", re.I)
SUBJECTS = ["Service", "Feature"]
SOURCE_GOES_QUIET_AFTER = timedelta(days=7)
ONE_ONLY = {
    "is owned by more than one team": "MATCH (holder:Team)-[e:OWNS]->(subject:Service)",
    "has more than one account manager": "MATCH (holder:Person)-[e:MANAGES_ACCOUNT]->(subject:Customer)",
    "reports to more than one manager": "MATCH (subject:Person)-[e:REPORTS_TO]->(holder:Person)",
}


def upkeep(graph: Graph) -> None:
    """Run after anything is read in: the areas are re-clustered and promises that disagree are queued for a human."""
    areas.refresh(graph)
    propose(graph)


def _measures(text: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for number, unit in MEASURE.findall(text):
        found.setdefault(unit.lower().rstrip("s"), set()).add(number)
    return found


def _disagreement(graph: Graph, newer: str, older: str) -> str | None:
    """Same thing named, same measure, different number. Needs no model, and misses anything said in words alone."""
    named = [{entity["id"] for entity in ingest.named_entities(graph, text) if entity["kind"] in SUBJECTS} for text in (newer, older)]
    shared = sorted(named[0] & named[1])
    ours, theirs = _measures(newer), _measures(older)
    for unit in sorted(ours.keys() & theirs.keys()):
        if shared and ours[unit].isdisjoint(theirs[unit]):
            return f"Both name {shared[0]}; the older says {' and '.join(sorted(theirs[unit]))} {unit}, the newer says {' and '.join(sorted(ours[unit]))} {unit}."
    return None


def propose(graph: Graph) -> int:
    """Pairs go to the same review queue a model's suspicions do; one a human has already ruled on is not raised again."""
    pairs = read(
        graph,
        """
        MATCH (a:Commitment)-[:MADE_TO]->(:Customer)<-[:MADE_TO]-(b:Commitment)
        WHERE a.made_at > b.made_at AND (a.valid_to IS NULL OR a.valid_to >= $at) AND (b.valid_to IS NULL OR b.valid_to >= $at)
          AND NOT (a)-[:SUPERSEDES|BOTH_STAND]-(b)
        RETURN a.id AS newer, a.text AS newer_text, b.id AS older, b.text AS older_text
        """,
        at=now(),
    )
    proposed = 0
    for pair in pairs:
        reason = _disagreement(graph, pair["newer_text"], pair["older_text"])
        if reason:
            write(
                graph,
                "MATCH (a:Commitment {id: $newer}), (b:Commitment {id: $older}) MERGE (a)-[e:SUPERSEDES]->(b) SET e.proposed = true, e.proposed_at = $at, e.found_by = 'rule', e.reason = $reason",
                newer=pair["newer"], older=pair["older"], at=now(), reason=reason,
            )
            proposed += 1
    return proposed


def findings(graph: Graph) -> list[dict]:
    """Things the graph itself shows are in conflict or out of date. Every one is a query; none is a model's opinion."""
    at = now()
    found = []
    for problem, match in ONE_ONLY.items():
        for row in read(graph, f"{match} RETURN labels(subject)[0] + ':' + subject.id AS subject, subject.id AS name, collect(DISTINCT labels(holder)[0] + ':' + holder.id) AS holders, collect(DISTINCT e.src) AS records"):
            if len(row["holders"]) > 1:
                found.append({"kind": "conflict", "text": f"{row['name']} {problem}.", "refs": [row["subject"], *sorted(row["holders"])], "records": sorted(row["records"])})
    for row in read(graph, "MATCH (j:Project)-[:FOLLOWS]->(d:Decision {status: 'superseded'}) RETURN j.id AS project, j.name AS name, d.id AS decision"):
        found.append({"kind": "conflict", "text": f"{row['name']} still follows {row['decision']}, which has been replaced.", "refs": [f"Project:{row['project']}", f"Decision:{row['decision']}"], "records": []})
    for row in read(graph, "MATCH (:Person)-[o:ON_CALL_FOR]->(s:Service) RETURN s.id AS service, max(o.ends_at) AS ended, max(CASE WHEN o.starts_at <= $at AND o.ends_at >= $at THEN 1 ELSE 0 END) AS covered ORDER BY service", at=at):
        if not row["covered"]:
            found.append({"kind": "stale", "text": f"Nobody is on call for {row['service']}: the last shift on the schedule ended {row['ended'][:10]}.", "refs": [f"Service:{row['service']}"], "records": []})
    for row in read(graph, "MATCH (j:Project {status: 'active'}) WHERE j.due_at < $day RETURN j.id AS project, j.name AS name, j.due_at AS due_at ORDER BY due_at", day=at[:10]):
        found.append({"kind": "stale", "text": f"{row['name']} is still marked active and was due {row['due_at']}.", "refs": [f"Project:{row['project']}"], "records": []})
    quiet = (datetime.now(UTC) - SOURCE_GOES_QUIET_AFTER).strftime(trust.STAMP)
    for row in read(graph, "MATCH (s:Source) WHERE s.last_sync < $quiet RETURN s.name AS name, s.last_sync AS at ORDER BY at", quiet=quiet):
        found.append({"kind": "stale", "text": f"{row['name']} was last read on {row['at'][:10]}; what it says may have moved on.", "refs": [], "records": []})
    for row in trust.lapsed(graph):
        why = "its source changed after that" if row["state"] == "changed" else f"that ran out on {row['due_at'][:10]}"
        found.append({"kind": "stale", "text": f"\"{row['name']}\" was verified by {row['verified_by']} on {row['verified_at'][:10]} and {why}.", "refs": [f"{row['kind']}:{row['id']}"], "records": []})
    return found
