from ripple import actions, agents, chat, world
from ripple.graph import Graph, read
from ripple.investigation import open_incident, parse_alerts, resolve, state

CLOSED, WAITING = "C", "A"
RESPONDER = "asha"


def load_history(tenant: str, graph: Graph) -> None:
    """Gives a freshly seeded demo company a past: one incident worked to a close, one waiting on a person, and questions people asked."""
    scenarios = {item["id"]: item for item in world.scenarios(world.world_of(tenant))}
    if not {CLOSED, WAITING} <= scenarios.keys():
        return
    closed = _investigate(tenant, graph, scenarios[CLOSED])
    agents.confirm(tenant, closed, RESPONDER)
    for action in state(graph, closed)["actions"]:
        actions.approve(graph, action["id"], RESPONDER, None)
    resolve(graph, closed, RESPONDER)
    _investigate(tenant, graph, scenarios[WAITING])
    for person in read(graph, "MATCH (p:Person) RETURN p.id AS id"):
        for question in chat.SUGGESTIONS[:3]:
            # Seeded history skips the model: thirty questions on every reset would spend a free tier's daily quota.
            chat.answer(graph, question, person["id"], f"history-{person['id']}", written=False)


def _investigate(tenant: str, graph: Graph, scenario: dict) -> str:
    world.apply_scenario(graph, scenario)
    investigation, _ = open_incident(graph, parse_alerts(scenario["alert"])[0])
    agents.run(tenant, investigation)
    return investigation
