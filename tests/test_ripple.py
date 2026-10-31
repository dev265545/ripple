import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ripple import access, actions, agents, areas, chat, checks, demo, fixer, inbox, ingest, load, memory, model, queries, trust, world
from ripple.api import app
from ripple.graph import connect, drop, read
from ripple.investigation import Context, UncitedClaim, add_task, claim_task, open_incident, parse_alerts, resolve, state

TENANT = "test"
AT = "2026-10-04T10:30:00Z"


configured_model = model.settings


# Set at import, not in a fixture: module-scoped fixtures run agents before any function-scoped patch applies.
model.settings = lambda routing=False: None


def fake_model(monkeypatch, *replies):
    queue = list(replies)

    def reply(messages, tools=None, json_reply=False, must_call=True, routing=False):
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(model, "settings", lambda: {"url": "http://model.invalid", "key": "k", "model": "fake-model"})
    monkeypatch.setattr(model, "chat", reply)


@pytest.fixture(scope="module")
def graph():
    yield world.seed(TENANT)
    drop(TENANT)
    drop("test-other")


@pytest.fixture(scope="module")
def scenario():
    return {item["id"]: item for item in world.scenarios()}


@pytest.fixture(scope="module")
def solved(graph, scenario):
    investigation, opened = open_incident(graph, parse_alerts(scenario["A"]["alert"])[0])
    assert opened
    agents.run(TENANT, investigation)
    return investigation


def test_resync_changes_nothing_and_every_fact_has_a_source(graph):
    assert all(stats["changed"] == 0 for stats in ingest.sync_all(graph, world.DEFAULT_WORLD).values())
    unsourced = read(graph, "MATCH (n) WHERE labels(n)[0] IN ['Service', 'PR', 'Decision', 'Customer', 'Commitment', 'SLA', 'Requirement'] AND NOT (n)-[:EVIDENCED_BY]->(:SourceRecord) RETURN n.id AS id")
    assert unsourced == []
    assert read(graph, "MATCH (n) WHERE n.id CONTAINS ':' AND labels(n)[0] IN ['Person', 'Customer'] RETURN n.id AS id") == []


def test_extraction_is_rejected_when_its_quote_is_not_in_the_document(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text("The pool is capped at 20.\n")
    sidecar = {"id": "N-1", "type": "note", "title": "Note", "links": [], "mentions": [],
               "nodes": [{"label": "Decision", "id": "D-1", "props": {}, "quote": "The pool is capped at 50."}]}
    (tmp_path / "docs" / "note.extracted.json").write_text(json.dumps(sidecar))
    with pytest.raises(ValueError, match="quote not found"):
        list(ingest.documents(tmp_path / "docs", lambda label, identity: (label, identity)))


def test_suspects_are_ranked_by_distance_and_carry_the_path_walked(graph):
    rows = queries.run(graph, "suspect_changes", service="checkout-api", since="2026-10-02T10:30:00Z", at=AT)
    assert [(row["pr"], row["hops"]) for row in rows] == [("PR-412", 1), ("PR-416", 1), ("PR-415", 2)]
    assert rows[0]["via"] == ["checkout-api", "payments-core"]
    assert "PR-414" not in {row["pr"] for row in rows}


def test_business_ripple_reaches_customers_contracts_and_promises(graph):
    assert "orchard" not in {row["customer"] for row in queries.run(graph, "affected_customers", service="payments-core")}
    assert [(row["customer"], row["credit_at_risk"]) for row in queries.run(graph, "sla_exposure", service="payments-core")] == [("larkspur", 4200), ("bluepeak", 3100), ("kite", 900)]
    promise = next(row for row in queries.run(graph, "commitments_at_risk", service="checkout-api", at=AT) if row["commitment"] == "COM-larkspur-sale-uptime")
    assert promise["quote"].startswith("We commit to zero checkout downtime") and promise["source"].endswith(".eml")
    assert [row["commitment"] for row in queries.run(graph, "commitments_at_risk", service="checkout-api", at="2026-10-08T00:00:00Z")] == ["COM-bluepeak-notify-15"]


def test_decision_trace_and_dependency_algorithms(graph):
    trace = queries.run(graph, "decision_trace", pr="PR-412")[0]
    assert (trace["decision"], trace["decided_by"], trace["supersedes"], trace["motivated_by"]) == ("ADR-7", "tomas", ["ADR-3"], ["INC-088"])
    assert queries.run(graph, "dependency_path", source="hosted-checkout-web", target="ledger-db")[0]["via"] == ["hosted-checkout-web", "checkout-api", "payments-core", "ledger-db"]
    assert queries.run(graph, "critical_services")[0]["service"] == "payments-core"
    assert queries.run(graph, "who_to_page", service="payments-core", at=AT)[0]["on_call"] == "asha"


def test_investigation_finds_the_cause_and_proposes_two_ways_out(graph, solved):
    report = state(graph, solved)
    assert (report["investigation"]["root_id"], report["investigation"]["status"]) == ("PR-412", "awaiting_approval")
    assert all(task["status"] == "done" for task in report["tasks"])
    assert {finding["kind"] for finding in report["findings"]} >= {"root_cause", "decision", "customers", "sla", "commitment", "requirement", "precedent"}
    assert all(finding["refs"] for finding in report["findings"])
    assert {action["kind"] for action in report["actions"]} == {"page", "status_page", "customer_notice"}
    remediations = {item["kind"]: item for item in report["remediations"]}
    assert remediations["rollback"]["tests_passed"] and "REOPENS_RISK_OF:Decision:ADR-7" in remediations["rollback"]["refs"]
    assert remediations["fix"]["load_passed"] and "RESPECTS:Decision:ADR-7" in remediations["fix"]["refs"]
    assert "test_burst.py" in remediations["fix"]["diff"]
    assert {edge["relation"] for edge in report["canvas"]["edges"]} >= {"DEPENDS_ON", "IMPLEMENTS", "SUPERSEDES"}


def test_a_claim_citing_nodes_no_tool_returned_is_rejected(graph, solved):
    ctx = Context.load(graph, solved, "investigator")
    with pytest.raises(UncitedClaim):
        ctx.finding("root_cause", "invented", "Orchard Toys caused it.", ["Customer:orchard"])
    with pytest.raises(UncitedClaim):
        ctx.finding("root_cause", "uncited", "Trust me.", [])


def test_a_second_alert_on_the_same_chain_joins_the_open_incident(graph, solved):
    alert = {"service": "hosted-checkout-web", "symptom": "High5xxRate", "severity": "critical", "summary": "web 5xx", "at": "2026-10-04T10:32:00Z"}
    assert open_incident(graph, alert) == (solved, False)


def test_merge_resolves_the_incident_and_memory_shortens_the_next_one(graph, solved, scenario):
    repo = world.repo_path(TENANT, "payments-core")
    assert not fixer.run_checks(repo)["load_passed"]
    merged = fixer.merge(graph, f"{solved}:R:rollback", "asha")
    assert merged["load_passed"]
    report = state(graph, solved)
    assert report["incident"]["status"] == "resolved"
    assert read(graph, "MATCH (p:PR {id: $pr})-[:FIXES]->(i:Incident) RETURN i.id AS id", pr=merged["pr"]) == [{"id": report["incident"]["id"]}]
    assert fixer.merge(graph, f"{solved}:R:fix", "ravi")["tests_passed"]
    assert "LEDGER_POOL_SIZE = 20" in (repo / "payments" / "config.py").read_text()
    with pytest.raises(ValueError):
        fixer.merge(graph, f"{solved}:R:fix", "ravi")

    learned = agents.confirm(TENANT, solved, "asha")
    assert learned["tools"] == ["suspect_changes", "change_detail"]
    assert read(graph, "MATCH (d:Doc {id: $id})-[:EVIDENCED_BY]->(:SourceRecord) RETURN count(d) AS n", id=learned["postmortem"])[0]["n"] == 1

    world.apply_scenario(graph, scenario["B"])
    second, _ = open_incident(graph, parse_alerts(scenario["B"]["alert"])[0])
    agents.run(TENANT, second)
    after = state(graph, second)

    def investigator_steps(report):
        return sum(step["agent"] == "investigator" for step in report["steps"])

    assert (after["investigation"]["root_id"], after["investigation"]["playbook"]) == ("PR-421", learned["playbook"])
    assert investigator_steps(after) < investigator_steps(report)
    assert memory.overview(graph)["playbooks"][0]["wins"] == 1


def test_a_vendor_outage_is_blamed_instead_of_a_recent_change(scenario):
    graph = world.seed("test-other")
    assert read(graph, "MATCH (n:Investigation) RETURN count(n) AS n")[0]["n"] == 0
    world.apply_scenario(graph, scenario["C"])
    investigation, _ = open_incident(graph, parse_alerts(scenario["C"]["alert"])[0])
    agents.run("test-other", investigation)
    report = state(graph, investigation)
    assert (report["investigation"]["root_kind"], report["investigation"]["root_id"]) == ("Vendor", "cardnet")
    assert report["remediations"] == []
    assert {task["status"] for task in report["tasks"]} == {"done"}
    assert {action["kind"] for action in report["actions"]} >= {"page", "status_page", "customer_notice"}


def test_merging_the_fix_first_withdraws_the_rollback(scenario):
    graph = world.seed("test-other")
    investigation, _ = open_incident(graph, parse_alerts(scenario["A"]["alert"])[0])
    agents.run("test-other", investigation)
    assert fixer.merge(graph, f"{investigation}:R:fix", "asha")["load_passed"]
    report = state(graph, investigation)
    assert report["incident"]["status"] == "resolved"
    assert {item["kind"]: item["status"] for item in report["remediations"]} == {"fix": "merged", "rollback": "withdrawn"}
    with pytest.raises(ValueError):
        fixer.merge(graph, f"{investigation}:R:rollback", "asha")


SERVE_EVERYTHING = "def serve_burst(pool, charges):\n    return {'served': charges, 'failed': 0}\n"


def test_the_fixer_walks_the_code_graph_and_the_checks_judge_the_model_written_fix(scenario, monkeypatch):
    graph = world.seed("test-other")
    changed = queries.run(graph, "code_impact", pr="PR-412")
    assert [(row["name"], row["used_in"], row["tests"]) for row in changed] == [("LEDGER_POOL_SIZE", ["payments-core:loadcheck.py"], ["payments-core:tests/test_ledger_cap.py"])]
    assert "larkspur" in {customer for row in queries.run(graph, "change_reach", pr="PR-412") for customer in row["customers"]}
    cheat = {"content": "Relax the load check\n--- loadcheck.py\n```python\nprint('fine')\n```", "model": "fake-model"}
    honest = {"content": f"Serve every charge\n--- payments/charges.py\n```python\n{SERVE_EVERYTHING}```", "model": "fake-model"}
    fake_model(monkeypatch, cheat, honest)
    investigation, _ = open_incident(graph, parse_alerts(scenario["A"]["alert"])[0])
    agents.run("test-other", investigation)
    report = state(graph, investigation)
    fix = next(item for item in report["remediations"] if item["kind"] == "fix")
    assert (fix["written_by"], fix["load_passed"], fix["tests_passed"]) == ("fake-model", True, True)
    assert "loadcheck.py" not in fix["diff"]
    walked = [step["tool"] for step in report["steps"] if step["agent"] == "fixer"]
    assert walked == ["run_checks", "code_impact", "code_context", "code_history", "write_fix", "run_checks"]
    merged = fixer.merge(graph, fix["id"], "asha")
    assert read(graph, "MATCH (:PR {id: $pr})-[:TOUCHES]->(s:Symbol) RETURN s.name AS name", pr=merged["pr"]) == [{"name": "serve_burst"}]


def test_the_cloudflare_replay_blames_the_rule_and_finds_the_refactor_behind_it():
    replay = world.demo_world("cloudflare-2019")
    graph = world.seed("test-other", replay)
    investigation, _ = open_incident(graph, parse_alerts(world.scenarios(replay)[0]["alert"])[0])
    agents.run("test-other", investigation)
    report = state(graph, investigation)
    assert report["investigation"]["root_id"] == "PR-742"
    claims = {finding["kind"]: finding["claim"] for finding in report["findings"]}
    assert "PR-701" in claims["code_history"] and "waf.engine.run_rule" in claims["code_history"]
    assert "Discord" in claims["customers"] and "revenue" not in claims["customers"]
    assert "$0.12" in claims["sla"]
    assert not any(finding["kind"] == "commitment" for finding in report["findings"])
    fixes = {item["kind"]: item for item in report["remediations"]}
    assert fixes["rollback"]["load_passed"] and fixes["fix"]["load_passed"] and fixes["fix"]["written_by"] == fixer.PREPARED
    assert "test_rule_cpu.py" in fixes["fix"]["diff"]


def test_each_task_is_claimed_once_and_later_stages_wait(graph):
    graph.query("CREATE (:Investigation {id: 'INV-race', tasks: 0, steps: 0})")
    for _ in range(40):
        add_task(graph, "INV-race", "triage", stage=1)
    late = add_task(graph, "INV-race", "notify", stage=2)
    claimed: list[str] = []

    def worker(name: str) -> None:
        mine = connect(TENANT)
        for _ in range(10):
            task = claim_task(mine, "INV-race", name)
            claimed.append(task["id"])

    threads = [threading.Thread(target=worker, args=(f"w{n}",)) for n in range(4)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert len(set(claimed)) == 40 and late not in claimed
    assert claim_task(graph, "INV-race", "w0") is None


def test_load_run_reports_no_double_claims():
    result = load.run(tenants=2, workers=3, tasks=30)
    assert (result["claimed"], result["double_claims"]) == (60, 0)


def test_api_serves_state_and_refuses_double_approval(graph, solved):
    client = TestClient(app)
    assert client.get(f"/api/{TENANT}/investigations/{solved}").json()["investigation"]["root_id"] == "PR-412"
    action = f"{solved}:A:status_page:public"
    assert client.get(f"/api/{TENANT}/status").json()["updates"] == []
    approved = client.post(f"/api/{TENANT}/actions/{action}/approve", json={"user": "mei"}).json()
    assert (approved["status"], approved["delivered"], approved["url"]) == ("sent", "Published on the status page.", f"/status/{TENANT}")
    assert [update["title"] for update in client.get(f"/api/{TENANT}/status").json()["updates"]] == [approved["subject"]]
    assert client.post(f"/api/{TENANT}/actions/{action}/approve", json={"user": "mei"}).status_code == 409
    called = client.post(f"/api/{TENANT}/tools/blast_radius", json={"params": {"service": "ledger-db"}, "user": "mei"}).json()
    assert "Service:payments-core" in called["refs"]
    assert client.get(f"/api/{TENANT}/turns", params={"user": "mei"}).json()[0]["refs"]
    assert client.get("/api/nope/sources").status_code == 404
    assert client.get(f"/api/{TENANT}/entities/Decision/ADR-7").json()["sources"][0]["quote"].startswith("Each payments-core pod")


def test_mcp_tools_cover_every_named_query():
    from ripple.mcp_server import call, parameters

    assert parameters("suspect_changes") == ["service", "since", "at"]
    assert call("find_entity", {"text": "ledger"}) is not None


def test_a_pasted_document_is_linked_to_what_it_names_with_the_sentence_as_evidence(graph):
    note = "# Call notes with Kite Grocers\n\nKite Grocers asked whether payments-core is affected by PR-412.\nNothing else.\n"
    added = ingest.add_document(graph, world.runtime(TENANT) / "uploads", "Kite call notes.txt", note)
    assert {(entity["kind"], entity["id"]) for entity in added["linked"]} == {("Customer", "kite"), ("Service", "payments-core"), ("PR", "PR-412")}
    trace = ingest.record_trace(graph, added["record"])
    assert trace["text"] == note
    mention = next(edge for edge in trace["edges"] if edge["target"] == "Service:payments-core")
    assert (mention["relation"], mention["quote"]) == ("MENTIONS", "Kite Grocers asked whether payments-core is affected by PR-412.")
    assert ingest.add_document(graph, world.runtime(TENANT) / "uploads", "Kite call notes.txt", note)["changed"] == 0
    assert any(row["id"] == added["record"] for row in ingest.records(graph, "uploads"))
    with pytest.raises(ValueError):
        ingest.add_document(graph, world.runtime(TENANT) / "uploads", "empty", "  ")


def test_inboxes_file_mail_chat_and_files_against_people_and_customers_already_known(graph, monkeypatch):
    client = TestClient(app)
    promise = "We will not run maintenance on payments-core before 08:00 UTC on Fridays, so the Bluepeak Travel Payouts batch always finishes first."
    reading = {"promises": [{"text": "No payments-core maintenance before 08:00 UTC on Fridays.", "quote": promise, "customer": "bluepeak", "made_by": "clara", "valid_to": None},
                            {"text": "Invented.", "quote": "A sentence that is not in the mail.", "customer": "bluepeak", "made_by": "clara"}],
               "note": "Bluepeak's Friday payout batch depends on payments-core staying up until 08:00 UTC."}
    fake_model(monkeypatch, {"content": json.dumps({"promises": [], "note": None})}, {"content": json.dumps(reading)}, {"content": json.dumps({"promises": []})})
    mail = client.post(f"/api/{TENANT}/inbox/gmail/example").json()
    assert (mail["records"], mail["changed"], mail["promises"], mail["notes"]) == (3, 3, 1, 1)
    monkeypatch.setattr(model, "settings", lambda routing=False: None)
    assert client.post(f"/api/{TENANT}/inbox/gmail/example").json()["changed"] == 0
    reply = ingest.record_trace(graph, "gmail:bp-payouts-2@northwindpay.example")
    edges = {(edge["source"], edge["relation"], edge["target"]) for edge in reply["edges"]}
    mail_id = "Email:gmail-bp-payouts-2@northwindpay.example"
    assert edges >= {("Person:clara", "SENT", mail_id), (mail_id, "SENT_TO", "Customer:bluepeak"), (mail_id, "SENT_TO", "Person:ravi"),
                     (mail_id, "REPLIES_TO", "Email:gmail-bp-payouts-1@bluepeak.example"), (mail_id, "MENTIONS", "Service:payments-core")}
    assert [row["commitment"] for row in queries.run(graph, "commitments_at_risk", service="payments-core", at=AT) if row["quote"] == promise] == ["COM-gmail-bp-payouts-2@northwindpay.example-1"]
    assert memory.overview(graph)["notes"][0]["text"] == reading["note"]
    history = queries.run(graph, "customer_history", customer="bluepeak")
    assert {row["item"] for row in history} >= {"gmail-bp-payouts-1@bluepeak.example", "gmail-bp-payouts-2@northwindpay.example"}

    chat_days = client.post(f"/api/{TENANT}/inbox/whatsapp/example").json()
    assert (chat_days["records"], chat_days["notes"]) == (2, 0)
    day = ingest.record_trace(graph, "whatsapp:Larkspur-weekend-sale-2026-10-02")
    said = {(edge["source"], edge["relation"], edge["target"]): edge["quote"] for edge in day["edges"]}
    talk = "Conversation:whatsapp-Larkspur-weekend-sale-2026-10-02"
    assert {("Person:nikhil", "TOOK_PART_IN", talk), ("Person:asha", "TOOK_PART_IN", talk), ("Contact:name:Imogen Hale", "TOOK_PART_IN", talk)} <= set(said)
    assert said[talk, "MENTIONS", "PR:PR-412"] == "09:21 Asha Rao: I am on call. PR-412 went out yesterday, so I will keep an eye on payments-core."
    assert "It is our biggest day of the quarter." in day["text"] and "end-to-end" not in day["text"]

    assert client.post(f"/api/{TENANT}/inbox/slack/example").json()["records"] == 1
    channel = ingest.record_trace(graph, "slack:payments-oncall-2026-10-01")
    assert "14:02 Ravi Menon: Heads up @Asha Rao: PR-412" in channel["text"] and "has joined" not in channel["text"]
    assert {edge["source"] for edge in channel["edges"] if edge["relation"] == "TOOK_PART_IN"} == {"Person:asha", "Person:ravi", "Contact:name:Sam Okoro"}

    word = client.post(f"/api/{TENANT}/inbox/drive/example").json()
    assert (word["records"], word["linked"]) == (1, 5)
    assert client.post(f"/api/{TENANT}/inbox/whatsapp/file?name=notes.pdf", content=b"x").status_code == 422
    assert client.post(f"/api/{TENANT}/inbox/drive/pull", json={"fields": {"url": "https://example.com/doc"}}).status_code == 422
    states = {item["id"]: item for item in client.get(f"/api/{TENANT}/connectors").json()}
    assert (states["slack"]["status"], states["slack"]["example"], states["whatsapp"]["records"]) == ("connected", True, 2)


def test_a_newer_promise_waits_for_a_human_then_replaces_the_older_one_and_a_changed_record_takes_facts_back(graph, monkeypatch):
    client = TestClient(app)
    people = [("name:Nikhil Shah", "Nikhil Shah"), ("name:Tomas Novak", "Tomas Novak")]
    slow, freeze = "We will answer Kite Grocers support tickets within 4 hours.", "We decided payments-core deploys are frozen on Fridays."
    fast = "From now on we will answer Kite Grocers support tickets within 1 hour."
    promise = lambda quote, replaces=None: {"text": quote, "quote": quote, "customer": "kite", "made_by": "nikhil", "replaces": replaces}
    first = {"promises": [promise(slow)], "decisions": [{"text": "No Friday deploys on payments-core.", "quote": freeze, "decided_by": "tomas"}, {"text": "Invented.", "quote": "Not said.", "decided_by": "tomas"}], "note": None}
    fake_model(monkeypatch, {"content": json.dumps(first)}, {"content": json.dumps({"promises": [promise(fast, "COM-whatsapp-support-1-1")]})}, {"content": json.dumps({"promises": [promise(slow)]})})
    day = lambda key, at, text: inbox.Item(key, "Conversation", f"Kite support on {at[:10]}", text, at, others=people, channel="whatsapp:Kite support")
    stats = inbox.file(graph, "whatsapp", [day("support-1", "2026-09-01T10:00:00Z", f"10:00 Nikhil Shah: {slow}\n10:05 Tomas Novak: {freeze}")])
    assert (stats["promises"], stats["decisions"]) == (1, 1)
    assert "DEC-whatsapp-support-1-1" in {row["decision"] for row in queries.run(graph, "governing_decisions", service="payments-core")}
    assert next(row for row in queries.run(graph, "who_knows", service="payments-core") if row["person"] == "nikhil")["discussions"] >= 1

    inbox.file(graph, "whatsapp", [day("support-2", "2026-09-20T09:00:00Z", f"09:00 Nikhil Shah: {fast}")])
    on_the_chat = {"X-Ripple-User": "nikhil"}
    assert client.get(f"/api/{TENANT}/review").json() == client.get(f"/api/{TENANT}/review", headers={"X-Ripple-User": "sofia"}).json() == []
    waiting = client.get(f"/api/{TENANT}/review", headers=on_the_chat).json()
    assert [(row["newer"], row["older"], row["older_quote"]) for row in waiting] == [("COM-whatsapp-support-2-1", "COM-whatsapp-support-1-1", slow)]
    in_force = lambda at: {row["commitment"]: row["replaced_by"] for row in queries.run(graph, "promises_as_of", customer="kite", at=at) if "support" in row["commitment"]}
    assert set(in_force("2026-09-25T00:00:00Z")) == {"COM-whatsapp-support-1-1", "COM-whatsapp-support-2-1"}
    settlement = {"newer": "COM-whatsapp-support-2-1", "older": "COM-whatsapp-support-1-1", "replace": True}
    assert client.post(f"/api/{TENANT}/review", json=settlement | {"user": "sofia"}).status_code == 404
    settled = client.post(f"/api/{TENANT}/review", json=settlement | {"user": "nikhil"})
    assert settled.status_code == 200 and client.get(f"/api/{TENANT}/review", headers=on_the_chat).json() == []
    assert in_force("2026-09-25T00:00:00Z") == {"COM-whatsapp-support-2-1": None}
    assert in_force("2026-09-10T00:00:00Z") == {"COM-whatsapp-support-1-1": "COM-whatsapp-support-2-1"}
    assert client.post(f"/api/{TENANT}/review", json={"newer": "x", "older": "y", "replace": False, "user": "sofia"}).status_code == 404

    inbox.file(graph, "whatsapp", [day("support-1", "2026-09-01T10:00:00Z", f"10:00 Nikhil Shah: {slow}")])
    assert "DEC-whatsapp-support-1-1" not in {row["decision"] for row in queries.run(graph, "governing_decisions", service="payments-core")}
    assert read(graph, "MATCH (d:Decision {id: 'DEC-whatsapp-support-1-1'}) RETURN d.id") == []
    assert in_force("2026-09-10T00:00:00Z") == {"COM-whatsapp-support-1-1": "COM-whatsapp-support-2-1"}


def test_private_mail_gives_two_people_different_answers_until_someone_on_it_shares_it(graph):
    client = TestClient(app)
    record, promise = "gmail:bp-payouts-2@northwindpay.example", "Commitment:COM-gmail-bp-payouts-2@northwindpay.example-1"
    asked = lambda user: chat.answer(graph, "What have we promised that depends on payments-core?", user, f"private-{user}")
    on_it, not_on_it = asked("clara"), asked("mei")
    assert promise in on_it["refs"]
    assert promise not in not_on_it["refs"] and not_on_it["withheld"] > on_it["withheld"] and record not in {cited["record"] for cited in not_on_it["citations"]}
    as_mei, as_clara = {"X-Ripple-User": "mei"}, {"X-Ripple-User": "clara"}
    kind, id = promise.split(":", 1)
    assert client.get(f"/api/{TENANT}/entities/{kind}/{id}", headers=as_mei).status_code == 403
    assert client.get(f"/api/{TENANT}/records/{record}", headers=as_mei).status_code == 403
    assert client.get(f"/api/{TENANT}/entities/{kind}/{id}", headers=as_clara).json()["sources"][0]["visibility"] == "restricted"
    assert promise.split(":", 1)[1] not in {row["id"] for row in client.get(f"/api/{TENANT}/search", params={"q": "maintenance payments-core Fridays"}, headers=as_mei).json()}
    assert "Person:clara" in {f"{other['kind']}:{other['id']}" for other in client.get(f"/api/{TENANT}/entities/Customer/bluepeak", headers=as_mei).json()["neighbours"]}
    assert promise not in {f"{other['kind']}:{other['id']}" for other in client.get(f"/api/{TENANT}/entities/Customer/bluepeak", headers=as_mei).json()["neighbours"]}
    hidden_from_agents = queries.redact("commitments_at_risk", queries.run(graph, "commitments_at_risk", service="payments-core", at=AT), access.view(graph, None).hidden)
    assert promise.split(":", 1)[1] not in {row["commitment"] for row in hidden_from_agents[0]} and hidden_from_agents[1] >= 1

    assert client.post(f"/api/{TENANT}/share", json={"record": record, "user": "mei"}).status_code == 403
    assert client.post(f"/api/{TENANT}/share", json={"record": record, "user": "clara"}).status_code == 200
    assert promise in asked("mei")["refs"]
    client.post(f"/api/{TENANT}/inbox/gmail/example")
    assert promise in asked("mei")["refs"]


def test_an_owner_verifies_for_a_time_and_a_changed_source_or_a_lapsed_date_takes_it_back(graph):
    client = TestClient(app)
    promise = {"kind": "Commitment", "id": "COM-bluepeak-notify-15"}
    assert trust.of(graph, **promise)["state"] == "unverified" and trust.of(graph, **promise)["owner"] == "clara"
    assert "COM-bluepeak-notify-15" in {item["id"] for item in client.get(f"/api/{TENANT}/brief/clara", headers={"X-Ripple-User": "clara"}).json()["to_check"]}
    assert client.post(f"/api/{TENANT}/verify", json=promise | {"user": "mei", "days": 90}).status_code == 403
    assert client.post(f"/api/{TENANT}/verify", json=promise | {"user": "clara", "days": 7}).status_code == 409
    verified = client.post(f"/api/{TENANT}/verify", json=promise | {"user": "clara", "days": 90}).json()
    assert (verified["state"], verified["verified_by"]) == ("verified", "clara") and verified["due_at"] > verified["verified_at"]
    assert "COM-bluepeak-notify-15" not in {item["id"] for item in memory.brief(graph, "clara")["to_check"]}
    assert client.get(f"/api/{TENANT}/entities/Commitment/COM-bluepeak-notify-15").json()["trust"]["state"] == "verified"
    graph.query("MATCH (m:Commitment {id: 'COM-bluepeak-notify-15'})-[:EVIDENCED_BY]->(r) SET m.verified_at = '2026-01-01T00:00:00Z', r.fetched_at = '2025-12-01T00:00:00Z'")
    assert trust.of(graph, **promise)["state"] == "expired"
    assert any("COM-bluepeak-notify-15" in finding["refs"][0] and "ran out on 2026-04-01" in finding["text"] for finding in checks.findings(graph) if finding["refs"])
    graph.query("MATCH (m:Commitment {id: 'COM-bluepeak-notify-15'})-[:EVIDENCED_BY]->(r) SET m.verified_at = '2026-01-01T00:00:00Z', m.verify_days = NULL, r.fetched_at = '2026-02-01T00:00:00Z'")
    assert trust.of(graph, **promise)["state"] == "changed"
    assert trust.of(graph, "Service", "payments-core") is None


def test_rules_find_promises_that_disagree_and_knowledge_that_conflicts_or_has_gone_stale_without_a_model(graph):
    client = TestClient(app)
    assert model.settings() is None
    graph.query("""
        MATCH (c:Customer {id: 'orchard'}), (p:Person {id: 'nikhil'}), (t:Team {id: 'Platform'}), (s:Service {id: 'cart-service'})
        CREATE (p)-[:MADE]->(:Commitment {id: 'COM-rule-old', text: 'Hosted Checkout refunds reach Orchard within 48 hours.', made_at: '2026-08-01T00:00:00Z'})-[:MADE_TO]->(c),
               (p)-[:MADE]->(:Commitment {id: 'COM-rule-new', text: 'Hosted Checkout refunds reach Orchard within 24 hours.', made_at: '2026-09-01T00:00:00Z'})-[:MADE_TO]->(c),
               (p)-[:MADE]->(:Commitment {id: 'COM-rule-other', text: 'We answer Orchard within 2 hours.', made_at: '2026-09-02T00:00:00Z'})-[:MADE_TO]->(c),
               (t)-[:OWNS {src: 'catalog:made-up'}]->(s),
               (:Project {id: 'PRJ-rule-late', name: 'Late project', status: 'active', due_at: '2026-01-31'})
    """)
    assert checks.propose(graph) == 1
    pair = next(row for row in memory.to_review(graph) if row["newer"] == "COM-rule-new")
    assert (pair["older"], pair["found_by"]) == ("COM-rule-old", "rule") and "48 hour" in pair["reason"] and "24 hour" in pair["reason"]
    assert client.post(f"/api/{TENANT}/review", json={"newer": "COM-rule-new", "older": "COM-rule-old", "replace": False, "user": "nikhil"}).status_code == 200
    assert checks.propose(graph) == 0 and not [row for row in memory.to_review(graph) if row["newer"] == "COM-rule-new"]
    found = {finding["text"]: finding for finding in client.get(f"/api/{TENANT}/checks").json()}
    assert found["cart-service is owned by more than one team."]["refs"] == ["Service:cart-service", "Team:Checkout", "Team:Platform"]
    assert found["Late project is still marked active and was due 2026-01-31."]["kind"] == "stale"
    graph.query("MATCH (n) WHERE n.id STARTS WITH 'COM-rule-' OR n.id = 'PRJ-rule-late' DETACH DELETE n")
    graph.query("MATCH (:Team {id: 'Platform'})-[e:OWNS]->(:Service {id: 'cart-service'}) DELETE e")


def test_the_graph_is_clustered_into_areas_and_a_written_summary_keeps_only_findings_about_members(graph, monkeypatch):
    found = {area["id"]: area for area in areas.refresh(graph)}
    payments = found["AREA-Payments"]
    assert payments["title"] == "Payments" and "Service:payments-core" in payments["members"] and payments["written_by"] is None
    assert read(graph, "MATCH (:Service {id: 'payments-core'})-[:IN_AREA]->(a:Area) RETURN a.id AS id") == [{"id": "AREA-Payments"}]
    assert all(area["size"] >= areas.MIN_SIZE for area in found.values()) and len(found) >= 4
    private = access.view(graph, None).hidden
    assert private and not read(graph, "MATCH (n)-[:IN_AREA]->(:Area) WHERE labels(n)[0] + ':' + n.id IN $private RETURN n.id", private=list(private))
    broad = chat.answer(graph, "Give me an overview of the company as a whole", "mei", "areas")
    assert broad["tool"] == "areas" and "Area:AREA-Payments" in broad["refs"]

    written = {"title": "Payments platform", "summary": "The Payments team runs payments-core.", "findings": [
        {"text": "The Payments team owns payments-core.", "refs": ["Team:Payments", "Service:payments-core"]},
        {"text": "It is about something else.", "refs": ["Service:cart-service"]}, {"text": "No refs.", "refs": []}]}
    fake_model(monkeypatch, *[{"content": json.dumps(written)}] * areas.MAX_WRITTEN)
    payments = next(area for area in areas.refresh(graph, written=True) if area["id"] == "AREA-Payments")
    assert (payments["title"], payments["written_by"]) == ("Payments platform", "fake-model")
    assert [finding["refs"] for finding in payments["findings"]] == [["Team:Payments", "Service:payments-core"]]
    monkeypatch.setattr(model, "settings", lambda routing=False: None)
    assert next(area for area in areas.refresh(graph) if area["id"] == "AREA-Payments")["title"] == "Payments platform"


def test_an_entity_carries_dated_history_and_whether_a_promise_still_stands(graph):
    history = [other for other in queries.entity(graph, "Service", "payments-core")["neighbours"] if other["at"]]
    assert {"PR", "Decision"} <= {other["kind"] for other in history} and all(other["at"][:2] == "20" for other in history)
    replaced = queries.entity(graph, "Commitment", "COM-whatsapp-support-1-1")
    assert replaced["props"]["valid_to"] == "2026-09-20T09:00:00Z"
    assert ("SUPERSEDES", False, "COM-whatsapp-support-2-1") in {(other["relation"], other["outgoing"], other["id"]) for other in replaced["neighbours"]}


def test_projects_join_people_changes_and_decisions_and_lone_experts_are_found(graph):
    project = queries.run(graph, "project_status", project="PRJ-ledger-hardening")[0]
    assert (project["lead"], project["decisions"], sorted(project["changes"])) == ("tomas", ["ADR-7"], ["PR-412", "PR-415"])
    assert {"INC-088", "INC-101"} <= set(project["incidents"])
    experts = queries.run(graph, "who_knows", service="payments-core")
    assert experts[0]["score"] >= experts[-1]["score"] and {"changes", "decisions", "discussions", "shifts"} <= set(experts[0])
    assert all(row["person"] for row in queries.run(graph, "single_experts"))
    assert "PR-412" in {row["item"] for row in queries.run(graph, "timeline", service="payments-core")}


def test_chat_answers_from_named_queries_with_citations_and_remembers_the_subject(graph):
    client = TestClient(app)

    def ask(text):
        return client.post(f"/api/{TENANT}/chat", json={"text": text, "user": "clara", "session": "s1"}).json()

    first = ask("Which customers are affected if ledger-db fails?")
    assert first["tool"] == "affected_customers" and any("Larkspur Retail" in line for line in first["lines"])
    assert any(cite["uri"].startswith("customers.csv") for cite in first["citations"])
    follow_up = ask("and who is on call for it?")
    assert (follow_up["tool"], follow_up["carried"], follow_up["params"]["service"]) == ("who_to_page", "Service:ledger-db", "ledger-db")
    assert ask("Why was PR-412 made?")["lines"][0].startswith("ADR-7")
    assert ask("zzzz qqqq")["refs"] == []


def test_login_knows_the_directory_and_connectors_report_live_state(graph):
    client = TestClient(app)
    assert client.post(f"/api/{TENANT}/login", json={"email": "Asha@northwindpay.example"}).json()["id"] == "asha"
    assert client.post(f"/api/{TENANT}/login", json={"email": "nobody@example.com"}).status_code == 401
    states = {item["id"]: item for item in client.get(f"/api/{TENANT}/connectors").json()}
    assert states["hr"]["status"] == "connected" and states["hr"]["records"] == 13
    assert (states["chat"]["status"], states["alerts"]["status"]) == ("planned", "listening")


def test_a_new_company_is_built_from_uploaded_exports():
    client = TestClient(app)
    name = "Onboard Probe"
    tenant = "onboard-probe"
    drop(tenant)
    shutil.rmtree(world.runtime(tenant), ignore_errors=True)
    assert client.post("/api/tenants", json={"name": name}).json() == {"tenant": tenant}
    assert client.post("/api/tenants", json={"name": name}).status_code == 409
    assert client.post(f"/api/{tenant}/login", json={"email": "asha@northwindpay.example"}).status_code == 401
    assert client.post(f"/api/tenants/{tenant}/seed").status_code == 409

    def upload(source: str, text: str):
        return client.post(f"/api/{tenant}/sources/{source}/file", json={"text": text})

    bad = upload("hr", "id,name\nx,Someone\n")
    assert bad.status_code == 422 and "missing field" in bad.json()["detail"]
    for source in ("hr", "catalog", "git"):
        example = client.get(f"/api/connectors/{source}/example").json()["text"]
        assert upload(source, example).json()["changed"] > 0
        assert upload(source, example).json()["changed"] == 0
    assert client.post(f"/api/{tenant}/login", json={"email": "asha@northwindpay.example"}).json()["id"] == "asha"
    assert "checkout-api" in client.get(f"/api/{tenant}/services").json()
    states = {item["id"]: item["status"] for item in client.get(f"/api/{tenant}/connectors").json()}
    assert (states["hr"], states["crm"]) == ("connected", "ready")
    assert client.get(f"/api/{tenant}/scenarios").json() == []
    drop(tenant)
    shutil.rmtree(world.runtime(tenant), ignore_errors=True)


def test_alert_times_from_alertmanager_are_normalised():
    alert = {"status": "firing", "labels": {"alertname": "X", "service": "s"}, "annotations": {"summary": "x"}}
    stamps = ["2026-10-04T10:30:00.123456789Z", "2026-10-04T16:00:00+05:30", AT]
    assert [parse_alerts({"alerts": [{**alert, "startsAt": stamp}]})[0]["at"] for stamp in stamps] == [AT] * 3


def test_the_demo_company_starts_with_a_history():
    tenant = "test-other"
    graph = world.seed(tenant)
    demo.load_history(tenant, graph)
    overview = memory.overview(graph)
    waiting = next(item for item in overview["investigations"] if item["incident_status"] == "open")
    assert sorted((item["incident_status"], item["root"]) for item in overview["investigations"]) == [("open", "PR-412"), ("resolved", "cardnet")]
    assert {item["kind"] for item in state(graph, waiting["id"])["remediations"]} == {"rollback", "fix"}
    assert len(overview["playbooks"]) == 1
    assert len(actions.outbox(graph)) > 0
    assert len([turn for turn in memory.recall_turns(graph, "sofia") if turn["role"] == "user"]) == 3


def test_search_finds_partial_words_and_ids(graph):
    def top(text: str):
        found = queries.find_entity(graph, text)
        return (found[0]["kind"], found[0]["id"]) if found else None

    assert [top(text) for text in ("lark", "PR-412", "pr-412", "?!")] == [("Customer", "larkspur"), ("PR", "PR-412"), ("PR", "PR-412"), None]


def test_a_vendor_outage_is_closed_by_a_person_and_old_incidents_do_not_absorb_new_alerts(scenario):
    graph = world.seed("test-other")
    world.apply_scenario(graph, scenario["C"])
    alert = parse_alerts(scenario["C"]["alert"])[0]
    investigation, _ = open_incident(graph, alert)
    agents.run("test-other", investigation)
    assert open_incident(graph, {**alert, "at": "2026-10-11T15:00:00Z"}) == (investigation, False)
    assert open_incident(graph, {**alert, "at": "2026-10-13T15:00:00Z"})[1]
    with pytest.raises(ValueError):
        resolve(graph, investigation, "asha")
    agents.confirm("test-other", investigation, "asha")
    assert resolve(graph, investigation, "asha")["incident"] == state(graph, investigation)["incident"]["id"]
    assert state(graph, investigation)["incident"]["status"] == "resolved"


def test_the_graph_view_shows_which_source_each_thing_came_from(graph):
    view = ingest.sourced_graph(graph)
    by_key = {f"{node['kind']}:{node['id']}": node for node in view["nodes"]}
    assert by_key["PR:PR-412"]["sources"] == ["git"]
    assert all(node["sources"] and node["kind"] != "Identity" for node in view["nodes"])
    assert all(edge["source"] in by_key and edge["target"] in by_key for edge in view["edges"])
    crossing = [edge for edge in view["edges"] if not set(by_key[edge["source"]]["sources"]) & set(by_key[edge["target"]]["sources"])]
    assert {"source": "PR:PR-412", "relation": "CHANGES", "target": "Service:payments-core"} in crossing


def test_a_model_picks_the_query_and_writes_the_answer_but_never_answers_without_one(graph, monkeypatch):
    picked = {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "who_to_page", "arguments": '{"service": "payments-core"}'}}]}
    fake_model(monkeypatch, picked, {"role": "assistant", "content": "Asha Rao is on call."})
    reply = chat.answer(graph, "Who should I wake up about payments?", "clara", "m1")
    assert (reply["model"], reply["tool"], reply["answer"], reply["params"]["service"]) == ("fake-model", "who_to_page", "Asha Rao is on call.", "payments-core")
    assert reply["rows"] and "Service:payments-core" in reply["refs"] and reply["citations"]
    fake_model(monkeypatch, {"role": "assistant", "content": "I think it is probably Asha."})
    assert chat.answer(graph, "Who is on call for payments-core?", "clara", "m1")["model"] is None
    fake_model(monkeypatch, model.ModelUnavailable("rate limited"))
    routed = chat.answer(graph, "Who is on call for payments-core?", "clara", "m1")
    assert (routed["model"], routed["tool"]) == (None, "who_to_page")


def test_a_model_found_promise_is_kept_only_with_its_exact_sentence(monkeypatch):
    tenant = "test-model"
    graph = world.seed(tenant)
    note = "Call with Kite Grocers.\nWe will refund any failed payout within one business day.\nThanks.\n"
    found = {"promises": [
        {"text": "Refund failed payouts within one business day.", "quote": "We will refund any failed payout within one business day.", "customer": "kite", "made_by": "clara", "valid_to": None},
        {"text": "Invented promise.", "quote": "We guarantee free service forever.", "customer": "kite", "made_by": "clara", "valid_to": None},
        {"text": "Unknown customer.", "quote": "Thanks.", "customer": "nobody", "made_by": "clara", "valid_to": None},
    ]}
    fake_model(monkeypatch, {"role": "assistant", "content": json.dumps(found)})
    try:
        added = ingest.add_document(graph, world.runtime(tenant) / "uploads", "Kite call", note)
        assert [promise["quote"] for promise in added["promises"]] == ["We will refund any failed payout within one business day."]
        stored = read(graph, "MATCH (p:Person)-[:MADE]->(c:Commitment)-[:MADE_TO]->(k:Customer {id: 'kite'}) WHERE c.id STARTS WITH 'COM-kite-call' MATCH (c)-[e:EVIDENCED_BY]->() RETURN p.id AS by, e.quote AS quote")
        assert stored == [{"by": "clara", "quote": "We will refund any failed payout within one business day."}]
    finally:
        drop(tenant)
        shutil.rmtree(world.runtime(tenant), ignore_errors=True)


def test_a_rewritten_message_must_keep_every_fact(solved, graph, monkeypatch):
    draft = read(graph, "MATCH (a:Action {status: 'proposed', kind: 'customer_notice'}) RETURN a.id AS id, a.body AS body LIMIT 1")[0]
    fake_model(monkeypatch, {"role": "assistant", "content": "Sorry, things broke. We will be in touch."})
    with pytest.raises(ValueError, match="original draft was kept"):
        actions.rewrite(graph, draft["id"])
    fake_model(monkeypatch, {"role": "assistant", "content": f"A short note from us.\n\n{draft['body']}"})
    assert actions.rewrite(graph, draft["id"]) == {"body": f"A short note from us.\n\n{draft['body']}", "model": "fake-model"}
    assert read(graph, "MATCH (a:Action {id: $id}) RETURN a.body AS body", id=draft["id"])[0]["body"] == draft["body"]


def test_the_model_client_speaks_the_openai_chat_format(monkeypatch):
    seen = {}

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.update(path=self.path, key=self.headers["Authorization"], body=json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            reply = json.dumps({"choices": [{"message": {"role": "assistant", "content": "hello"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=server.handle_request, daemon=True).start()
    monkeypatch.setattr(model, "settings", lambda: {"url": f"http://127.0.0.1:{server.server_port}/v1/", "key": "secret", "model": "some-model"})
    assert model.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])["content"] == "hello"
    assert (seen["path"], seen["key"], seen["body"]["model"], seen["body"]["tool_choice"]) == ("/v1/chat/completions", "Bearer secret", "some-model", "required")
    monkeypatch.setattr(model, "settings", lambda: None)
    with pytest.raises(model.ModelUnavailable):
        model.chat([{"role": "user", "content": "hi"}])


def test_a_cheaper_model_can_be_named_for_picking_the_query(monkeypatch):
    for variable in ("RIPPLE_MODEL_KEY", "RIPPLE_MODEL", *model.PROVIDERS):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("EXPERIENTIAL_API_KEY", "k")
    assert (configured_model()["model"], configured_model(routing=True)["model"]) == ("deepseek-v4-flash", "deepseek-v4-flash")
    monkeypatch.setenv("RIPPLE_ROUTER_MODEL", "jev-latest")
    assert (configured_model()["model"], configured_model(routing=True)["model"]) == ("deepseek-v4-flash", "jev-latest")


def test_a_rate_limited_model_hands_over_to_its_spare(monkeypatch):
    asked = []

    def complete(found, *rest):
        asked.append(found["model"])
        if found["model"] == "first":
            raise model.RateLimited("first answered 429")
        return {"content": "hello", "model": found["model"]}

    monkeypatch.setattr(model, "settings", lambda: {"url": "http://model.invalid", "key": "k", "model": "first", "spares": ["first", "second"]})
    monkeypatch.setattr(model, "_complete", complete)
    assert (model.chat([{"role": "user", "content": "hi"}])["model"], asked) == ("second", ["first", "second"])


def test_github_changes_are_pull_requests_or_commits(monkeypatch):
    from ripple import github

    replies = {
        "pulls?state": [{"number": 7, "title": "Cap the pool", "user": {"login": "ravim"}, "merged_at": "2026-01-02T00:00:00Z", "body": None, "html_url": "u"}, {"number": 8, "merged_at": None}],
        "pulls/7/files": [{"filename": "pool.py"}],
        "pulls/7/reviews": [{"user": {"login": "elenav"}}, {"user": {"login": "elenav"}}],
    }
    monkeypatch.setattr(github, "_get", lambda url, token: next(reply for part, reply in replies.items() if part in url))
    assert github.changes("https://github.com/acme/ledger.git") == [
        {"number": 7, "title": "Cap the pool", "user": {"login": "ravim"}, "merged_at": "2026-01-02T00:00:00Z", "base": {"repo": {"name": "ledger"}}, "body": "", "html_url": "u", "files": ["pool.py"], "reviews": [{"user": {"login": "elenav"}}]}
    ]

    commit = {"sha": "abcdef1234", "html_url": "c", "author": None, "commit": {"message": "Fix retry\n\nwhy", "author": {"name": "Asha", "date": "2026-01-03T00:00:00Z"}}, "files": [{"filename": "retry.py"}]}
    replies = {"pulls?state": [], "commits?per_page": [commit], "commits/abcdef1234": commit}
    assert github.changes("acme/ledger")[0] | {"html_url": "c"} == {"number": "abcdef1", "title": "Fix retry", "user": {"login": "Asha"}, "merged_at": "2026-01-03T00:00:00Z", "base": {"repo": {"name": "ledger"}}, "body": "why", "html_url": "c", "files": ["retry.py"], "reviews": []}

    with pytest.raises(ValueError):
        github.changes("not a repo")


def test_a_watched_repository_opens_an_incident_from_an_issue_and_replies_after_approval(monkeypatch):
    from ripple import github, watch

    tenant, posted = "test-watch", []
    drop(tenant)
    shutil.rmtree(world.runtime(tenant), ignore_errors=True)
    world.create(tenant)
    change = {"number": 7, "title": "Cap the pool", "user": {"login": "ravim"}, "merged_at": "2026-10-04T09:00:00Z", "base": {"repo": {"name": "ledger"}}, "body": "", "html_url": "https://github.com/acme/ledger/pull/7", "files": ["pool.py"], "reviews": []}
    issue = {"number": 3, "title": "Checkout times out", "created_at": "2026-10-04T10:00:00Z", "labels": [{"name": "incident"}, {"name": "timeouts"}]}
    monkeypatch.setattr(github, "changes", lambda repo, token, limit, known: [] if 7 in known else [change])
    monkeypatch.setattr(github, "issues", lambda repo, token, since: [issue] if since < issue["created_at"] else [])
    monkeypatch.setattr(github, "comment", lambda issue, token, body: posted.append((issue, body)) or "link")
    monkeypatch.setattr(watch, "now", lambda: "2026-10-04T08:00:00Z")

    def start(tenant, alert):
        investigation, opened = open_incident(connect(tenant), alert)
        agents.run(tenant, investigation)
        return {"investigation": investigation, "opened": opened}

    try:
        assert watch.connect(tenant, "acme/ledger", "t", 10, start) | {"records": 1} == {"records": 1, "changed": 1, "read": 1, "incidents": 1}
        assert watch.sync(tenant, start)["incidents"] == 0
        graph = connect(tenant)
        assert read(graph, "MATCH (:Deploy)-[:SHIPPED]->(p:PR) RETURN p.id AS id") == [{"id": "PR-7"}]
        drafted = read(graph, "MATCH (a:Action {kind: 'issue_comment'}) RETURN a.id AS id, a.to AS issue")
        assert [draft["issue"] for draft in drafted] == ["acme/ledger#3"]
        assert not posted
        assert read(graph, "MATCH (v:Investigation) RETURN v.root_id AS root") == [{"root": "PR-7"}]
        actions.approve(graph, drafted[0]["id"], "ravim")
        assert posted[0][0] == "acme/ledger#3" and "INC-1" in posted[0][1]
        revert = read(graph, "MATCH (a:Action {kind: 'revert_pr'}) RETURN a.id AS id, a.to AS pull, a.subject AS subject")
        assert [(draft["pull"], draft["subject"]) for draft in revert] == [("acme/ledger#7", 'Revert "Cap the pool"')]
        monkeypatch.setattr(github, "revert", lambda pull, token, title, body: posted.append((pull, title)) or "https://github.com/acme/ledger/pull/8")
        assert actions.approve(graph, revert[0]["id"], "ravim")["url"] == "https://github.com/acme/ledger/pull/8"
        assert posted[-1] == ("acme/ledger#7", 'Revert "Cap the pool"')
        assert watch.revertable(tenant, "PR-99") is None
        assert watch.signed(tenant, b"{}", "sha256=wrong") is False
    finally:
        drop(tenant)
        shutil.rmtree(world.runtime(tenant), ignore_errors=True)


def test_kept_connections_are_read_again_and_carry_approved_messages(monkeypatch):
    from ripple import live
    from ripple.graph import write

    tenant, said, mailed = "test-live", [], []
    drop(tenant)
    shutil.rmtree(world.runtime(tenant), ignore_errors=True)
    graph = world.create(tenant)
    write(graph, "MERGE (:Vendor {id: 'github', name: 'GitHub'})")
    replies = {
        "conversations.list": {"channels": [{"id": "C1", "name": "incidents", "is_member": True}, {"id": "C2", "name": "random", "is_member": False}]},
        "users.list": {"members": [{"id": "U1", "real_name": "Asha Rao"}]},
        "conversations.history": {"messages": [{"ts": "1759572000", "user": "U1", "text": "restore is slow"}, {"ts": "1759572060", "user": "U9", "bot_id": "B1", "text": "posted by the bot"}]},
    }
    monkeypatch.setattr(inbox, "slack", lambda token, method, **params: said.append((method, params)) or replies.get(method, {}))
    monkeypatch.setattr(live, "status_feed", lambda vendor, url: [{"id": f"OUT-{vendor}-1", "vendor": vendor, "title": "Actions are delayed", "start": "2026-10-04T09:00:00Z", "end": None}])

    class Mailer:
        def __init__(self, host, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *problem):
            return False

        def login(self, address, password):
            mailed.append((address, password))

        def send_message(self, message):
            mailed.append((message["To"], message["Subject"]))

    monkeypatch.setattr(live.smtplib, "SMTP_SSL", Mailer)
    monkeypatch.setattr(inbox, "pull_gmail", lambda address, password, limit: [])
    draft = {"to": "someone", "subject": "Checkout is down", "body": "We are on it."}
    try:
        with pytest.raises(ValueError, match="Known vendors: github"):
            live.connect(tenant, "vendor_status", {"vendor": "nobody", "url": "https://status.example"})
        assert live.connect(tenant, "vendor_status", {"vendor": "github", "url": "https://status.example/"})["changed"] == 1
        assert read(graph, "MATCH (o:Outage)-[:OF]->(:Vendor {id: 'github'}) RETURN o.title AS title, o.ends_at AS ends_at") == [{"title": "Actions are delayed", "ends_at": None}]
        assert live.check(tenant, "vendor_status")["changed"] == 0

        assert actions.deliver(tenant, "oncall", draft | {"kind": "page"}) == ("Approved, not sent: connect Slack to post pages in a channel.", "")
        with pytest.raises(ValueError, match="not in #war-room"):
            live.connect(tenant, "slack", {"token": "xoxb-1", "channel": "#war-room"})
        assert live.connect(tenant, "slack", {"token": "xoxb-1"})["records"] == 1
        assert read(graph, "MATCH (c:Conversation) RETURN c.text AS text") == [{"text": "10:00 Asha Rao: restore is slow"}]
        assert actions.deliver(tenant, "oncall", draft | {"kind": "page"}) == ("Posted in #incidents.", "")
        assert said[-1] == ("chat.postMessage", {"channel": "C1", "text": "*Checkout is down*\nWe are on it."})
        assert actions.deliver(tenant, "public", draft | {"kind": "status_page"}) == ("Published on the status page and posted in #incidents.", f"/status/{tenant}")

        assert actions.deliver(tenant, "acme", draft | {"kind": "customer_notice"})[0].startswith("Approved, not sent")
        live.connect(tenant, "gmail", {"address": "ops@gmail.com", "app_password": "abcd efgh"})
        assert actions.deliver(tenant, "acme inc", draft | {"kind": "customer_notice"}) == ("Emailed to ops+acmeinc@gmail.com.", "")
        assert mailed == [("ops@gmail.com", "abcdefgh"), ("ops+acmeinc@gmail.com", "Checkout is down")]

        shown = json.dumps(live.state(tenant))
        assert "xoxb-1" not in shown and "abcdefgh" not in shown and live.state(tenant)["slack"]["watching"] == "#incidents"
        assert (world.runtime(tenant) / "slack.json").stat().st_mode & 0o077 == 0
        live.disconnect(tenant, "slack")
        assert "slack" not in live.state(tenant)
    finally:
        drop(tenant)
        shutil.rmtree(world.runtime(tenant), ignore_errors=True)


def test_a_model_may_write_its_own_read_only_query_and_can_correct_a_refused_one(graph, monkeypatch):
    def call(cypher):
        return {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "graph_query", "arguments": json.dumps({"cypher": cypher})}}]}

    before = read(graph, "MATCH (t:Team) RETURN count(t) AS teams")
    fake_model(monkeypatch, call("MATCH (t:Team) DETACH DELETE t"), call("MATCH (p:Person)-[:MEMBER_OF]->(t:Team) RETURN t.id AS id, count(p) AS people ORDER BY people DESC LIMIT 3"), {"role": "assistant", "content": "The largest team."})
    reply = chat.answer(graph, "Which team has the most people?", "clara", "w1")
    assert read(graph, "MATCH (t:Team) RETURN count(t) AS teams") == before
    assert (reply["tool"], len(reply["steps"]), reply["answer"]) == ("graph_query", 1, "The largest team.")
    assert reply["rows"] and reply["refs"][0].startswith("Team:")
    assert "(:Person)-[:MEMBER_OF]->(:Team)" in queries.schema(graph)
    count = "MATCH (t:Team) RETURN count(t) AS teams"
    assert queries.written(graph, count, hidden=frozenset({"Team:" + reply["rows"][0]["id"]})) == [{"teams": before[0]["teams"] - 1}]
    assert read(graph, count) == before and not [name for name in graph.client.list_graphs() if name.startswith("view:")]


def test_a_model_read_link_is_kept_only_with_its_sentence_a_known_kind_and_a_named_end():
    text = "Agreement CON-2030-001 with Kite Grocers.\nWe guarantee 99.9% monthly uptime for Payouts.\n"
    read_out = {
        "things": [
            {"kind": "Contract", "id": "CON-2030-001", "quote": "Agreement CON-2030-001 with Kite Grocers.", "props": {"title": "Agreement", "owner": "dropped"}},
            {"kind": "SLA", "id": "sla", "quote": "We guarantee 99.9% monthly uptime for Payouts.", "props": {"uptime_target": 99.9}},
            {"kind": "Weapon", "id": "CON-2030-001", "quote": "Agreement CON-2030-001 with Kite Grocers."},
        ],
        "links": [
            {"from": ["Customer", "kite"], "type": "HAS_CONTRACT", "to": ["Contract", "CON-2030-001"], "quote": "Agreement CON-2030-001 with Kite Grocers."},
            {"from": ["Contract", "CON-2030-001"], "type": "GUARANTEES", "to": ["SLA", "sla"], "quote": "We guarantee 99.9% monthly uptime for Payouts."},
            {"from": ["SLA", "sla"], "type": "COVERS", "to": ["Feature", "Payouts"], "quote": "Payouts never fail."},
            {"from": ["SLA", "sla"], "type": "COVERS", "to": ["Feature", "Refunds"], "quote": "We guarantee 99.9% monthly uptime for Payouts."},
            {"from": ["Customer", "kite"], "type": "OWNS", "to": ["Contract", "CON-2030-001"], "quote": "Agreement CON-2030-001 with Kite Grocers."},
        ],
    }
    found = ingest.structure(read_out, text, {("Customer", "kite"), ("Feature", "Payouts")}, "kite")
    assert found["things"] == [
        {"label": "Contract", "id": "CON-2030-001", "quote": "Agreement CON-2030-001 with Kite Grocers.", "props": {"title": "Agreement"}},
        {"label": "SLA", "id": "SLA-kite-2", "quote": "We guarantee 99.9% monthly uptime for Payouts.", "props": {"uptime_target": 99.9}},
    ]
    assert [(link["from"][1], link["type"], link["to"][1]) for link in found["links"]] == [("kite", "HAS_CONTRACT", "CON-2030-001"), ("CON-2030-001", "GUARANTEES", "SLA-kite-2")]
