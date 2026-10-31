from falkordb import Graph

from ripple import ingest

# source: key in ingest.SOURCES when the connector reads that system's export today; None when only planned.
CATALOG = [
    {"id": "hr", "name": "HR directory", "category": "People", "systems": ["Workday", "BambooHR", "Okta"], "reads": "people CSV export", "produces": ["Person", "Team", "Identity"], "source": "hr"},
    {"id": "catalog", "name": "Service catalog", "category": "Systems", "systems": ["Backstage", "Kubernetes"], "reads": "Backstage catalog-info YAML", "produces": ["Service", "Vendor", "Repo"], "source": "catalog"},
    {
        "id": "git", "name": "Git host", "category": "Systems", "systems": ["GitHub", "GitLab"], "reads": "a GitHub repository's merged pull requests, or a pull requests JSON export", "produces": ["PR", "Repo"], "source": "git",
        "live": {
            "pull": "Connect GitHub",
            "fields": [
                {"name": "repo", "label": "Repository", "placeholder": "owner/name or a github.com link"},
                {"name": "token", "label": "Access token, for private repositories and for posting findings", "placeholder": "github_pat_…", "secret": True, "optional": True},
                {"name": "limit", "label": "Newest changes to read", "placeholder": "10", "optional": True},
            ],
            "help": "Reads the newest merged pull requests with their files and reviewers, or the commits when there are none, and counts each merge as a deploy. Ripple then keeps checking the repository, and opens an investigation for every new issue labelled incident. The token is kept in a file on this machine until you disconnect.",
        },
    },
    {"id": "deploys", "name": "Deploy log", "category": "Systems", "systems": ["Argo CD", "GitHub Actions"], "reads": "deploy events JSON", "produces": ["Deploy"], "source": "deploys"},
    {"id": "oncall", "name": "On-call schedule", "category": "People", "systems": ["PagerDuty", "Opsgenie"], "reads": "schedule JSON", "produces": ["ON_CALL_FOR windows"], "source": "oncall"},
    {"id": "alerts", "name": "Alerts", "category": "Systems", "systems": ["Prometheus", "Grafana", "Datadog"], "reads": "Alertmanager webhook at /hooks/alerts", "produces": ["Alert", "Incident", "Investigation"], "source": "webhook"},
    {
        "id": "vendor_status", "name": "Vendor status pages", "category": "Systems", "systems": ["Statuspage"], "reads": "a vendor's public Statuspage site, or a status feed JSON", "produces": ["Vendor", "Outage"], "source": "vendor_status",
        "watch": {
            "pull": "Watch a status page",
            "fields": [
                {"name": "vendor", "label": "Vendor, by its id in the service catalog", "placeholder": "github"},
                {"name": "url", "label": "Status page address", "placeholder": "https://www.githubstatus.com"},
            ],
            "help": "Reads the vendor's ten newest incidents from its public Statuspage site and keeps checking every minute. An incident that is still open becomes a suspect for any alert on a service that depends on the vendor.",
        },
    },
    {"id": "crm", "name": "CRM", "category": "Customers", "systems": ["Salesforce", "HubSpot"], "reads": "accounts CSV export", "produces": ["Customer", "Identity"], "source": "crm"},
    {"id": "product_map", "name": "Product map", "category": "Customers", "systems": ["Notion", "Confluence"], "reads": "feature-to-service YAML", "produces": ["Product", "Feature"], "source": "product_map"},
    {"id": "projects", "name": "Projects", "category": "People", "systems": ["Linear", "Jira"], "reads": "projects JSON export", "produces": ["Project"], "source": "projects"},
    {"id": "calendar", "name": "Shared calendar", "category": "Customers", "systems": ["Google Calendar"], "reads": "iCalendar (.ics)", "produces": ["Event"], "source": "calendar"},
    {"id": "email", "name": "Email", "category": "Documents", "systems": ["Gmail", "Outlook"], "reads": ".eml messages", "produces": ["Email", "Commitment"], "source": "email"},
    {"id": "documents", "name": "Documents", "category": "Documents", "systems": ["Confluence", "Notion", "Google Drive"], "reads": "Markdown: ADRs, contracts, postmortems, requirement documents", "produces": ["Doc", "Decision", "Contract", "SLA", "Requirement"], "source": "documents"},
    {"id": "uploads", "name": "Anything you paste", "category": "Documents", "systems": [], "reads": "any text, dropped in the app", "produces": ["Doc", "MENTIONS links"], "source": "uploads"},
    {
        "id": "gmail", "name": "Gmail", "category": "Documents", "systems": ["Gmail"], "reads": "the newest inbox messages over IMAP, or .eml and .mbox files",
        "produces": ["Email", "Contact", "Commitment", "Note"], "source": "gmail",
        "inbox": {
            "accepts": ".eml,.mbox", "pull": "Connect the mailbox",
            "fields": [
                {"name": "address", "label": "Gmail address", "placeholder": "you@company.com"},
                {"name": "app_password", "label": "App password", "placeholder": "16 letters", "secret": True},
                {"name": "limit", "label": "Newest messages to read", "placeholder": "20", "optional": True},
            ],
            "help": "Create an app password in your Google account under Security, App passwords. Ripple reads the inbox every minute and sends approved customer notices from it. The password is kept in a file on this machine until you disconnect. Each mail can be read only by the people on it until one of them shares it.",
        },
    },
    {
        "id": "drive", "name": "Google Drive and Word", "category": "Documents", "systems": ["Google Drive", "Google Docs", "Word"], "reads": "a Google Doc, Sheet or Slides link, or .docx, .txt, .md and .csv files",
        "produces": ["Doc", "Commitment", "Note"], "source": "drive",
        "inbox": {
            "accepts": ".docx,.txt,.md,.csv", "pull": "Read the file",
            "fields": [{"name": "url", "label": "Link to a Google Doc, Sheet or Slides file", "placeholder": "https://docs.google.com/document/d/…"}],
            "help": "The file must be shared as 'Anyone with the link'. Signing in to read a private Drive is not built.",
        },
    },
    {
        "id": "slack", "name": "Slack", "category": "People", "systems": ["Slack"], "reads": "channels a bot was invited to, or a workspace export .zip",
        "produces": ["Conversation", "Channel", "Contact", "Commitment", "Note"], "source": "slack",
        "inbox": {
            "accepts": ".zip", "pull": "Connect the workspace",
            "fields": [
                {"name": "token", "label": "Bot token", "placeholder": "xoxb-…", "secret": True},
                {"name": "channel", "label": "Channel for approved pages and status updates", "placeholder": "incidents", "optional": True},
                {"name": "limit", "label": "Newest messages per channel", "placeholder": "20", "optional": True},
            ],
            "help": "The bot needs channels:read, channels:history, users:read, users:read.email and chat:write, and an /invite to each channel. Ripple reads those channels every minute and posts approved pages and status updates in the one you name. The token is kept in a file on this machine until you disconnect.",
        },
    },
    {
        "id": "whatsapp", "name": "WhatsApp", "category": "People", "systems": ["WhatsApp"], "reads": "a chat exported from the app (.txt or .zip)",
        "produces": ["Conversation", "Channel", "Contact", "Commitment", "Note"], "source": "whatsapp",
        "inbox": {"accepts": ".txt,.zip", "pull": None, "fields": [], "help": "In WhatsApp open the chat, choose Export chat, then Without media. Reading live from WhatsApp is not built. A chat can be read only by the people in it until one of them shares it."},
    },
    {"id": "chat", "name": "Team chat", "category": "People", "systems": ["Microsoft Teams"], "reads": "channel history", "produces": ["Message", "Commitment"], "source": None},
    {"id": "tickets", "name": "Tickets", "category": "Customers", "systems": ["Jira", "Linear", "Zendesk"], "reads": "issues and support tickets", "produces": ["Ticket"], "source": None},
    {"id": "traces", "name": "Traces and logs", "category": "Systems", "systems": ["Sentry", "OpenTelemetry"], "reads": "error groups and spans", "produces": ["Error", "CALLS edges"], "source": None},
]


def catalog() -> list[dict]:
    """Each connector plus the export file name it accepts as an upload, when it reads a single file."""
    return [{**connector, "file": ingest.EXPORT_FILES.get(connector["source"])} for connector in CATALOG]


def overview(graph: Graph, examples: set[str] = frozenset()) -> list[dict]:
    """The catalog with each connector's live state: record and node counts come from the graph."""
    synced = {source["id"]: source for source in ingest.source_overview(graph)}

    def state(connector: dict) -> dict:
        if connector["source"] is None:
            return {"status": "planned"}
        if connector["source"] == "webhook":
            return {"status": "listening"}
        source = synced.get(connector["source"])
        if not source or not source["records"]:
            return {"status": "ready"}
        return {"status": "connected", "records": source["records"], "nodes": source["nodes"], "last_sync": source["last_sync"], "uri": source["uri"]}

    return [{**connector, **state(connector), "example": connector["source"] in examples} for connector in catalog()]
