from falkordb import Graph

from ripple import trust
from ripple.graph import now, read, write


def learn(graph: Graph, investigation: str) -> dict:
    """After a human confirms the root cause: keep what was true (a fact) and how it was found (a playbook)."""
    root = read(
        graph,
        """
        MATCH (v:Investigation {id: $id})
        RETURN v.root_kind AS kind, v.root_id AS id, v.root_service AS service, v.root_title AS title,
               v.root_risk AS risk, v.service AS alerted, v.symptom AS symptom
        """,
        id=investigation,
    )[0]
    tools = [
        row["tool"]
        for row in read(
            graph,
            f"""
            MATCH (:Investigation {{id: $inv}})-[:HAS_STEP]->(st:Step {{agent: 'investigator'}})-[:TOUCHED]->(:{root['kind']} {{id: $root}})
            RETURN st.tool AS tool, min(st.seq) AS first ORDER BY first
            """,
            inv=investigation, root=root["id"],
        )
    ]
    playbook = f"PB-{investigation}"
    write(
        graph,
        """
        MATCH (v:Investigation {id: $inv}), (s:Service {id: $service})
        MERGE (p:Playbook {id: $id})
        SET p.symptom = $symptom, p.tools = $tools, p.risk = $risk, p.learned_at = $at,
            p.wins = coalesce(p.wins, 0), p.losses = coalesce(p.losses, 0)
        MERGE (p)-[:LEARNED_IN]->(v) MERGE (p)-[:APPLIES_TO]->(s)
        WITH p UNWIND range(0, size($tools) - 1) AS position
        MERGE (step:PlaybookStep {id: p.id + ':' + toString(position)}) SET step.tool = $tools[position]
        MERGE (p)-[h:HAS_STEP]->(step) SET h.order = position
        """,
        inv=investigation, service=root["service"], id=playbook, symptom=root["symptom"],
        tools=tools, risk=root["risk"] or [], at=now(),
    )
    fact = f"FACT-{investigation}"
    text = f"{root['symptom']} on {root['alerted']} was caused by {root['title']} in {root['service']}."
    write(
        graph,
        """
        MATCH (v:Investigation {id: $inv})
        MERGE (f:Fact {id: $id}) SET f.text = $text, f.confidence = 1.0, f.learned_at = $at
        MERGE (f)-[:LEARNED_IN]->(v)
        WITH f MATCH (s:Service) WHERE s.id IN $services MERGE (f)-[:ABOUT]->(s)
        """,
        inv=investigation, id=fact, text=text, at=now(), services=[root["service"], root["alerted"]],
    )
    return {"playbook": playbook, "tools": tools, "fact": fact}


def record_outcome(graph: Graph, playbook: str, won: bool) -> None:
    field = "wins" if won else "losses"
    write(graph, f"MATCH (p:Playbook {{id: $id}}) SET p.{field} = p.{field} + 1", id=playbook)


def overview(graph: Graph) -> dict:
    return {
        "playbooks": read(
            graph,
            """
            MATCH (p:Playbook)-[:APPLIES_TO]->(s:Service)
            RETURN p.id AS id, p.symptom AS symptom, s.id AS service, p.tools AS tools, p.risk AS risk,
                   p.wins AS wins, p.losses AS losses, p.learned_at AS learned_at ORDER BY learned_at
            """,
        ),
        "facts": read(
            graph,
            "MATCH (f:Fact) OPTIONAL MATCH (f)-[:ABOUT]->(s:Service) RETURN f.id AS id, f.text AS text, f.confidence AS confidence, collect(s.id) AS services ORDER BY id",
        ),
        "notes": read(
            graph,
            """
            MATCH (o)-[:HAS_NOTE]->(n:Note)
            OPTIONAL MATCH (n)-[:ABOUT]->(e)
            RETURN n.id AS id, n.text AS text, n.written_by AS written_by, n.written_at AS written_at,
                   labels(o)[0] + ':' + o.id AS origin, coalesce(o.subject, o.title, o.id) AS origin_name,
                   collect(labels(e)[0] + ':' + e.id) AS about
            ORDER BY written_at DESC LIMIT 50
            """,
        ),
        "investigations": read(
            graph,
            """
            MATCH (v:Investigation)-[:INVESTIGATES]->(i:Incident)
            RETURN v.id AS id, i.id AS incident, i.title AS title, i.status AS incident_status, v.status AS status,
                   v.steps AS steps, v.root_id AS root, v.playbook AS playbook, i.started_at AS started_at
            ORDER BY started_at DESC
            """,
        ),
    }


def brief(graph: Graph, person: str) -> dict:
    """What one person should know today, all of it read from the graph; the only model-written text is the note on a mail or chat."""
    at = now()
    return {
        "promises": read(
            graph,
            """
            MATCH (:Person {id: $person})-[:MADE]->(m:Commitment)-[:MADE_TO]->(c:Customer)
            WHERE m.valid_to IS NULL OR m.valid_to >= $at
            RETURN m.id AS id, m.text AS text, c.id AS customer, c.name AS customer_name, m.made_at AS made_at, m.valid_to AS valid_to
            ORDER BY made_at DESC
            """,
            person=person, at=at,
        ),
        "projects": read(
            graph,
            """
            MATCH (:Person {id: $person})-[:LEADS]->(j:Project)
            OPTIONAL MATCH (j)-[:INVOLVES]->(s:Service)<-[:AFFECTS]-(i:Incident {status: 'open'})
            RETURN j.id AS id, j.name AS name, j.status AS status, j.due_at AS due_at, j.goal AS goal, collect(DISTINCT i.id) AS open_incidents
            ORDER BY due_at
            """,
            person=person,
        ),
        "on_call": read(graph, "MATCH (:Person {id: $person})-[o:ON_CALL_FOR]->(s:Service) WHERE o.starts_at <= $at AND o.ends_at >= $at RETURN s.id AS service, o.ends_at AS until ORDER BY service", person=person, at=at),
        "only_expert": read(
            graph,
            """
            MATCH (p:Person)-[:AUTHORED|REVIEWED]->(:PR)-[:CHANGES]->(s:Service)
            WITH s, collect(DISTINCT p.id) AS experts
            WHERE experts = [$person]
            RETURN s.id AS service ORDER BY service
            """,
            person=person,
        ),
        "recent": read(
            graph,
            """
            MATCH (:Person {id: $person})-[:SENT|SENT_TO|TOOK_PART_IN]-(o)
            WHERE o:Email OR o:Conversation
            OPTIONAL MATCH (o)-[:HAS_NOTE]->(n:Note)
            RETURN DISTINCT labels(o)[0] AS kind, o.id AS id, coalesce(o.subject, o.title) AS title, coalesce(o.sent_at, o.started_at) AS at, n.text AS note
            ORDER BY at DESC LIMIT 6
            """,
            person=person,
        ),
        "review": to_review(graph),
        "to_check": trust.to_check(graph, person),
    }


def to_review(graph: Graph) -> list[dict]:
    """Newer promises and decisions a model thinks replace an older one. Both stay in force until a human settles it."""
    return read(
        graph,
        """
        MATCH (new)-[e:SUPERSEDES]->(old) WHERE e.proposed = true
        OPTIONAL MATCH (new)-[ne:EVIDENCED_BY]->(nr:SourceRecord)
        OPTIONAL MATCH (old)-[oe:EVIDENCED_BY]->(orec:SourceRecord)
        OPTIONAL MATCH (new)-[:MADE_TO]->(c:Customer)
        RETURN labels(new)[0] AS kind, c.id AS customer, c.name AS customer_name, e.found_by AS found_by, e.reason AS reason,
               new.id AS newer, coalesce(new.text, new.title) AS newer_text, ne.quote AS newer_quote, nr.id AS newer_record, coalesce(new.made_at, new.decided_at) AS newer_at,
               old.id AS older, coalesce(old.text, old.title) AS older_text, oe.quote AS older_quote, orec.id AS older_record, coalesce(old.made_at, old.decided_at) AS older_at
        ORDER BY newer_at DESC
        """,
    )


def settle(graph: Graph, newer: str, older: str, replace: bool, user: str) -> bool:
    """A human's call: the newer one replaces the older from its date on, or both stand and the pair is not raised again."""
    if not replace:
        return bool(write(
            graph,
            "MATCH (new {id: $newer})-[e:SUPERSEDES]->(old {id: $older}) WHERE e.proposed = true DELETE e MERGE (new)-[k:BOTH_STAND]->(old) SET k.by = $user, k.at = $at RETURN 1 AS done",
            newer=newer, older=older, user=user, at=now(),
        ))
    return bool(write(
        graph,
        """
        MATCH (new {id: $newer})-[e:SUPERSEDES]->(old {id: $older}) WHERE e.proposed = true
        SET e.proposed = false, e.confirmed_by = $user, e.confirmed_at = $at,
            old.valid_to = coalesce(new.made_at, new.decided_at), old.status = CASE WHEN old:Decision THEN 'superseded' ELSE old.status END
        RETURN 1 AS done
        """,
        newer=newer, older=older, user=user, at=now(),
    ))


def remember_turn(graph: Graph, user: str, session: str, role: str, text: str, refs: list[str]) -> None:
    """Conversation history lives in the graph, linked to the entities each turn was about."""
    turn = write(
        graph,
        """
        MERGE (u:User {id: $user})
        MERGE (s:Session {id: $session}) ON CREATE SET s.started_at = $at, s.turns = 0
        MERGE (u)-[:HAD]->(s)
        SET s.turns = s.turns + 1
        WITH s
        CREATE (s)-[:HAS]->(t:Turn {id: s.id + ':' + toString(s.turns), seq: s.turns, role: $role, text: $text, at: $at})
        WITH s, t OPTIONAL MATCH (s)-[:HAS]->(prev:Turn {seq: t.seq - 1})
        FOREACH (p IN CASE WHEN prev IS NULL THEN [] ELSE [prev] END | CREATE (p)-[:NEXT]->(t))
        RETURN t.id AS id
        """,
        user=user, session=session, role=role, text=text, at=now(),
    )[0]["id"]
    for ref in refs:
        kind, _, id = ref.partition(":")
        write(graph, f"MATCH (t:Turn {{id: $turn}}), (n:{kind} {{id: $id}}) MERGE (t)-[:REFERRED_TO]->(n)", turn=turn, id=id)


def recall_turns(graph: Graph, user: str, limit: int = 20) -> list[dict]:
    return read(
        graph,
        """
        MATCH (:User {id: $user})-[:HAD]->(s:Session)-[:HAS]->(t:Turn)
        OPTIONAL MATCH (t)-[:REFERRED_TO]->(n)
        RETURN s.id AS session, t.seq AS seq, t.role AS role, t.text AS text, t.at AS at,
               collect(labels(n)[0] + ':' + n.id) AS refs
        ORDER BY at DESC, seq DESC LIMIT $limit
        """,
        user=user, limit=limit,
    )


def set_preference(graph: Graph, user: str, key: str, value: str) -> None:
    write(graph, "MERGE (u:User {id: $user}) SET u += $prefs", user=user, prefs={f"pref_{key}": value})
