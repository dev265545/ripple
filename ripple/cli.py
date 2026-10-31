import argparse
import json
import os

from ripple import agents, demo, evaluate, ingest, load, world
from ripple.graph import connect
from ripple.investigation import open_incident, parse_alerts, state


def main() -> None:
    parser = argparse.ArgumentParser(prog="ripple")
    parser.add_argument("--tenant", default=os.getenv("RIPPLE_TENANT", "northwind"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed", help="rebuild the tenant graph and service repositories from the world files")
    commands.add_parser("sync", help="re-read every source; unchanged records are skipped")
    commands.add_parser("fire", help="fire a scenario and run the investigation").add_argument("scenario")
    commands.add_parser("eval", help="run every scenario on a fresh tenant and report accuracy")
    commands.add_parser("read", help="score the model reader on the packaged documents against their hand-written links")
    commands.add_parser("load", help="race workers for tasks across tenants")
    serve = commands.add_parser("serve", help="HTTP API and web UI")
    serve.add_argument("--port", type=int, default=8642)
    serve.add_argument("--host", default="127.0.0.1", help="0.0.0.0 lets other devices on the network open it; the API has no login")
    commands.add_parser("mcp", help="MCP server over stdio")
    args = parser.parse_args()

    if args.command == "seed":
        demo.load_history(args.tenant, world.seed(args.tenant))
        print(json.dumps(ingest.source_overview(connect(args.tenant)), indent=1))
    elif args.command == "sync":
        print(json.dumps(ingest.sync_all(connect(args.tenant), world.world_of(args.tenant)), indent=1))
    elif args.command == "fire":
        graph = connect(args.tenant)
        scenario = next(item for item in world.scenarios(world.world_of(args.tenant)) if item["id"] == args.scenario)
        world.apply_scenario(graph, scenario)
        investigation, _ = open_incident(graph, parse_alerts(scenario["alert"])[0])
        agents.run(args.tenant, investigation)
        report = state(graph, investigation)
        for finding in report["findings"]:
            print(f"[{finding['kind']}] {finding['claim']}\n    cites {', '.join(finding['refs'])}")
        for item in report["remediations"]:
            print(f"[{item['kind']}] {item['title']} (tests {'pass' if item['tests_passed'] else 'fail'}) {item['warning']}")
    elif args.command == "eval":
        print(json.dumps(evaluate.evaluate(), indent=1))
    elif args.command == "read":
        print(json.dumps(evaluate.reading(), indent=1))
    elif args.command == "load":
        print(json.dumps(load.run(), indent=1))
    elif args.command == "serve":
        import uvicorn

        uvicorn.run("ripple.api:app", host=args.host, port=args.port)
    elif args.command == "mcp":
        os.environ["RIPPLE_TENANT"] = args.tenant
        from ripple.mcp_server import main as serve_mcp

        serve_mcp()
