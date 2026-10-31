import json
import os
import re

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from ripple import access, queries
from ripple.graph import connect
from ripple.investigation import Context

TRACE = {"investigation": {"type": "string", "description": "Optional investigation id; when given, the call is recorded as a step so its results can be cited."}}


def parameters(name: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\$(\w+)", queries.QUERIES[name].cypher)))


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


def tools() -> list[types.Tool]:
    graph_tools = [
        types.Tool(name=name, description=query.doc, input_schema=_schema({**{param: {"type": "string"} for param in parameters(name)}, **TRACE}, parameters(name)))
        for name, query in queries.QUERIES.items()
    ]
    return [
        *graph_tools,
        types.Tool(name="find_entity", description="Resolve free text to nodes in the company graph (full-text search).", input_schema=_schema({"text": {"type": "string"}}, ["text"])),
        types.Tool(name="entity", description="Everything known about one node: properties, neighbours, and the source records behind it.", input_schema=_schema({"kind": {"type": "string"}, "id": {"type": "string"}}, ["kind", "id"])),
        types.Tool(
            name="record_finding",
            description="Store a claim on an investigation. Rejected unless every cited node (as Kind:id) was returned by a traced tool call.",
            input_schema=_schema({"investigation": {"type": "string"}, "kind": {"type": "string"}, "key": {"type": "string"}, "claim": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}}, ["investigation", "kind", "key", "claim", "cites"]),
        ),
    ]


async def list_tools(_context, _params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=tools())


async def call_tool(_context, params: types.CallToolRequestParams) -> types.CallToolResult:
    try:
        text, failed = json.dumps(call(params.name, params.arguments or {}), indent=1), False
    except (KeyError, ValueError) as error:
        text, failed = f"{type(error).__name__}: {error}", True
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=failed)


def call(name: str, arguments: dict) -> object:
    graph = connect(os.getenv("RIPPLE_TENANT", "northwind"))
    company = access.view(graph, None)
    if name == "find_entity":
        return [hit for hit in queries.find_entity(graph, arguments["text"]) if company.sees(f"{hit['kind']}:{hit['id']}")]
    if name == "entity":
        found = queries.entity(graph, arguments["kind"], arguments["id"])
        return access.narrow(found, company) if found and company.sees(f"{arguments['kind']}:{arguments['id']}") else None
    if name == "record_finding":
        ctx = Context.load(graph, arguments["investigation"], "external")
        return {"finding": ctx.finding(arguments["kind"], arguments["key"], arguments["claim"], arguments["cites"])}
    params = {param: arguments[param] for param in parameters(name)}
    if arguments.get("investigation"):
        return Context.load(graph, arguments["investigation"], "external").tool(name, **params)
    return queries.redact(name, queries.run(graph, name, **params), company.hidden)[0]


server = Server("ripple", on_list_tools=list_tools, on_call_tool=call_tool)


async def serve() -> None:
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


def main() -> None:
    anyio.run(serve)
