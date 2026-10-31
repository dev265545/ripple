import os
from datetime import UTC, datetime

from falkordb import FalkorDB, Graph
from redis.exceptions import ResponseError

PREFIX = "ripple:"

LABELS = [
    "Person", "Team", "Identity", "Service", "Vendor", "Outage", "Repo", "PR", "Deploy", "Alert",
    "Incident", "Doc", "Decision", "Requirement", "Product", "Feature", "Customer", "Contract",
    "SLA", "Commitment", "Event", "Email", "Source", "SourceRecord", "Investigation", "Task",
    "Step", "Hypothesis", "Finding", "Action", "Remediation", "Fact", "Playbook", "PlaybookStep",
    "User", "Session", "Turn", "File", "Symbol", "Conversation", "Channel", "Contact", "Note", "Project", "Area",
]

FULLTEXT = {
    "Person": ["name", "email"],
    "Team": ["id"],
    "Service": ["id", "description"],
    "Vendor": ["name"],
    "Customer": ["name"],
    "Feature": ["id"],
    "PR": ["id", "title"],
    "Decision": ["id", "title"],
    "Requirement": ["text"],
    "Incident": ["id", "title", "summary"],
    "Doc": ["title", "text"],
    "Email": ["subject", "body"],
    "Commitment": ["text"],
    "Conversation": ["title", "text"],
    "Note": ["text"],
    "Contact": ["name"],
    "Project": ["name", "goal"],
    "Area": ["title", "summary"],
}


def database() -> FalkorDB:
    return FalkorDB(
        host=os.getenv("FALKORDB_HOST", "localhost"),
        port=int(os.getenv("FALKORDB_PORT", "6379")),
    )


def connect(tenant: str) -> Graph:
    return database().select_graph(PREFIX + tenant)


def tenants() -> list[str]:
    return sorted(name.removeprefix(PREFIX) for name in database().list_graphs() if name.startswith(PREFIX))


def drop(tenant: str) -> None:
    if tenant in tenants():
        connect(tenant).delete()


def apply_schema(graph: Graph) -> None:
    for label in LABELS:
        _ensure(graph, f"CREATE INDEX FOR (n:{label}) ON (n.id)")
    for label, fields in FULLTEXT.items():
        properties = ", ".join(f"n.{field}" for field in fields)
        _ensure(graph, f"CREATE FULLTEXT INDEX FOR (n:{label}) ON ({properties})")


def _ensure(graph: Graph, statement: str) -> None:
    try:
        graph.query(statement)
    except ResponseError as error:
        if "already indexed" not in str(error):
            raise


def read(graph: Graph, cypher: str, **params) -> list[dict]:
    return _rows(graph.ro_query(cypher, params))


def write(graph: Graph, cypher: str, **params) -> list[dict]:
    return _rows(graph.query(cypher, params))


def _rows(result) -> list[dict]:
    columns = [column[1] for column in result.header]
    return [dict(zip(columns, row)) for row in result.result_set]


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
