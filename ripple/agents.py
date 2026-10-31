import json
import threading
import time
from datetime import datetime, timedelta

from ripple import actions, fixer, ingest, memory, watch
from ripple.graph import connect, read, write
from ripple.investigation import Context, claim_task, finish_task, unfinished_tasks
from ripple.world import runtime, tenant_of

WINDOW_HOURS = 48
CONFIDENT = 0.6
LEAD = 0.1
MAX_SUSPECTS = 5
ROLES = {"triage": "triage", "technical": "investigator", "impact": "impact", "context": "context", "remediate": "fixer", "notify": "scribe"}
DEFAULT_PROCEDURE = ["blast_radius", "similar_incidents", "customer_events", "suspect_changes", "change_detail"]
TIME = "%Y-%m-%dT%H:%M:%SZ"


def triage(ctx: Context, payload: dict) -> str:
    similar = ctx.tool("similar_incidents", service=ctx.service)
    playbooks = ctx.tool("recall_playbooks", service=ctx.service, symptom=ctx.symptom)
    facts = ctx.tool("recall_facts", service=ctx.service)
    for incident in similar[:1]:
        fixed = f" and fixed by {incident['fix']}" if incident["fix"] else ""
        cites = [f"Incident:{incident['incident']}", f"Service:{incident['service']}"] + ([f"{incident['cause_kind']}:{incident['cause']}"] if incident["cause"] else [])
        ctx.finding("precedent", incident["incident"], f"{incident['incident']} ({incident['title']}) hit {incident['service']} on the same dependency chain; it was caused by {incident['cause']}{fixed}.", cites)
    facts = list({fact["fact"]: fact for fact in facts}.values())
    for fact in facts:
        ctx.finding("recalled", fact["fact"], f"Remembered from an earlier investigation: {fact['text']}", [f"Fact:{fact['fact']}", f"Service:{fact['service']}"])
    ctx.task("technical", stage=2, playbook=playbooks[0] if playbooks else None)
    ctx.task("impact", stage=2, service=ctx.service)
    return f"{len({incident['incident'] for incident in similar})} similar incidents, {len(playbooks)} playbooks, {len(facts)} facts recalled"


def technical(ctx: Context, payload: dict) -> str:
    playbook = payload.get("playbook")
    if playbook:
        write(ctx.graph, "MATCH (v:Investigation {id: $id}) SET v.playbook = $playbook", id=ctx.investigation, playbook=playbook["playbook"])
        found = _investigate(ctx, playbook["tools"], playbook["risk"])
        memory.record_outcome(ctx.graph, playbook["playbook"], won=found is not None)
        if found:
            return f"{found} (playbook {playbook['playbook']})"
    found = _investigate(ctx, DEFAULT_PROCEDURE, None)
    if found:
        return found
    ctx.task("notify", stage=4)
    return "inconclusive: no suspect scored high enough"


def _investigate(ctx: Context, procedure: list[str], risk_pattern: list[str] | None) -> str | None:
    since = (datetime.strptime(ctx.at, TIME) - timedelta(hours=WINDOW_HOURS)).strftime(TIME)
    if "blast_radius" in procedure:
        ctx.tool("blast_radius", service=ctx.service)
    prior = {row["service"] for row in ctx.tool("similar_incidents", service=ctx.service)} if "similar_incidents" in procedure else set()
    if "customer_events" in procedure:
        ctx.tool("customer_events", service=ctx.service, at=ctx.at)

    candidates = []
    for vendor in ctx.tool("vendor_outages", service=ctx.service, at=ctx.at):
        if vendor["outage"]:
            subject = f"Vendor:{vendor['vendor']}"
            statement = f"{vendor['name']} has an open outage ({vendor['outage_title']}) since {vendor['since']}; {vendor['used_by']} depends on it."
            supports = [subject, f"Outage:{vendor['outage']}", *[f"Service:{service}" for service in vendor["via"]]]
            ctx.hypothesis(subject, statement, 0.9, {"vendor_outage": 1.0}, supports)
            candidates.append({"score": 0.9, "subject": subject, "service": vendor["used_by"], "title": f"{vendor['name']} outage", "risk": [], "cites": supports})

    suspects: dict[str, dict] = {}
    if "suspect_changes" in procedure:
        for row in ctx.tool("suspect_changes", service=ctx.service, since=since, at=ctx.at):
            suspects.setdefault(row["pr"], row)
    matching = [row for row in suspects.values() if not risk_pattern or set(row["risk"]) & set(risk_pattern)]
    for suspect in matching[:MAX_SUSPECTS]:
        detail = ctx.tool("change_detail", pr=suspect["pr"])[0]
        factors = _score(suspect, detail, ctx.at, prior)
        subject = f"PR:{suspect['pr']}"
        via = " → ".join(suspect["via"])
        statement = f"{suspect['pr']} ({suspect['title']}) by {suspect['author_name']} changed {suspect['service']}, reached via {via}."
        supports = [subject, f"Person:{suspect['author']}", *[f"Service:{service}" for service in suspect["via"]]]
        ctx.hypothesis(subject, statement, factors["total"], factors, supports)
        candidates.append({"score": factors["total"], "subject": subject, "service": suspect["service"], "title": suspect["title"], "risk": suspect["risk"], "cites": supports})

    ranked = sorted(candidates, key=lambda candidate: -candidate["score"])
    if not ranked or ranked[0]["score"] < CONFIDENT or (len(ranked) > 1 and ranked[0]["score"] - ranked[1]["score"] < LEAD):
        return None
    return _conclude(ctx, ranked[0])


def _score(suspect: dict, detail: dict, at: str, prior: set[str]) -> dict:
    """Transparent ranking of a suspect change; every factor is shown beside the hypothesis."""
    age_hours = (datetime.strptime(at, TIME) - datetime.strptime(suspect["merged_at"], TIME)).total_seconds() / 3600
    factors = {
        "proximity": round(1 / (1 + suspect["hops"]), 2),
        "recency": round(max(0.0, 1 - age_hours / WINDOW_HOURS), 2),
        "risk": min(1.0, len(suspect["risk"]) / 2),
        "prior_incident": 1.0 if suspect["service"] in prior else 0.0,
        "deployed": 1.0 if detail["deployed_at"] and detail["deployed_at"] <= at else 0.0,
    }
    weighted = 0.35 * factors["proximity"] + 0.3 * factors["recency"] + 0.25 * factors["risk"] + 0.1 * factors["prior_incident"]
    return {**factors, "total": round(factors["deployed"] * weighted, 3)}


def _conclude(ctx: Context, winner: dict) -> str:
    kind, id = winner["subject"].split(":", 1)
    write(
        ctx.graph,
        """
        MATCH (v:Investigation {id: $inv})
        SET v.root_kind = $kind, v.root_id = $id, v.root_service = $service, v.root_title = $title, v.root_risk = $risk
        WITH v MATCH (v)-[:HAS_HYPOTHESIS]->(h:Hypothesis)
        SET h.status = CASE WHEN h.subject = $subject THEN 'leading' ELSE 'rejected' END
        """,
        inv=ctx.investigation, kind=kind, id=id, service=winner["service"], title=winner["title"], risk=winner["risk"], subject=winner["subject"],
    )
    ctx.finding("root_cause", "root", f"Most likely cause: {id} ({winner['title']}) in {winner['service']}, score {winner['score']}.", winner["cites"], status="proposed")
    ctx.task("context", stage=3)
    if winner["service"] != ctx.service:
        ctx.task("impact", stage=3, service=winner["service"])
    ctx.task("remediate", stage=3)
    ctx.task("notify", stage=4)
    return f"root cause proposed: {id}"


def context(ctx: Context, payload: dict) -> str:
    root = ctx.root()
    if root["kind"] == "PR":
        for trace in ctx.tool("decision_trace", pr=root["id"]):
            replaced = f" It replaced {', '.join(trace['supersedes'])}." if trace["supersedes"] else ""
            motive = f" It was motivated by {', '.join(trace['motivated_by'])}." if trace["motivated_by"] else ""
            cites = [f"Decision:{trace['decision']}", f"Person:{trace['decided_by']}", *[f"Decision:{d}" for d in trace["supersedes"]], *[f"Incident:{i}" for i in trace["motivated_by"]]]
            ctx.finding(
                "decision", trace["decision"],
                f"{root['id']} implements {trace['decision']} ({trace['title']}), decided by {trace['decided_by_name']} on {trace['decided_at']}.{replaced}{motive} Its recorded risk: {trace['risk']}",
                cites,
            )
    for decision in ctx.tool("governing_decisions", service=root["service"]):
        ctx.finding("constraint", decision["decision"], f"Any fix to {root['service']} must keep {decision['decision']} ({decision['title']}) in force." + (f" Its recorded risk: {decision['risk']}" if decision["risk"] else ""), [f"Decision:{decision['decision']}"])
    for requirement in ctx.tool("requirements_at_risk", service=root["service"]):
        by = f" (requested by {requirement['requested_by_name']})" if requirement["requested_by"] else ""
        cites = [f"Requirement:{requirement['requirement']}", f"Service:{requirement['service']}"] + ([f"Customer:{requirement['requested_by']}"] if requirement["requested_by"] else [])
        ctx.finding("requirement", requirement["requirement"], f"Requirement at risk on {requirement['service']}: {requirement['text']}{by}", cites)
    experts = ctx.tool("expertise", service=root["service"])
    if experts:
        ctx.finding("expertise", root["service"], f"Best reviewers for {root['service']}: " + ", ".join(f"{expert['name']} ({expert['touches']} changes)" for expert in experts[:3]), [f"Person:{expert['person']}" for expert in experts[:3]])
    return f"decision history, constraints and reviewers for {root['service']}"


def impact(ctx: Context, payload: dict) -> str:
    service = payload["service"]
    customers = ctx.tool("affected_customers", service=service)
    if customers:
        revenue = f" Combined monthly revenue ${sum(customer['monthly_revenue'] for customer in customers):,}." if all(customer["monthly_revenue"] for customer in customers) else ""
        ctx.finding("customers", "all", f"{len(customers)} customers use features that depend on {service}: {', '.join(customer['name'] for customer in customers)}.{revenue}", [f"Customer:{customer['customer']}" for customer in customers])
    exposure = ctx.tool("sla_exposure", service=service)
    if exposure:
        total = sum(row["credit_at_risk"] for row in exposure)
        detail = "; ".join(f"{row['name']} {row['uptime_target']}% ({_budget_minutes(row['uptime_target'])} min of downtime allowed a month, {_money(row['credit_at_risk'])} credit)" for row in exposure)
        ctx.finding("sla", "all", f"SLA credits at risk: {_money(total)} a month across {len(exposure)} {'contract' if len(exposure) == 1 else 'contracts'}. {detail}.", [ref for row in exposure for ref in (f"Customer:{row['customer']}", f"Contract:{row['contract']}", f"SLA:{row['sla']}")])
    for commitment in ctx.tool("commitments_at_risk", service=service, at=ctx.at):
        ctx.finding("commitment", commitment["commitment"], f"{commitment['made_by_name']} promised {commitment['customer_name']} on {commitment['made_at'][:10]}: \"{commitment['quote']}\" ({commitment['source']})", [f"Commitment:{commitment['commitment']}", f"Customer:{commitment['customer']}", f"Person:{commitment['made_by']}"])
    for event in ctx.tool("customer_events", service=service, at=ctx.at):
        ctx.finding("event", event["event"], f"{event['title']} is running right now ({event['starts_at'][:10]} to {event['ends_at'][:10]}).", [f"Event:{event['event']}", f"Customer:{event['customer']}"])
    return f"{len(customers)} customers, {len(exposure)} SLA contracts affected through {service}"


def _money(amount: float) -> str:
    return f"${amount:,.0f}" if amount >= 10 or amount == int(amount) else f"${amount:,.2f}"


def _budget_minutes(uptime_target: float) -> float:
    return round(30 * 24 * 60 * (1 - uptime_target / 100), 1)


def remediate(ctx: Context, payload: dict) -> str:
    root = ctx.root()
    if root["kind"] != "PR":
        return f"cause is a {root['kind'].lower()}, not a code change: no rollback offered"
    proposed = [id for id in (fixer.propose_rollback(ctx, root["id"]), fixer.propose_fix(ctx, root["id"])) if id]
    if proposed:
        return f"{len(proposed)} remediations proposed"
    pull = watch.revertable(tenant_of(ctx.graph), root["id"])
    if not pull:
        return f"{root['id']} is not in a checked-out repository: nothing to revert"
    subject, body = actions.revert_request(root, ctx.incident, fixer.revert_warning(fixer.undone_by_reverting(ctx.graph, root["id"])))
    actions.propose(ctx, "revert_pr", root["id"], pull, "GitHub pull request", subject, body, [f"{ctx.investigation}:F:root_cause:root"])
    return f"a revert of {root['id']} is drafted as a pull request on {pull.split('#')[0]}"


def notify(ctx: Context, payload: dict) -> str:
    """Reads what the other agents left in the investigation subgraph and turns it into messages for approval."""
    root = ctx.root()
    service = root["service"] or ctx.service
    incident = read(ctx.graph, "MATCH (i:Incident {id: $id}) RETURN i.title AS title, i.started_at AS started_at", id=ctx.incident)[0]
    cause = [f"{ctx.investigation}:F:root_cause:root"] if root["id"] else []
    proposed = 0
    for on_call in ctx.tool("who_to_page", service=service, at=ctx.at):
        if on_call["on_call"] and root["id"]:
            subject, body = actions.page(root, ctx.incident, incident["title"], on_call)
            actions.propose(ctx, "page", on_call["on_call"], on_call["on_call_name"], "pager", subject, body, cause)
            proposed += 1
    customers = ctx.shared("affected_customers")
    exposure = {row["customer"]: row for row in ctx.shared("sla_exposure")}
    commitments = ctx.shared("commitments_at_risk")
    if customers:
        subject, body = actions.status_update(ctx.incident, sorted({feature for customer in customers for feature in customer["features"]}))
        actions.propose(ctx, "status_page", "public", "Status page", "status page", subject, body, [f"{ctx.investigation}:F:customers:all"])
        proposed += 1
    for customer in customers:
        promised = [commitment for commitment in commitments if commitment["customer"] == customer["customer"]]
        if customer["customer"] not in exposure and not promised:
            continue
        because = [f"{ctx.investigation}:F:commitment:{commitment['commitment']}" for commitment in promised] + ([f"{ctx.investigation}:F:sla:all"] if customer["customer"] in exposure else [])
        subject, body = actions.customer_notice({**customer, "started_at": incident["started_at"]}, ctx.incident, promised, exposure.get(customer["customer"]))
        actions.propose(ctx, "customer_notice", customer["customer"], customer["name"], f"email via {customer['account_manager_name']}", subject, body, because)
        proposed += 1
    reported = read(ctx.graph, "MATCH (:Incident {id: $id})-[:TRIGGERED_BY]->(a:Alert) WHERE a.origin <> '' RETURN a.origin AS origin ORDER BY a.at LIMIT 1", id=ctx.incident)
    if reported:
        subject, body = actions.issue_reply(ctx.graph, ctx.investigation, ctx.incident)
        actions.propose(ctx, "issue_comment", "github", reported[0]["origin"], "GitHub issue", subject, body, cause)
        proposed += 1
    return f"{proposed} messages drafted for approval"


WORKERS = {"triage": triage, "technical": technical, "impact": impact, "context": context, "remediate": remediate, "notify": notify}


def work(tenant: str, investigation: str, worker: str, delay: float = 0.0) -> None:
    """One worker: claim a task from the shared board, do it, repeat until the board is empty."""
    graph = connect(tenant)
    while True:
        task = claim_task(graph, investigation, worker)
        if task is None:
            if not unfinished_tasks(graph, investigation):
                return
            time.sleep(0.05)
            continue
        ctx = Context.load(graph, investigation, ROLES[task["kind"]], delay)
        try:
            finish_task(graph, task["id"], "done", WORKERS[task["kind"]](ctx, task["payload"]))
        except Exception as error:
            finish_task(graph, task["id"], "failed", f"{type(error).__name__}: {error}")


def run(tenant: str, investigation: str, workers: int = 3, delay: float = 0.0) -> None:
    threads = [threading.Thread(target=work, args=(tenant, investigation, f"worker-{n}", delay)) for n in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    graph = connect(tenant)
    write(graph, "MATCH (v:Investigation {id: $id}) WHERE v.status = 'running' SET v.status = 'awaiting_approval'", id=investigation)


def confirm(tenant: str, investigation: str, user: str) -> dict:
    """A human accepts the proposed root cause. Only now is anything written to long-term memory."""
    graph = connect(tenant)
    root = Context.load(graph, investigation, "scribe").root()
    if not root["id"]:
        raise ValueError(f"{investigation} has no proposed root cause to confirm")
    write(
        graph,
        f"""
        MATCH (v:Investigation {{id: $inv}})-[:INVESTIGATES]->(i:Incident), (cause:{root['kind']} {{id: $root}})
        SET v.status = 'confirmed', v.confirmed_by = $user
        MERGE (i)-[:CAUSED_BY]->(cause)
        WITH v MATCH (v)-[:HAS_HYPOTHESIS]->(h:Hypothesis {{status: 'leading'}}) SET h.status = 'confirmed'
        WITH v MATCH (v)-[:HAS_FINDING]->(f:Finding {{kind: 'root_cause'}}) SET f.status = 'confirmed'
        """,
        inv=investigation, root=root["id"], user=user,
    )
    learned = memory.learn(graph, investigation)
    text, sidecar = actions.postmortem(graph, investigation)
    folder = runtime(tenant) / "docs" / "postmortems"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{sidecar['id']}.md").write_text(text)
    (folder / f"{sidecar['id']}.extracted.json").write_text(json.dumps(sidecar, indent=1))
    ingest.sync(graph, "documents", runtime(tenant) / "docs")
    return {**learned, "postmortem": sidecar["id"]}
