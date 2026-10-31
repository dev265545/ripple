"""Writes Forkline: an invented company that sells a managed graph database built on the FalkorDB repository.

Staff, customers, contracts, mail and chat are made up. The repository and its pull requests are real and are not written here.
Run: uv run python forkline/make.py [YYYY-MM-DD]   (the day the company's story ends; today by default)
"""

import csv
import io
import json
import random
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

OUT = Path(__file__).parent / "data"
DOMAIN = "forkline.example"
REPO = "FalkorDB"
TODAY = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(tzinfo=UTC) if len(sys.argv) > 1 else datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
rng = random.Random(11)

# id, name, team, role, manager, git handle
PEOPLE = [
    ("mara", "Mara Lindqvist", "Leadership", "CEO", "", ""),
    ("idris", "Idris Okafor", "Leadership", "CTO", "mara", ""),
    ("hana", "Hana Kobayashi", "Query", "Engineering Lead", "idris", ""),
    ("leo", "Leo Brandt", "Query", "Senior Engineer", "hana", ""),
    ("priya", "Priya Nair", "Query", "Engineer", "hana", ""),
    ("tomas", "Tomas Reyes", "Storage", "Engineering Lead", "idris", ""),
    ("wen", "Wen Zhao", "Storage", "Site Reliability Engineer", "tomas", ""),
    ("kofi", "Kofi Mensah", "Storage", "Engineer", "tomas", ""),
    ("sara", "Sara Haddad", "Indexing", "Engineering Lead", "idris", ""),
    ("emil", "Emil Novak", "Indexing", "Engineer", "sara", ""),
    ("ines", "Ines Duarte", "Cloud", "Engineering Lead", "idris", ""),
    ("jonas", "Jonas Weber", "Cloud", "Engineer", "ines", ""),
    ("dev", "Dev Gupta", "Storage", "Engineer", "tomas", "dev265545"),
    ("nadia", "Nadia Petrova", "Sales", "VP Sales", "mara", ""),
    ("omar", "Omar Farouk", "Sales", "Account Executive", "nadia", ""),
    ("lucy", "Lucy Bennett", "Sales", "Account Executive", "nadia", ""),
    ("ravi", "Ravi Kapoor", "Customer Success", "Head of Customer Success", "mara", ""),
    ("anya", "Anya Sokolova", "Customer Success", "Account Manager", "ravi", ""),
    ("ben", "Ben Achterberg", "Customer Success", "Account Manager", "ravi", ""),
    ("chloe", "Chloe Martin", "Customer Success", "Account Manager", "ravi", ""),
    ("felix", "Felix Aldana", "Support", "Support Lead", "ravi", ""),
    ("grace", "Grace Oyelaran", "Support", "Support Engineer", "felix", ""),
    ("yusuf", "Yusuf Demir", "Product", "Product Manager", "mara", ""),
    ("zoe", "Zoe Hartmann", "Growth", "Marketing Lead", "mara", ""),
]
NAME = {id: name for id, name, *_ in PEOPLE}
ADDRESS = {id: f"{id}@{DOMAIN}" for id in NAME}

# id, description, type, tier, owner, folders, depends on
SERVICES = [
    (REPO, "The database as customers run it", "service", 1, "Storage", [], ["component:module"]),
    ("module", "Redis module that receives every command", "service", 1, "Storage", ["src/commands"], ["component:parser", "component:planner", "component:runtime", "component:persistence", "resource:redis"]),
    ("parser", "Turns Cypher text into a syntax tree", "library", 1, "Query", ["graph/src/parser"], []),
    ("planner", "Chooses how a query is run", "library", 1, "Query", ["graph/src/planner"], ["component:parser", "component:index"]),
    ("runtime", "Runs a planned query, functions and procedures", "library", 1, "Query", ["graph/src/runtime", "graph/src/udf"], ["component:storage", "component:index"]),
    ("storage", "Nodes, relationships and the matrices that hold them", "library", 1, "Storage", ["graph/src/storage", "graph/src/graph", "graph/src/effects"], ["component:native-deps"]),
    ("index", "Range, full-text and vector indexes", "library", 1, "Indexing", ["graph/src/index"], ["component:native-deps", "resource:redisearch"]),
    ("persistence", "Snapshots, loading and replication records", "library", 1, "Storage", ["src/serializers"], ["component:storage", "resource:object-storage"]),
    ("native-deps", "Bundled native libraries", "library", 2, "Indexing", ["native-deps", "deps"], ["resource:graphblas"]),
    ("packaging", "Images and release builds", "service", 2, "Cloud", ["build", ".github"], ["resource:cloud-provider", "resource:github"]),
]
VENDORS = {"redis": "Redis server", "graphblas": "GraphBLAS", "redisearch": "RediSearch", "object-storage": "Object storage", "cloud-provider": "Cloud provider", "github": "GitHub"}
PRODUCTS = {
    "Forkline Graph Cloud": {"Cypher queries": ["parser", "planner", "runtime"], "Full-text search": ["index"], "Vector search": ["index", "native-deps"], "Range indexes": ["index"], "Backups and restore": ["persistence"], "Replication": ["persistence", "storage"]},
    "Forkline Platform": {"Managed clusters": ["packaging", "module"], "Bulk import": ["module", "storage"], "Slow query log": ["module"], "User-defined functions": ["runtime"]},
}
FEATURES = [feature for features in PRODUCTS.values() for feature in features]
SERVES = {feature: services for features in PRODUCTS.values() for feature, services in features.items()}

FIRST = ["Harbor", "Quill", "Cinder", "Juniper", "Atlas", "Meridian", "Saffron", "Tidewater", "Brightwell", "Corvid", "Lumen", "Pinecrest", "Vantage", "Orchard", "Kestrel", "Marlow",
         "Sable", "Fennel", "Ironbark", "Halcyon", "Thistle", "Cobalt", "Wren", "Larch", "Solstice", "Garnet", "Drift", "Ember", "Nimbus", "Osprey", "Peregrine", "Sorrel", "Tamarack", "Umber", "Verity", "Willow"]
SECOND = ["Analytics", "Robotics", "Health", "Logistics", "Bank", "Games", "Labs", "Energy", "Freight", "Media", "Insurance", "Systems"]
CUSTOMERS = []
for index, first in enumerate(FIRST):
    second = SECOND[index % len(SECOND)]
    plan = "enterprise" if index < 10 else "team" if index < 24 else "starter"
    revenue = {"enterprise": rng.randrange(18, 60) * 1000, "team": rng.randrange(2, 9) * 1000, "starter": rng.randrange(2, 9) * 100}[plan]
    CUSTOMERS.append({
        "id": first.lower(), "name": f"{first} {second}", "domain": f"{first.lower()}{second.lower()}.example", "plan": plan, "monthly_revenue_usd": revenue,
        "account_manager": NAME[["anya", "ben", "chloe"][index % 3]], "features": ";".join(sorted(rng.sample(FEATURES, {"enterprise": 5, "team": 3, "starter": 2}[plan]))),
        "contact": rng.choice(["Aiko Tanaka", "Marcus Bell", "Elif Kaya", "Daniel Osei", "Rosa Vidal", "Peter Lang", "Samira Aziz", "Tara Whitlock", "Hugo Mertens", "Nora Quinn"]),
    })
ENTERPRISE = CUSTOMERS[:10]


def at(days_ago: float, hour: int = 10, minute: int = 0) -> datetime:
    return TODAY - timedelta(days=days_ago) + timedelta(hours=hour, minutes=minute)


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def manager(customer: dict) -> str:
    return next(id for id, name in NAME.items() if name == customer["account_manager"])


def contact(customer: dict) -> str:
    return f"{customer['contact']} <{customer['contact'].split()[0].lower()}@{customer['domain']}>"


def staff(id: str) -> str:
    return f"{NAME[id]} <{ADDRESS[id]}>"


def tables() -> None:
    rows = io.StringIO()
    writer = csv.writer(rows)
    writer.writerow(["id", "name", "email", "git_handle", "team", "role", "manager"])
    writer.writerows([id, name, ADDRESS[id], handle, team, role, boss] for id, name, team, role, boss, handle in PEOPLE)
    (OUT / "people.csv").write_text(rows.getvalue())

    rows = io.StringIO()
    writer = csv.DictWriter(rows, ["id", "name", "domain", "plan", "monthly_revenue_usd", "account_manager", "features"], extrasaction="ignore")
    writer.writeheader()
    writer.writerows(CUSTOMERS)
    (OUT / "customers.csv").write_text(rows.getvalue())

    entities = [f"apiVersion: backstage.io/v1alpha1\nkind: Resource\nmetadata: {{name: {id}, description: {name}}}\nspec: {{type: external-api, owner: Platform}}" for id, name in VENDORS.items()]
    for id, description, kind, tier, owner, folders, needs in SERVICES:
        notes = {"forkline/tier": str(tier)} | ({"forkline/paths": ", ".join(f"{REPO}/{folder}" for folder in folders)} if folders else {})
        entities.append(f"apiVersion: backstage.io/v1alpha1\nkind: Component\nmetadata: {json.dumps({'name': id, 'description': description, 'annotations': notes})}\nspec: {json.dumps({'type': kind, 'owner': owner, 'dependsOn': needs})}")
    (OUT / "catalog.yaml").write_text("\n---\n".join(entities) + "\n")

    products = [{"name": product, "features": [{"name": feature, "served_by": services} for feature, services in features.items()]} for product, features in PRODUCTS.items()]
    (OUT / "product_map.yaml").write_text(json.dumps({"products": products}, indent=1) + "\n")

    rota = {"module": ["wen", "kofi", "dev"], "runtime": ["leo", "priya"], "index": ["emil", "sara"], "persistence": ["kofi", "wen"], "packaging": ["jonas", "ines"], REPO: ["wen", "dev", "kofi"]}
    shifts = [
        {"service": service, "email": ADDRESS[people[week % len(people)]], "start": stamp(at(14 - 7 * week, 0)), "end": stamp(at(7 - 7 * week, 0))}
        for service, people in rota.items() for week in range(5)
    ]
    (OUT / "oncall.json").write_text(json.dumps({"shifts": shifts}, indent=1))

    projects = [
        {"id": "PRJ-numeric-index", "name": "Native numeric index", "status": "active", "goal": "Range queries on numbers answer from the index without a full scan.", "started": stamp(at(30)), "due": stamp(at(-20)), "lead": ADDRESS["sara"], "team": "Indexing", "services": ["index"], "customers": ["cinder", "atlas"]},
        {"id": "PRJ-safe-restore", "name": "Restores that cannot corrupt", "status": "active", "goal": "A damaged snapshot is refused with a clear error instead of loading half a graph.", "started": stamp(at(21)), "due": stamp(at(-10)), "lead": ADDRESS["tomas"], "team": "Storage", "services": ["persistence"], "customers": ["harbor", "meridian"]},
        {"id": "PRJ-parser-parity", "name": "Parser parity", "status": "active", "goal": "Every query the old parser accepted is accepted by the new one, with the same result.", "started": stamp(at(18)), "due": stamp(at(-25)), "lead": ADDRESS["hana"], "team": "Query", "services": ["parser"], "customers": ["quill"]},
        {"id": "PRJ-private-link", "name": "Private network access", "status": "planned", "goal": "Enterprise customers reach their clusters without crossing the public internet.", "started": stamp(at(5)), "due": stamp(at(-60)), "lead": ADDRESS["yusuf"], "team": "Cloud", "services": ["packaging", "module"], "customers": ["juniper", "saffron", "tidewater"]},
    ]
    (OUT / "projects.json").write_text(json.dumps(projects, indent=1))

    events = [(ENTERPRISE[0], -2, "moves its fraud graph to production"), (ENTERPRISE[3], -4, "quarterly release freeze"), (ENTERPRISE[6], -1, "launch week for its recommendations service"), (ENTERPRISE[8], -6, "board demo of its knowledge graph assistant")]
    blocks = [
        f"BEGIN:VEVENT\nUID:EVT-{customer['id']}\nSUMMARY:{customer['name']} {what}\nCATEGORIES:customer:{customer['id']}\nDTSTART:{at(days_ago, 8):%Y%m%dT%H%M%SZ}\nDTEND:{at(days_ago - 3, 18):%Y%m%dT%H%M%SZ}\nEND:VEVENT"
        for customer, days_ago, what in events
    ]
    (OUT / "calendar.ics").write_text("BEGIN:VCALENDAR\nVERSION:2.0\n" + "\n".join(blocks) + "\nEND:VCALENDAR\n")
    (OUT / "vendor_status.json").write_text(json.dumps({"outages": [{"id": "OUT-storage-0917", "vendor": "object-storage", "title": "Elevated error rates on snapshot uploads", "start": stamp(at(23, 14)), "end": stamp(at(23, 16))}]}, indent=1))


def documents() -> None:
    folder = OUT / "documents"
    folder.mkdir(exist_ok=True)
    for index, customer in enumerate(ENTERPRISE):
        covered = customer["features"].split(";")[:2]
        uptime, credit = [99.9, 99.95, 99.5][index % 3], [10, 15, 20, 25][index % 4]
        (folder / f"CON-2026-{101 + index}.md").write_text(
            f"# Master Services Agreement CON-2026-{101 + index}: {customer['name']}\n\n"
            f"Signed by {customer['account_manager']} for Forkline and {customer['contact']} for {customer['name']} on {at(200 - 12 * index):%Y-%m-%d}.\n\n"
            f"## Service levels\nForkline guarantees {uptime}% monthly uptime for {covered[0]} and {covered[1]}.\n"
            f"If monthly uptime falls below the target, {customer['name']} receives a service credit of {credit}% of that month's fees.\n\n"
            f"## Support\nForkline answers urgent requests from {customer['name']} within one hour, every day of the year.\n"
        )
    decisions = [
        ("ADR-11", "Every customer gets its own database process", "tomas", "module", "Each customer's graphs run in a database process of their own, so that one customer's heavy query cannot slow another's.", "A customer with many small graphs pays for memory it does not use."),
        ("ADR-12", "Snapshots go to object storage every fifteen minutes", "tomas", "persistence", "persistence writes a snapshot of every cluster to object storage every fifteen minutes.", "A failure between two snapshots can lose up to fifteen minutes of writes on a cluster without a replica."),
        ("ADR-13", "Queries on shared plans stop after thirty seconds", "hana", "runtime", "runtime stops any query on a shared plan that has run for thirty seconds.", "A legitimate analytical query on a shared plan is cut off and has to be moved to a dedicated plan."),
        ("ADR-14", "Engine upgrades go one minor version at a time", "ines", "packaging", "packaging upgrades a cluster by one minor engine version at a time and waits a day between steps.", "A fix that only exists two versions ahead takes at least two days to reach a customer."),
        ("ADR-15", "Vector indexes are built on a replica", "sara", "index", "A new vector index is built on a replica and swapped in, so that building it never blocks writes on the primary.", "A cluster without a replica cannot build a vector index without a short pause in writes."),
    ]
    for id, title, who, service, decision, risk in decisions:
        (folder / f"{id}.md").write_text(f"# {id}: {title}\n\nStatus: Accepted\nDate: {at(60):%Y-%m-%d}\nDeciders: {NAME[who]}\n\n## Decision\n{decision}\n\n## Risks\n{risk}\n\n## Applies to\nThis decision governs {service}.\n")
    (folder / "BRD-7-enterprise-rollouts.md").write_text(
        f"# BRD-7: Enterprise rollouts\n\nOwner: {NAME['yusuf']}\nDate: {at(40):%Y-%m-%d}\n\n## Background\n{ENTERPRISE[0]['name']} is moving its fraud graph to Forkline and asked for guarantees before it does.\n\n"
        "## Requirements\nR1. module must keep 2,000 connections open at once without dropping any.\nR2. runtime must answer 99% of two-hop queries within 50 milliseconds.\nR3. Enterprise customers must be told about any outage within 15 minutes.\n"
    )


def mail() -> None:
    letters = []

    def send(sender: str, to: str, subject: str, body: str, when: datetime, reply_to: str | None = None) -> str:
        message = EmailMessage()
        id = f"<m{len(letters) + 1:03d}@{DOMAIN}>"
        message["Message-ID"], message["From"], message["To"], message["Subject"], message["Date"] = id, sender, to, subject, format_datetime(when)
        if reply_to:
            message["In-Reply-To"] = reply_to
        message.set_content(body)
        letters.append(message)
        return id

    for index, customer in enumerate(ENTERPRISE):
        owner, feature, person = manager(customer), customer["features"].split(";")[0], customer["contact"].split()[0]
        days = 16 - index
        if index % 3 == 0:
            asked = send(contact(customer), staff(owner), f"{feature} before our launch", f"Hi {NAME[owner].split()[0]},\n\nWe put {feature} in front of our own customers next week. The last outage cost us half a day.\nCan you promise it will stay up?\n\n{person}", at(days, 9))
            send(staff(owner), contact(customer), f"Re: {feature} before our launch", f"Hi {person},\n\nWe commit to zero unplanned downtime on {feature} for {customer['name']} through {at(-14):%d %B}.\nIf anything goes wrong I will call you personally within 15 minutes.\n\n{NAME[owner]}", at(days, 11, 20), asked)
        elif index % 3 == 1:
            asked = send(contact(customer), staff(owner), f"Yesterday's trouble with {feature}", f"Hi {NAME[owner].split()[0]},\n\n{feature} stopped answering for about forty minutes yesterday afternoon and nobody told us.\nWe need to understand what happened.\n\n{person}", at(days, 8, 30))
            answered = send(staff(owner), contact(customer), f"Re: Yesterday's trouble with {feature}", f"Hi {person},\n\nI am sorry. We will send {customer['name']} a written root cause report within two business days of any outage.\nWe will also credit this month's invoice by 10%.\n\n{NAME[owner]}", at(days, 10, 5), asked)
            send(contact(customer), staff(owner), f"Re: Yesterday's trouble with {feature}", f"Thank you. Please make sure the report covers {feature} specifically.\n\n{person}", at(days, 13), answered)
        else:
            asked = send(contact(customer), staff("yusuf"), "Private network access and audit logs", f"Hi Yusuf,\n\nOur security team will not approve production use without private network access. We also need audit logs of every query.\nIs either on your roadmap?\n\n{person}", at(days, 14))
            send(staff("yusuf"), f"{contact(customer)}, {staff(owner)}", "Re: Private network access and audit logs", f"Hi {person},\n\nPrivate network access is planned and we are looking into audit logs in module. I cannot give a date for either yet.\n{NAME[owner]} will keep you posted.\n\n{NAME['yusuf']}", at(days, 16, 40), asked)

    for index, customer in enumerate(CUSTOMERS[10:22]):
        owner, feature, person = manager(customer), customer["features"].split(";")[0], customer["contact"].split()[0]
        days = 20 - index
        topic = index % 4
        if topic == 0:
            asked = send(contact(customer), staff("felix"), "Security questionnaire", f"Hello,\n\nAttached is our vendor security questionnaire. We need it back before we renew.\n\n{person}", at(days, 9, 15))
            send(staff("felix"), contact(customer), "Re: Security questionnaire", f"Hi {person},\n\nWe will return the completed questionnaire to {customer['name']} by {at(days - 5):%d %B}.\n\n{NAME['felix']}", at(days, 12), asked)
        elif topic == 1:
            asked = send(contact(customer), staff(owner), "Renewal pricing", f"Hi {NAME[owner].split()[0]},\n\nOur renewal is next month and the budget is tight. What can you do on price for {feature}?\n\n{person}", at(days, 10))
            send(staff(owner), contact(customer), "Re: Renewal pricing", f"Hi {person},\n\nWe will hold {customer['name']}'s current price for another twelve months if you renew before {at(days - 20):%d %B}.\n\n{NAME[owner]}", at(days, 15, 30), asked)
        elif topic == 2:
            send(contact(customer), staff("grace"), f"{feature} is slow on large graphs", f"Hello,\n\n{feature} takes over ten seconds on our largest graph since last week.\nIs this known?\n\n{person}", at(days, 11))
            send(staff("grace"), contact(customer), f"Re: {feature} is slow on large graphs", f"Hi {person},\n\nYes, it is known and the Query team is working on it in planner. I will write to you as soon as the fix ships.\n\n{NAME['grace']}", at(days, 11, 50))
        else:
            send(staff(owner), contact(customer), "Your onboarding session", f"Hi {person},\n\nYour onboarding session for {feature} is booked. We will give {customer['name']} three hours of hands-on training at no charge.\n\n{NAME[owner]}", at(days, 9, 40))

    send(staff("ines"), f"{staff('anya')}, {staff('ben')}, {staff('chloe')}", "Heads-up: engine upgrades slow down", f"Hi all,\n\nFollowing ADR-14, packaging now upgrades a cluster one minor version at a time and waits a day between steps.\nCustomers on Managed clusters who ask for a fix may wait two days for it.\n\n{NAME['ines']}", at(3, 9))
    send(staff("wen"), staff("ravi"), "On-call cover during the Harbor launch", f"Ravi,\n\nI will be on call for module during the whole {ENTERPRISE[0]['name']} launch, and Kofi Mensah covers nights.\n\n{NAME['wen']}", at(2, 17))
    send(staff("nadia"), staff("mara"), "Pipeline this quarter", f"Mara,\n\n{ENTERPRISE[1]['name']} and {ENTERPRISE[4]['name']} both asked for Vector search on the enterprise plan. Omar Farouk is running both deals.\n\n{NAME['nadia']}", at(6, 8))
    (OUT / "mail.mbox").write_bytes(b"".join(f"From forkline {format_datetime(TODAY)}\n".encode() + message.as_bytes() + b"\n" for message in letters))


def chat() -> None:
    users = [{"id": f"U{index:03d}", "name": id, "real_name": name, "profile": {"email": ADDRESS[id], "real_name": name}} for index, (id, name, *_) in enumerate(PEOPLE)]
    user = {member["name"]: member["id"] for member in users}
    channels: dict[str, list[tuple[datetime, str, str]]] = {}

    def say(channel: str, days_ago: float, hour: int, minute: int, who: str, text: str) -> None:
        channels.setdefault(channel, []).append((at(days_ago, hour, minute), who, text))

    say("incidents", 12, 14, 2, "wen", "module is refusing new connections on three clusters in eu-west. Looking.")
    say("incidents", 12, 14, 9, "kofi", "Snapshot uploads are failing and the local disk filled up. object-storage shows errors on its status page.")
    say("incidents", 12, 14, 31, "wen", "Cleared old snapshots, connections are back. Decision: we will alert at 80% disk on every cluster from today.")
    say("incidents", 12, 14, 40, "anya", f"{ENTERPRISE[1]['name']} noticed. I am writing to them now.")
    say("incidents", 5, 9, 15, "emil", "Vector search queries are timing out for a few customers. redisearch looks healthy.")
    say("incidents", 5, 9, 48, "sara", "It was our index rebuild running on the primary, against ADR-15. Moved it to the replica.")
    say("incidents", 5, 10, 5, "ben", f"{ENTERPRISE[4]['name']} and {CUSTOMERS[12]['name']} both wrote in about Vector search. Telling them it is fixed.")
    say("eng-storage", 9, 11, 0, "tomas", "A truncated snapshot loaded half a graph on a test cluster last night. persistence has to refuse those.")
    say("eng-storage", 9, 11, 12, "dev", "I can take that. Checking the length before decoding should catch most of it.")
    say("eng-storage", 9, 11, 30, "tomas", "Decision: persistence refuses any snapshot that ends early and the cluster keeps its previous one.")
    say("eng-storage", 4, 16, 20, "wen", "Reminder that ADR-12 is live: persistence snapshots every fifteen minutes.")
    say("eng-storage", 4, 16, 44, "kofi", "Two clusters without replicas asked what they would lose in a failure. Up to fifteen minutes of writes.")
    say("eng-storage", 1, 10, 10, "tomas", "Capacity check before the Harbor launch: module held 2,400 connections in the load run last night.")
    say("eng-query", 8, 13, 0, "hana", "The new parser rejects a few queries the old one accepted, mostly odd number spellings. parser needs parity before Friday.")
    say("eng-query", 8, 13, 25, "leo", "On it. Decision: we will not roll a parser change to customers until the compatibility suite passes on it.")
    say("eng-query", 3, 15, 5, "hana", "Two-hop queries answer in 31 milliseconds at the 99th percentile in runtime. R2 from BRD-7 is met.")
    say("eng-indexing", 7, 10, 30, "sara", "The native numeric index lands this week in index. Cinder Health and Atlas Bank are waiting on it.")
    say("eng-indexing", 7, 10, 52, "emil", "Range indexes on mixed number types still fall back to a scan. planner does not pick the index for them.")
    say("eng-indexing", 2, 14, 15, "sara", "Decision: when planner cannot prove an index covers a filter, it scans instead of guessing.")
    say("cs-accounts", 10, 9, 5, "ravi", "Renewals this month: Juniper Logistics, Saffron Labs, Tidewater Energy. All three asked about private network access.")
    say("cs-accounts", 10, 9, 30, "chloe", "Saffron Labs will not renew without it. I told them it is planned, no date.")
    say("cs-accounts", 6, 11, 45, "anya", f"{ENTERPRISE[0]['name']} moves its fraud graph to production next week on Managed clusters. They want a named contact.")
    say("cs-accounts", 6, 12, 0, "ravi", "Anya Sokolova is the named contact for Harbor Analytics for the whole launch.")
    say("cs-accounts", 1, 15, 20, "ben", "Quill Robotics is asking when Range indexes cover dates. Sara says this month.")
    say("releases", 11, 17, 0, "jonas", "Engine 6.0.3 is on every shared cluster: faster start after a restore.")
    say("releases", 4, 17, 0, "ines", "This week's engine release fixes Cypher queries that used a block comment before a division.")
    say("releases", 0.5, 9, 0, "jonas", "Engine 6.0.4 with the numeric index goes to dedicated clusters this week, one minor version at a time.")

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as export:
        export.writestr("users.json", json.dumps(users))
        export.writestr("channels.json", json.dumps([{"id": f"C{index:03d}", "name": name} for index, name in enumerate(channels)]))
        for name, lines in channels.items():
            days: dict[str, list[dict]] = {}
            for moment, who, text in lines:
                days.setdefault(f"{moment:%Y-%m-%d}", []).append({"type": "message", "user": user[who], "text": text, "ts": f"{moment.timestamp():.6f}"})
            for day, messages in days.items():
                export.writestr(f"{name}/{day}.json", json.dumps(messages))
    (OUT / "slack-export.zip").write_bytes(archive.getvalue())


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    tables()
    documents()
    mail()
    chat()
    print(f"{len(PEOPLE)} people, {len(CUSTOMERS)} customers, {len(SERVICES)} services, {len(list((OUT / 'documents').glob('*.md')))} documents, mail.mbox, slack-export.zip in {OUT}")
