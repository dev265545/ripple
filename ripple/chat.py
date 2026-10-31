import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from falkordb import Graph

from ripple import access, ingest, memory, model, queries, trust
from ripple.graph import now, read
from ripple.mcp_server import parameters

WINDOW = timedelta(hours=48)
STAMP = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class Intent:
    pattern: str
    tool: str
    about: str | None
    lead: str
    line: str


# Without a model key, questions are routed to named queries by these keywords.
INTENTS = [
    Intent(r"on.?call|\bpage\b|who (do|should) (i|we) (call|wake)", "who_to_page", "Service", "On call for {subject}:", "{on_call_name} ({email}), {team} team"),
    Intent(r"promis|commit", "commitments_at_risk", "Service", "Live promises that depend on {subject}:", '{made_by_name} told {customer_name}: "{quote}"'),
    Intent(r"\bsla\b|credit|contract|exposure|penalt", "sla_exposure", "Service", "Contracts whose SLA covers what {subject} serves:", "{name}: {contract} guarantees {uptime_target}% uptime, {credit_at_risk} in monthly credit at risk"),
    Intent(r"customer|affected|who uses|impact", "affected_customers", "Service", "Customers who use something served by {subject}:", "{name} ({plan}), account manager {account_manager_name}, uses {features}"),
    Intent(r"requirement|brd", "requirements_at_risk", "Service", "Stated requirements that rest on {subject}:", "{requirement}: {text} Requested by {requested_by_name}."),
    Intent(r"why|decision|decided|adr", "decision_trace", "PR", "Why {subject} was made:", "{decision}: {title}. Decided by {decided_by_name} on {decided_at}, motivated by {motivated_by}. Recorded risk: {risk}"),
    Intent(r"why|decision|decided|adr|rule|constraint", "governing_decisions", "Service", "Decisions that govern {subject}:", "{decision}: {title}. Decided by {decided_by_name}. Recorded risk: {risk}"),
    Intent(r"expert|who knows|who worked|knows", "expertise", "Service", "People who have worked most on {subject}:", "{name}, {touches} changes authored or reviewed"),
    Intent(r"similar|before|history|past|happened|previous", "similar_incidents", "Service", "Earlier incidents on {subject} or what it depends on:", "{incident}: {title}. Caused by {cause}, fixed by {fix}."),
    Intent(r"vendor|third.?party|outage", "vendor_outages", "Service", "Vendors {subject} relies on:", "{name}, used by {used_by}, open outage: {outage_title}"),
    Intent(r"chang|deploy|recent|shipped|merged|suspect", "suspect_changes", "Service", "Changes in the 48 hours before {at} on {subject} or its dependencies:", "{pr}: {title} by {author_name}, deployed {deployed_at}"),
    Intent(r"depend|blast|break|goes down|fails|downstream|radius|relies", "blast_radius", "Service", "If {subject} fails, these depend on it:", "{service} ({team} team), {hops} hops away"),
    Intent(r"critical|single point|most important|riskiest", "critical_services", None, "Services most of the dependency graph runs through:", "{service}, centrality {score}"),
    Intent(r"overview|big picture|as a whole|areas|parts of|how is .* organi[sz]ed|what does (the|this|our) company", "areas", None, "The graph falls into these parts:", "{title} ({size} things). {summary}"),
    Intent(r".", "change_detail", "PR", "{subject}:", "{title} in {service}. Files: {files}. Reviewed by {reviewers}. Deployed {deployed_at}."),
]
SUGGESTIONS = [
    "Who is on call for payments-core?",
    "Which customers are affected if ledger-db fails?",
    "What have we promised that depends on checkout-api?",
    "Why was PR-412 made?",
    "What changed recently around checkout-api?",
    "Which services are most critical?",
]


def answer(graph: Graph, text: str, user: str, session: str, written: bool = True) -> dict:
    """Route a question to a named graph query, answer from its rows, and cite the source records behind them."""
    seen = access.view(graph, user)
    named = [entity for entity in ingest.named_entities(graph, text) if seen.sees(f"{entity['kind']}:{entity['id']}")]
    subjects = {}
    for entity in named:
        subjects.setdefault(entity["kind"], entity["id"])
    refers_back = not named and re.search(r"\b(it|its|that|this|there|same)\b", text.lower())
    carried = _last_subject(graph, user, session) if refers_back else None
    if carried:
        subjects[carried[0]] = carried[1]
    reply = (_ask_model(graph, text, named, carried, session, seen) if written and model.settings() else None) or {**_routed(graph, text, subjects, seen), "model": None}
    reply["refs"] = [ref for ref in reply["refs"] if seen.sees(ref)]
    reply.setdefault("withheld", 0)
    reply["citations"] = _citations(graph, reply["refs"], seen)
    reply["carried"] = f"{carried[0]}:{carried[1]}" if carried else None
    memory.remember_turn(graph, user, session, "user", text, [f"{kind}:{id}" for kind, id in subjects.items()])
    memory.remember_turn(graph, user, session, "assistant", reply["answer"], reply["refs"][:12])
    return reply


def _routed(graph: Graph, text: str, subjects: dict[str, str], seen: access.View) -> dict:
    intent = next((item for item in INTENTS if re.search(item.pattern, text.lower()) and (item.about is None or item.about in subjects)), None)
    if intent:
        return _run(graph, intent, subjects.get(intent.about) if intent.about else None, seen)
    if subjects:
        return _describe(graph, *next(iter(subjects.items())), seen)
    return _closest(graph, text)


MODEL_ROWS = 12
MODEL_ROUNDS = 4
REMEMBERED_TURNS = 6
REMEMBERED_CHARS = 700
FILLED_FOR_THE_MODEL = ("at", "since")
INSTRUCTIONS = """You answer questions about one company from its knowledge graph, by calling the tools that query it.
Call every tool the question needs, several at once when it has several parts. Use ids exactly as they appear below or in earlier turns.
"This", "these" and "it" refer to what the earlier turns were about. Who is responsible for a change is its author and reviewers.
When asked what could go wrong or what the repercussions are, look up what depends on the changed service, which customers use it, and which promises and SLAs are at risk.
When the rows come back, answer briefly in markdown, using only what the rows say and adding no consequences they do not show: bold the names that matter, and use a bullet list when there are several items.
Prefer the named tools when one answers the question. Counting, ranking, totals, comparisons and anything else they do not cover are for graph_query: write the Cypher yourself from the schema, and never say the graph has nothing before trying it. If it returns an error, correct the query and run it again.
Quote promises word for word on a line starting with "> ". If the rows are empty, say the graph has nothing on it. Never guess."""


def _ask_model(graph: Graph, text: str, named: list[dict], carried: tuple[str, str] | None, session: str, seen: access.View) -> dict | None:
    """The model picks named queries and writes the answer from their rows. None means: use keyword routing."""
    at = _clock(graph)
    filled = {"at": at, "since": (datetime.strptime(at, STAMP) - WINDOW).strftime(STAMP)}
    tools = [
        {"type": "function", "function": {"name": name, "description": query.doc, "parameters": {"type": "object", "properties": {param: {"type": "string"} for param in parameters(name) if param not in FILLED_FOR_THE_MODEL}, "required": [param for param in parameters(name) if param not in FILLED_FOR_THE_MODEL]}}}
        for name, query in queries.QUERIES.items()
    ]
    tools.append({"type": "function", "function": {"name": queries.WRITTEN, "description": queries.WRITTEN_DOC, "parameters": {"type": "object", "properties": {"cypher": {"type": "string"}}, "required": ["cypher"]}}})
    services = [row["id"] for row in read(graph, "MATCH (s:Service) RETURN s.id AS id ORDER BY id")]
    hints = [f"{entity['kind']}:{entity['id']} ({entity['name']})" for entity in named] + ([f"{carried[0]}:{carried[1]} (what the previous question was about)"] if carried else [])
    earlier = read(graph, "MATCH (:Session {id: $session})-[:HAS]->(t:Turn) RETURN t.role AS role, t.text AS content ORDER BY t.seq DESC LIMIT $turns", session=session, turns=REMEMBERED_TURNS)
    messages = [
        {"role": "system", "content": f"{INSTRUCTIONS}\nServices: {', '.join(services)}\nNamed in the question: {', '.join(hints) or 'nothing recognised'}\nSchema for graph_query:\n{queries.schema(graph)}"},
        *[{"role": turn["role"], "content": turn["content"][:REMEMBERED_CHARS]} for turn in reversed(earlier)],
        {"role": "user", "content": text},
    ]
    steps, withheld = [], 0
    try:
        picked = model.chat(messages, tools, routing=True)
        for last in [False] * (MODEL_ROUNDS - 1) + [True]:
            messages.append({"role": "assistant", "content": picked.get("content") or "", "tool_calls": picked["tool_calls"]})
            for call in picked["tool_calls"]:
                tool = call["function"]["name"]
                if tool == queries.WRITTEN:
                    cypher = json.loads(call["function"]["arguments"])["cypher"]
                    try:
                        rows = queries.written(graph, cypher, seen.hidden, seen.records)
                        steps.append({"tool": tool, "cypher": cypher, "params": {}, "rows": rows})
                        result = rows[:MODEL_ROWS]
                    except ValueError as problem:
                        result = {"error": str(problem)}
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, default=str)})
                    continue
                params = {name: filled.get(name) or str(json.loads(call["function"]["arguments"] or "{}")[name]) for name in parameters(tool)}
                rows, left_out = queries.redact(tool, queries.run(graph, tool, **params), seen.hidden)
                withheld += left_out
                steps.append({"tool": tool, "cypher": queries.QUERIES[tool].cypher.strip(), "params": params, "rows": rows})
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(rows[:MODEL_ROWS], default=str)})
            if last:
                messages.append({"role": "user", "content": "That is every query you may run. Write the answer now from the rows above, and say plainly which part of the question they do not cover."})
            picked = model.chat(messages, tools, must_call=False)
            if not picked.get("tool_calls"):
                break
        written = (picked.get("content") or "").strip()
    except (model.ModelUnavailable, KeyError, IndexError, TypeError, ValueError) as problem:
        logging.getLogger(__name__).warning("model answer skipped after %s, keyword routing used: %s", [step["tool"] for step in steps], problem)
        return None
    if not written:
        logging.getLogger(__name__).warning("model wrote nothing after %s queries, keyword routing used", len(steps))
        return None
    if not steps:
        return None
    refs = list(dict.fromkeys(ref for step in steps for ref in (queries.written_refs(graph, step["rows"]) if step["tool"] == queries.WRITTEN else queries.refs(step["tool"], step["rows"]))))
    return {"answer": written, "lines": [], **steps[0], "steps": steps, "refs": refs, "withheld": withheld, "model": picked.get("model", model.name())}


def _run(graph: Graph, intent: Intent, subject: str | None, seen: access.View) -> dict:
    at = _clock(graph)
    since = (datetime.strptime(at, STAMP) - WINDOW).strftime(STAMP)
    available = {"service": subject, "pr": subject, "at": at, "since": since}
    params = {name: available[name] for name in parameters(intent.tool)}
    rows, withheld = queries.redact(intent.tool, queries.run(graph, intent.tool, **params), seen.hidden)
    lead = intent.lead.format(subject=subject, at=at)
    lines = [intent.line.format_map(_Readable(row)) for row in rows]
    refs = queries.refs(intent.tool, rows)
    if subject and f"{intent.about}:{subject}" not in refs:
        refs = [f"{intent.about}:{subject}", *refs]
    return {
        "answer": lead if lines else f"The graph has nothing for that. Asked: {queries.QUERIES[intent.tool].doc}",
        "lines": lines,
        "tool": intent.tool,
        "cypher": queries.QUERIES[intent.tool].cypher.strip(),
        "params": params,
        "rows": rows,
        "refs": refs,
        "withheld": withheld,
    }


def _describe(graph: Graph, kind: str, id: str, seen: access.View) -> dict:
    found = access.narrow(queries.entity(graph, kind, id), seen)
    lines = [f"{neighbour['relation']} {'→' if neighbour['outgoing'] else '←'} {neighbour['kind']} {neighbour['name']}" for neighbour in found["neighbours"][:14]]
    refs = [f"{kind}:{id}", *[f"{neighbour['kind']}:{neighbour['id']}" for neighbour in found["neighbours"][:14]]]
    name = found["props"].get("name") or found["props"].get("title") or id
    return {"answer": f"{name} ({kind}) is connected to:", "lines": lines, "tool": "entity", "cypher": None, "params": {"kind": kind, "id": id}, "rows": [], "refs": list(dict.fromkeys(refs))}


def _closest(graph: Graph, text: str) -> dict:
    words = [word for word in re.findall(r"[A-Za-z0-9]{4,}", text)]
    hits = queries.find_entity(graph, " | ".join(words))[:6] if words else []
    return {
        "answer": "I could not tie that to anything I can query. Closest things in the graph:" if hits else "Nothing in the graph matches that. Name a service, customer, person or change.",
        "lines": [f"{hit['kind']} {hit['name']}" for hit in hits],
        "tool": "find_entity",
        "cypher": None,
        "params": {"text": text},
        "rows": [],
        "refs": [f"{hit['kind']}:{hit['id']}" for hit in hits],
    }


def _citations(graph: Graph, refs: list[str], seen: access.View) -> list[dict]:
    cited = []
    for ref in refs[:10]:
        kind, _, id = ref.partition(":")
        if kind not in ingest.LINKABLE + ["Commitment", "SLA", "Team", "Event"]:
            continue
        standing = trust.of(graph, kind, id)
        verified_by = standing["verified_by"] if standing and standing["state"] == "verified" else None
        cited += read(
            graph,
            f"""
            MATCH (n:{kind} {{id: $id}})-[e:EVIDENCED_BY]->(r:SourceRecord)-[:FROM]->(s:Source)
            WHERE NOT r.id IN $unreadable
            RETURN $ref AS ref, coalesce(n.name, n.title, n.id) AS name, s.name AS source, r.id AS record, r.uri AS uri, e.quote AS quote, $verified_by AS verified_by
            ORDER BY e.quote IS NULL LIMIT 2
            """,
            id=id, ref=ref, unreadable=list(seen.records), verified_by=verified_by,
        )
    return cited


def _last_subject(graph: Graph, user: str, session: str) -> tuple[str, str] | None:
    for turn in memory.recall_turns(graph, user, limit=4):
        if turn["session"] != session:
            continue
        for ref in turn["refs"]:
            kind, _, id = ref.partition(":")
            if kind in ("Service", "PR"):
                return kind, id
    return None


def _clock(graph: Graph) -> str:
    """Questions about 'now' mean the open incident when there is one."""
    live = read(graph, "MATCH (i:Incident {status: 'open'}) RETURN max(i.started_at) AS at")
    return live[0]["at"] or now()


class _Readable(dict):
    def __getitem__(self, key: str) -> str:
        value = self.get(key)
        if value is None or value == []:
            return "none recorded"
        return ", ".join(map(str, value)) if isinstance(value, list) else str(value)
