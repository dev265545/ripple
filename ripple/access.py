from dataclasses import dataclass

from falkordb import Graph

from ripple.graph import now, read, write


@dataclass(frozen=True)
class View:
    """What one person may not see: records they cannot read, and things backed only by those records."""

    viewer: str | None
    records: frozenset[str] = frozenset()
    hidden: frozenset[str] = frozenset()

    def sees(self, ref: str) -> bool:
        return ref not in self.hidden

    def only_seen(self, rows: list[dict], *columns: str) -> list[dict]:
        return [row for row in rows if all(row.get(column) not in self.hidden and row.get(column) not in self.records for column in columns)]


def view(graph: Graph, viewer: str | None) -> View:
    """No viewer is the view of the whole company: everything that has not been restricted to named people."""
    # ponytail: two scans of the restricted records per request; cache per viewer if a tenant holds thousands of private items
    records = frozenset(
        row["id"]
        for row in read(graph, "MATCH (r:SourceRecord {visibility: 'restricted'}) WHERE NOT (:Person {id: $viewer})-[:CAN_READ]->(r) RETURN r.id AS id", viewer=viewer or "")
    )
    if not records:
        return View(viewer)
    backed = read(
        graph,
        """
        MATCH (n)-[:EVIDENCED_BY]->(mine:SourceRecord) WHERE mine.id IN $records
        MATCH (n)-[:EVIDENCED_BY]->(r:SourceRecord)
        RETURN labels(n)[0] + ':' + n.id AS ref, collect(DISTINCT r.id) AS records
        """,
        records=list(records),
    )
    return View(viewer, records, frozenset(row["ref"] for row in backed if records.issuperset(row["records"])))


def restrict(graph: Graph, record: str, readers: list[str]) -> None:
    """Only these people may read the record, unless one of them has already shared it with everyone."""
    write(graph, "MATCH (r:SourceRecord {id: $id}) WHERE r.visibility IS NULL SET r.visibility = 'restricted'", id=record)
    write(graph, "MATCH (r:SourceRecord {id: $id}), (p:Person) WHERE p.id IN $readers MERGE (p)-[:CAN_READ]->(r)", id=record, readers=readers)


def share(graph: Graph, record: str, person: str) -> bool:
    return bool(write(
        graph,
        "MATCH (:Person {id: $person})-[:CAN_READ]->(r:SourceRecord {id: $id}) SET r.visibility = 'shared', r.shared_by = $person, r.shared_at = $at RETURN 1 AS done",
        id=record, person=person, at=now(),
    ))


def narrow(entity: dict, seen: View) -> dict:
    """An entity as this viewer may see it: without hidden neighbours, links written by unreadable records, or those records."""
    return entity | {
        "neighbours": [other for other in entity["neighbours"] if seen.sees(f"{other['kind']}:{other['id']}") and other["src"] not in seen.records],
        "sources": [source for source in entity["sources"] if source["record"] not in seen.records],
    }
