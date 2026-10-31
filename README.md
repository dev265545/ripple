# Ripple

**Root cause is only the first ring.** Ripple is a team of incident-response agents that works on one
FalkorDB graph of a company: its code, services, customers, contracts and promises. It follows an
incident from the failing service to the people and SLAs it reaches, and ends with a rollback and a
fix ready to merge.

Built for Graph Hacks (WeMakeDevs × FalkorDB), October 2026.

**Live demo:** _link added after deploy_ (a static snapshot: sign in as Elena Voss for Northwind Pay,
or John Graham-Cumming for the Cloudflare 2019 WAF outage replay).

## Run it locally

```bash
docker compose up -d                 # FalkorDB on 127.0.0.1:6379
uv sync
echo "GROQ_API_KEY=..." > .env        # any OpenAI-compatible key, see ripple/model.py
uv run ripple seed                    # Northwind Pay
RIPPLE_WORLD=world/cloudflare-2019 uv run ripple --tenant cloudflare-2019 seed
uv run ripple serve                   # API on :8642
cd web && npm install && npm run dev  # UI on :5183
```

`uv run ripple eval` runs every scenario on a fresh tenant and reports accuracy. `uv run ripple mcp`
exposes the graph tools over MCP.

## How it works

- **Graph as the product.** Every tool is a Cypher query, agent memory is a subgraph, agent
  coordination is a subgraph, and each tenant is its own graph.
- **Agents.** Triage recalls similar incidents and playbooks, an investigator walks the dependency
  chain, scorers rank suspects, and writers draft customer messages and remediation PRs with tests.
- **Evidence.** Every claim cites the records it rests on, and every answer shows the queries behind it.

See [PLAN.md](PLAN.md) for the full design.

## Static demo build

`web/public/demo` holds recorded API responses. `VITE_RIPPLE_DEMO=1 npm run build` serves them
instead of calling the API, which is what the hosted demo runs.
