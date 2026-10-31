import json
import random
import time
from datetime import datetime, timedelta

from ripple import agents, ingest, model, world
from ripple.graph import drop, read
from ripple.investigation import open_incident, parse_alerts

TENANT = "eval"
RESULTS = world.HOME / "eval.json"
READING = world.HOME / "reading.json"
# Free model tiers allow a few thousand tokens a minute; a document read too soon comes back empty.
READING_PAUSE_SECONDS = 20
ALERT_AT = datetime(2026, 10, 20, 12, 0)
TIME = "%Y-%m-%dT%H:%M:%SZ"


def run_scenario(graph, scenario: dict) -> dict:
    world.apply_scenario(graph, scenario)
    investigation, _ = open_incident(graph, parse_alerts(scenario["alert"])[0])
    agents.run(TENANT, investigation)
    found = read(
        graph,
        """
        MATCH (v:Investigation {id: $id})
        OPTIONAL MATCH (v)-[:HAS_STEP]->(st:Step {agent: 'investigator'})
        RETURN v.root_kind + ':' + v.root_id AS root, v.playbook AS playbook, v.steps AS steps, count(st) AS investigator_steps
        """,
        id=investigation,
    )[0]
    return {"scenario": scenario["id"], "title": scenario["title"], "truth": scenario["truth"], "investigation": investigation, **found, "correct": found["root"] == scenario["truth"]}


def generate(graph, count: int, seed: int) -> list[dict]:
    """Random incidents with a planted cause and red herrings. The cause is hidden from the investigator."""
    rng = random.Random(seed)
    reach = read(
        graph,
        """
        MATCH (s:Service)-[:DEPENDS_ON*0..2]->(d:Service)
        OPTIONAL MATCH (d)-[:DEPENDS_ON]->(v:Vendor)
        RETURN s.id AS service, collect(DISTINCT d.id) AS downstream, collect(DISTINCT v.id) AS vendors
        ORDER BY service
        """,
    )
    everything = sorted(row["service"] for row in reach)
    authors = [row["handle"].removeprefix("git:") for row in read(graph, "MATCH (i:Identity) WHERE i.id STARTS WITH 'git:' RETURN i.id AS handle ORDER BY handle")]
    scenarios = []
    for index in range(count):
        target = rng.choice([row for row in reach if len(row["downstream"]) > 1])
        number = 900 + index * 10
        pulls, deploys, outages = [], [], []

        def change(offset: int, service: str, title: str, file: str, hours_before: float, deployed: bool = True) -> str:
            merged = ALERT_AT - timedelta(hours=hours_before)
            pulls.append({"number": number + offset, "title": title, "user": {"login": rng.choice(authors)}, "merged_at": merged.strftime(TIME),
                          "base": {"repo": {"name": service}}, "files": [file], "reviews": [], "body": ""})
            if deployed:
                deploys.append({"id": f"D-{number + offset}", "service": service, "pr": number + offset, "env": "production", "status": "success",
                                "at": (merged + timedelta(minutes=10)).strftime(TIME)})
            return f"PR:PR-{number + offset}"

        if target["vendors"] and rng.random() < 0.25:
            cause = None
            vendor = rng.choice(sorted(target["vendors"]))
            outages.append({"id": f"OUT-{number}", "vendor": vendor, "title": "Elevated error rates", "start": (ALERT_AT - timedelta(minutes=20)).strftime(TIME), "end": None})
            truth = f"Vendor:{vendor}"
        else:
            cause = rng.choice(sorted(target["downstream"]))
            truth = change(0, cause, rng.choice(["Lower connection pool size", "Shorten upstream timeout", "Retry failed calls immediately"]), f"{cause}/config.py", rng.uniform(0.5, 6))
        others = sorted(set(target["downstream"]) - {cause})
        change(1, rng.choice(others or target["downstream"]), "Copy and styling tweaks", "ui/labels.py", rng.uniform(0.3, 3))
        change(2, rng.choice(sorted(target["downstream"])), "Raise worker pool size", "deploy/config.yaml", rng.uniform(0.2, 2), deployed=False)
        outside = sorted(set(everything) - set(target["downstream"]))
        if outside:
            change(3, rng.choice(outside), "Lower cache timeout", "cache/config.py", rng.uniform(0.5, 4))
        change(4, rng.choice(sorted(target["downstream"])), "Tune retry limits", "client/config.py", rng.uniform(30, 44))
        scenarios.append({
            "id": f"G{index + 1:02d}", "title": f"Generated: 5xx on {target['service']}", "truth": truth,
            "ingest": {"git": pulls, "deploys": deploys, **({"vendor_status": {"outages": outages}} if outages else {})},
            "alert": {"alerts": [{"status": "firing", "labels": {"alertname": "High5xxRate", "service": target["service"], "severity": "critical"},
                                  "annotations": {"summary": f"{target['service']} 5xx rate elevated"}, "startsAt": ALERT_AT.strftime(TIME)}]},
        })
    return scenarios


def evaluate(generated: int = 12, seed: int = 7) -> dict:
    """Every scenario runs on a freshly seeded tenant, so no run can learn from another unless that is the point."""
    fixed = {scenario["id"]: scenario for scenario in world.scenarios()}
    runs = []
    for scenario in [*fixed.values(), *generate(world.seed(TENANT), generated, seed)]:
        runs.append(run_scenario(world.seed(TENANT), scenario))

    graph = world.seed(TENANT)
    first = run_scenario(graph, fixed["A"])
    agents.confirm(TENANT, first["investigation"], "evaluation")
    graph.query("MATCH (i:Incident {status: 'open'}) SET i.status = 'resolved'")
    warm = run_scenario(graph, fixed["B"])
    cold = next(run for run in runs if run["scenario"] == "B")
    drop(TENANT)

    result = {
        "runs": runs,
        "accuracy": round(sum(run["correct"] for run in runs) / len(runs), 3),
        "memory": {"scenario": "B", "cold_steps": cold["investigator_steps"], "warm_steps": warm["investigator_steps"],
                   "cold_correct": cold["correct"], "warm_correct": warm["correct"], "playbook": warm["playbook"]},
    }
    RESULTS.parent.mkdir(exist_ok=True)
    RESULTS.write_text(json.dumps(result, indent=1))
    return result


def reading() -> dict:
    """Scores the model reader on the packaged documents against the links a person wrote down for each."""
    graph = world.seed(TENANT)
    resolve = lambda label, identity: ingest._resolve(graph, label, identity)
    documents = []
    for file in sorted((world.world_of(TENANT) / "docs").rglob("*.md")):
        text = file.read_text()
        # A made-up id (an SLA has none in the text) cannot be compared by name, so it counts by kind.
        end = lambda pair: f"{pair[0]}:{'*' if pair[0] in ingest.THINGS and pair[1] not in text else pair[1]}"
        triple = lambda link: (end(resolve(*link["from"]) if ":" in link["from"][1] else link["from"]), link["type"], end(resolve(*link["to"]) if ":" in link["to"][1] else link["to"]))
        expected = {triple(link) for link in ingest.extract(file)["links"] if "Commitment" not in (link["from"][0], link["to"][0])}
        time.sleep(READING_PAUSE_SECONDS)
        found = {triple(link) for link in ingest.understand(graph, text, f"COM-{file.stem}")["links"]}
        documents.append({"document": file.stem, "expected": len(expected), "found": len(found), "matched": len(expected & found),
                          "missed": [" ".join(link) for link in sorted(expected - found)], "extra": [" ".join(link) for link in sorted(found - expected)]})
    drop(TENANT)
    total = lambda key: sum(document[key] for document in documents)
    result = {"model": model.name(), "documents": documents, "expected": total("expected"), "found": total("found"), "matched": total("matched")}
    READING.write_text(json.dumps(result, indent=1))
    return result
