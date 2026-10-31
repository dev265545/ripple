from datetime import datetime, timedelta

from falkordb import Graph

from ripple.graph import now, read, write

VERIFIABLE = ["Commitment", "Decision", "Fact", "Note", "Doc", "Playbook"]
INTERVALS = [30, 90, 180, 365]
STAMP = "%Y-%m-%dT%H:%M:%SZ"
STANDING = """
    OPTIONAL MATCH (maker:Person)-[:MADE|DECIDED]->(n)
    OPTIONAL MATCH (n)-[:EVIDENCED_BY]->(r:SourceRecord)
    RETURN labels(n)[0] AS kind, n.id AS id, coalesce(n.text, n.title, n.id) AS name, coalesce(n.owner, maker.id) AS owner,
           n.verified_by AS verified_by, n.verified_at AS verified_at, n.verify_days AS days, r.fetched_at AS changed_at
"""


def _standing(graph: Graph, match: str, **params) -> list[dict]:
    # FalkorDB 4.x panics when never-set properties are grouping keys beside an aggregate, so the latest change is taken here.
    latest: dict[tuple[str, str], dict] = {}
    for row in read(graph, f"{match} {STANDING}", **params):
        known = latest.setdefault((row["kind"], row["id"]), row)
        known["changed_at"] = max(filter(None, [known["changed_at"], row["changed_at"]]), default=None)
    return [_judged(row) for row in latest.values()]


def _judged(row: dict) -> dict:
    """Read at the time of asking, so nothing has to run for a verification to lapse."""
    due_at = (datetime.strptime(row["verified_at"], STAMP) + timedelta(days=row["days"])).strftime(STAMP) if row["verified_at"] and row["days"] else None
    if not row["verified_at"]:
        state = "unverified"
    elif row["changed_at"] and row["changed_at"] > row["verified_at"]:
        state = "changed"
    else:
        state = "expired" if due_at and due_at < now() else "verified"
    return row | {"state": state, "due_at": due_at}


def of(graph: Graph, kind: str, id: str) -> dict | None:
    if kind not in VERIFIABLE:
        return None
    found = _standing(graph, f"MATCH (n:{kind} {{id: $id}})", id=id)
    return found[0] if found else None


def verify(graph: Graph, kind: str, id: str, user: str, days: int | None) -> dict:
    """The owner says this is still right, for a number of days or until it changes. Something nobody owns goes to whoever verifies it."""
    current = of(graph, kind, id)
    if current is None or days not in [None, *INTERVALS]:
        raise ValueError(f"cannot verify {kind} {id} for {days} days")
    if current["owner"] and current["owner"] != user:
        raise PermissionError(f"Only its owner, {current['owner']}, can verify this.")
    if not write(graph, f"MATCH (p:Person {{id: $user}}), (n:{kind} {{id: $id}}) SET n.owner = p.id, n.verified_by = p.id, n.verified_at = $at, n.verify_days = $days RETURN 1 AS done", id=id, user=user, at=now(), days=days):
        raise PermissionError("Only someone in the company directory can verify.")
    return of(graph, kind, id)


def lapsed(graph: Graph) -> list[dict]:
    return [row for row in _standing(graph, "MATCH (n) WHERE n.verified_at IS NOT NULL") if row["state"] != "verified"]


def to_check(graph: Graph, person: str) -> list[dict]:
    """What this person owns that is in force and not verified, or was verified and has lapsed or changed since."""
    # ponytail: reads every verifiable node and filters here; match on a stored owner if a tenant holds tens of thousands
    rows = _standing(graph, "MATCH (n) WHERE labels(n)[0] IN $kinds AND (n.valid_to IS NULL OR n.valid_to >= $at) AND coalesce(n.status, '') <> 'superseded'", kinds=VERIFIABLE, at=now())
    return sorted((row for row in rows if row["owner"] == person and row["state"] != "verified"), key=lambda row: (row["kind"], row["id"]))
