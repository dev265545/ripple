import re
from datetime import datetime

from falkordb import Graph

from ripple import live, model, watch, world
from ripple.graph import now, read, write
from ripple.investigation import Context


def propose(ctx: Context, kind: str, key: str, to: str, channel: str, subject: str, body: str, because: list[str]) -> str:
    """Outward messages are only proposed here; nothing is sent until a human approves."""
    id = f"{ctx.investigation}:A:{kind}:{key}"
    write(
        ctx.graph,
        """
        MATCH (v:Investigation {id: $inv})
        MERGE (a:Action {id: $id})
        SET a.kind = $kind, a.to = $to, a.channel = $channel, a.subject = $subject, a.body = $body,
            a.status = coalesce(a.status, 'proposed'), a.proposed_at = $at
        MERGE (v)-[:PROPOSED]->(a)
        WITH a UNWIND $because AS finding MATCH (f:Finding {id: finding}) MERGE (a)-[:JUSTIFIED_BY]->(f)
        """,
        inv=ctx.investigation, id=id, kind=kind, to=to, channel=channel, subject=subject, body=body,
        because=because, at=now(),
    )
    return id


def approve(graph: Graph, action: str, user: str, body: str | None = None) -> dict:
    drafted = read(graph, "MATCH (a:Action {id: $id, status: 'proposed'}) RETURN a.kind AS kind, a.to AS to, a.subject AS subject, a.body AS body", id=action)
    if not drafted:
        raise ValueError(f"{action} is not awaiting approval")
    delivered, url = deliver(world.tenant_of(graph), action.rsplit(":", 1)[1], drafted[0] | {"body": body or drafted[0]["body"]})
    return write(
        graph,
        """
        MATCH (a:Action {id: $id}) WHERE a.status = 'proposed'
        SET a.status = 'sent', a.approved_by = $user, a.sent_at = $at, a.body = coalesce($body, a.body), a.delivered = $delivered, a.url = $url
        RETURN properties(a) AS action
        """,
        id=action, user=user, at=now(), body=body, delivered=delivered, url=url,
    )[0]["action"]


def deliver(tenant: str, key: str, action: dict) -> tuple[str, str]:
    """Sends an approved message wherever a connection exists for it, and says in a sentence where it went, with a link if there is one."""
    kind = action["kind"]
    if kind == "issue_comment":
        return "Posted on the GitHub issue.", watch.reply(tenant, action["to"], action["body"])
    if kind == "revert_pr":
        return "Opened as a pull request on GitHub.", watch.revert(tenant, action["to"], action["subject"], action["body"])
    if kind == "customer_notice":
        address = live.mail(tenant, key, action["subject"], action["body"])
        return (f"Emailed to {address}." if address else "Approved, not sent: connect Gmail to email approved notices."), ""
    channel = live.post(tenant, f"*{action['subject']}*\n{action['body']}")
    if kind == "status_page":
        return "Published on the status page" + (f" and posted in {channel}." if channel else "."), f"/status/{tenant}"
    return (f"Posted in {channel}." if channel else "Approved, not sent: connect Slack to post pages in a channel."), ""


REWRITE_INSTRUCTIONS = """Rewrite this incident message so it reads as if a calm, senior person wrote it by hand.
Keep every fact, name, number, date, time, reference and quoted sentence exactly as written. Add nothing new.
Reply with the message body only."""
FACT = r"\d[\d.,:%]*\d|\d|\"[^\"]+\"|\b[A-Z]{2,}-[\w-]+"


def rewrite(graph: Graph, action: str) -> dict:
    """A model's rewording of a draft, returned for a person to review. Rejected if any fact in the draft is missing."""
    found = read(graph, "MATCH (a:Action {id: $id}) RETURN a.body AS body, a.status AS status", id=action)
    if not found or found[0]["status"] != "proposed":
        raise ValueError(f"{action} is not awaiting approval")
    draft = found[0]["body"]
    reply = model.chat([{"role": "system", "content": REWRITE_INSTRUCTIONS}, {"role": "user", "content": draft}])
    written = (reply.get("content") or "").strip()
    lost = [fact for fact in dict.fromkeys(re.findall(FACT, draft)) if fact not in written]
    if not written or lost:
        raise ValueError(f"The rewrite dropped {', '.join(lost[:4]) or 'everything'}, so the original draft was kept.")
    return {"body": written, "model": reply.get("model", model.name())}


def outbox(graph: Graph) -> list[dict]:
    return [row["action"] for row in read(graph, "MATCH (a:Action {status: 'sent'}) RETURN properties(a) AS action ORDER BY a.sent_at DESC")]


def page(root: dict, incident: str, summary: str, on_call: dict) -> tuple[str, str]:
    subject = f"[{incident}] {summary}"
    body = (
        f"{on_call['on_call_name']}, you are on call for {on_call['service']}.\n\n"
        f"{incident}: {summary}\n"
        f"Likely cause: {root['title']} ({root['id']}) in {root['service']}.\n"
        "The evidence and what Ripple proposes are waiting for your review in the incident room."
    )
    return subject, body


def status_update(incident: str, features: list[str]) -> tuple[str, str]:
    affected = ", ".join(sorted(features))
    return (
        f"Investigating degraded performance: {affected}",
        f"We are investigating elevated error rates affecting {affected}. "
        f"A cause has been identified and a fix is being rolled out. Next update in 30 minutes. Reference {incident}.",
    )


def status_page(graph: Graph) -> list[dict]:
    """Only what a person approved for the public: the status updates, newest first, with whether their incident is over."""
    return read(
        graph,
        """
        MATCH (i:Incident)<-[:INVESTIGATES]-(:Investigation)-[:PROPOSED]->(a:Action {kind: 'status_page', status: 'sent'})
        RETURN a.subject AS title, a.body AS body, a.sent_at AS at, i.status AS incident_status, i.resolved_at AS resolved_at
        ORDER BY at DESC
        """,
    )


def revert_request(root: dict, incident: str, warning: str) -> tuple[str, str]:
    body = f"Reverts #{root['id'].removeprefix('PR-')} ({root['title']}), the likely cause of {incident}."
    return f"Revert \"{root['title']}\"", f"{body}\n\n{warning}" if warning else body


def issue_reply(graph: Graph, investigation: str, incident: str) -> tuple[str, str]:
    findings = read(graph, "MATCH (:Investigation {id: $id})-[:HAS_FINDING]->(f:Finding) RETURN f.claim AS claim ORDER BY f.at", id=investigation)
    found = [f"- {finding['claim']}" for finding in findings] or ["- Nothing in the company's records points at a cause yet."]
    return f"Findings for {incident}", "\n".join([f"Ripple investigated this as {incident}. What the company's records show:", "", *found])


def _day(stamp: str) -> str:
    return f"{datetime.fromisoformat(stamp):%-d %B %Y}"


def customer_notice(customer: dict, incident: str, commitments: list[dict], credit: dict | None) -> tuple[str, str]:
    lines = [
        f"Hello {customer['name']} team,",
        "",
        f"Since {datetime.fromisoformat(customer['started_at']):%H:%M} UTC on {_day(customer['started_at'])} some requests to {', '.join(customer['features'])} have been failing. "
        "We have identified the cause and are rolling out a fix.",
    ]
    for commitment in commitments:
        lines += ["", f"On {_day(commitment['made_at'])} we told you: \"{commitment['quote']}\" We have not met that, and {customer['account_manager_name']} will call you directly."]
    if credit:
        lines += ["", f"Your agreement {credit['contract']} guarantees {credit['uptime_target']}% uptime. If this month falls below it, the {credit['credit_percent']}% service credit will be applied without you needing to ask."]
    lines += ["", f"Reference: {incident}", customer["account_manager_name"]]
    return f"Service disruption affecting {', '.join(customer['features'])}", "\n".join(lines)


def postmortem(graph: Graph, investigation: str) -> tuple[str, dict]:
    """Postmortem text plus the extraction sidecar, so it can be ingested back like any other document."""
    head = read(
        graph,
        """
        MATCH (v:Investigation {id: $id})-[:INVESTIGATES]->(i:Incident)
        RETURN i.id AS incident, i.title AS title, i.started_at AS started_at, i.resolved_at AS resolved_at,
               v.service AS alerted, v.root_kind AS root_kind, v.root_id AS root_id, v.root_service AS root_service,
               v.root_title AS root_title, v.confirmed_by AS confirmed_by
        """,
        id=investigation,
    )[0]
    findings = read(graph, "MATCH (:Investigation {id: $id})-[:HAS_FINDING]->(f:Finding) RETURN f.kind AS kind, f.claim AS claim ORDER BY f.at", id=investigation)
    merged = read(
        graph,
        "MATCH (:Investigation {id: $id})-[:PROPOSED]->(r:Remediation {status: 'merged'}) RETURN r.kind AS kind, r.title AS title, r.pr AS pr, r.merged_at AS merged_at ORDER BY merged_at",
        id=investigation,
    )
    summary = f"{head['title']}. First alert on {head['alerted']}."
    cause = f"{head['root_id']} ({head['root_title']}) in {head['root_service']}."
    lines = [
        f"# Postmortem {head['incident']}: {head['title']}",
        "",
        f"Started: {head['started_at']}",
        f"Resolved: {head['resolved_at'] or 'not yet resolved'}",
        f"Root cause confirmed by: {head['confirmed_by']}",
        "",
        "## Summary",
        summary,
        "",
        "## Root cause",
        cause,
        "",
        "## What the investigation found",
        *[f"- ({finding['kind']}) {finding['claim']}" for finding in findings],
        "",
        "## Resolution",
        *([f"- {item['merged_at']}: {item['kind']} merged as {item['pr']} ({item['title']})" for item in merged] or ["- No code change merged."]),
    ]
    sidecar = {
        "id": f"PM-{head['incident']}",
        "type": "postmortem",
        "title": lines[0].removeprefix("# "),
        "nodes": [{"label": "Incident", "id": head["incident"], "props": {"summary": summary}, "quote": summary}],
        "links": [
            {"from": ["Incident", head["incident"]], "type": "CAUSED_BY", "to": [head["root_kind"], head["root_id"]], "quote": cause},
            *[{"from": ["PR", item["pr"]], "type": "FIXES", "to": ["Incident", head["incident"]]} for item in merged],
        ],
        "mentions": [["Service", head["alerted"]], ["Service", head["root_service"]]],
    }
    return "\n".join(lines) + "\n", sidecar
