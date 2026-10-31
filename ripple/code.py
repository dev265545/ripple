import ast
import re
from pathlib import Path

from falkordb import Graph

from ripple import ingest, world
from ripple.graph import write

SOURCE = "code"
MAX_CODE = 4000
HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", re.M)
PR_SUBJECT = re.compile(r"\((PR-\d+)\)$")


def index(graph: Graph, repo: Path) -> None:
    """Puts a repository's files, symbols, who-uses-what and which pull request touched what into the graph."""
    write(graph, "MERGE (s:Source {id: $id}) SET s.name = 'Code index', s.uri = $uri", id=SOURCE, uri=str(repo.parent))
    files = {path: (repo / path).read_text() for path in world.git(repo, "ls-files", "*.py").stdout.split()}
    parsed = {path: symbols(path, text) for path, text in files.items()}
    known = {symbol["id"] for found in parsed.values() for symbol in found}
    methods = _unique_methods(parsed)
    for path, text in files.items():
        record = ingest.Record(f"{repo.name}:{path}", f"{repo.name}/{path}", text)
        file = record.node("File", f"{repo.name}:{path}", name=path, path=path, repo=repo.name, test=path.startswith("tests/"), lines=text.count("\n"))
        record.edge(("Service", repo.name), "HAS_CODE", file)
        imported = _imports(ast.parse(text))
        for symbol in parsed[path]:
            user = file
            if symbol["name"]:
                user = record.node("Symbol", f"{repo.name}:{symbol['id']}", name=symbol["name"], kind=symbol["kind"], path=path, line=symbol["line"], code=symbol["code"][:MAX_CODE])
                record.edge(file, "DEFINES", user)
            for used in sorted((_resolve(symbol, imported, parsed[path], methods) & known) - {symbol["id"]}):
                record.edge(user, "REFERENCES", ("Symbol", f"{repo.name}:{used}"))
        ingest.store(graph, SOURCE, record)
    for line in world.git(repo, "log", "main", "--first-parent", "--format=%H %s").stdout.splitlines():
        commit, subject = line.split(" ", 1)
        if found := PR_SUBJECT.search(subject):
            link(graph, repo, found[1], commit)


def link(graph: Graph, repo: Path, pr: str, commit: str) -> None:
    """Records the files and symbols a merged commit changed as what its pull request touched."""
    record = ingest.Record(f"{repo.name}:{pr}", f"{repo.name}@{commit[:7]}", commit)
    for path, names in touched(repo, commit).items():
        record.edge(("PR", pr), "TOUCHES", ("File", f"{repo.name}:{path}"))
        for name in names:
            record.edge(("PR", pr), "TOUCHES", ("Symbol", f"{repo.name}:{name}"))
    ingest.store(graph, SOURCE, record)


def touched(repo: Path, commit: str) -> dict[str, list[str]]:
    found = {}
    for path in world.git(repo, "diff", "--name-only", f"{commit}~1", commit).stdout.split():
        diff = world.git(repo, "diff", "--unified=0", f"{commit}~1", commit, "--", path).stdout
        spans = [(int(start), int(start) + int(count or 1)) for start, count in HUNK.findall(diff)]
        after = world.git(repo, "show", f"{commit}:{path}", check=False).stdout if path.endswith(".py") else ""
        found[path] = [
            symbol["id"] for symbol in symbols(path, after)
            if symbol["name"] and any(start <= symbol["end"] and symbol["line"] < max(stop, start + 1) for start, stop in spans)
        ]
    return found


def symbols(path: str, text: str) -> list[dict]:
    """Top-level functions, classes, methods and constants of a module; the entry with no name is the module's own code."""
    module = path.removesuffix(".py").replace("/", ".")
    found, loose = [], []
    for node in ast.parse(text).body if text else []:
        if isinstance(node, ast.ClassDef):
            methods = [child for child in node.body if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)]
            found.append(_symbol(module, node.name, "class", node, text, node.bases + [child for child in node.body if child not in methods]))
            found += [_symbol(module, f"{node.name}.{method.name}", "method", method, text) for method in methods]
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found.append(_symbol(module, node.name, "function", node, text))
        elif isinstance(node, ast.Assign) and all(isinstance(target, ast.Name) for target in node.targets):
            found += [_symbol(module, target.id, "constant", node, text) for target in node.targets]
        elif not isinstance(node, ast.Import | ast.ImportFrom):
            loose.append(node)
    return [*found, {"id": module, "name": "", "kind": "module", "line": 0, "end": 0, "code": "", "mentions": _mentions(loose)}]


def _symbol(module: str, name: str, kind: str, node: ast.AST, text: str, body: list[ast.AST] | None = None) -> dict:
    return {
        "id": f"{module}.{name}", "name": name, "kind": kind, "line": node.lineno, "end": node.end_lineno,
        "code": ast.get_source_segment(text, node) or "", "mentions": _mentions([node] if body is None else body),
    }


def _mentions(nodes: list[ast.AST]) -> tuple[set[str], set[str]]:
    walked = [child for node in nodes for child in ast.walk(node)]
    return {child.id for child in walked if isinstance(child, ast.Name)}, {child.attr for child in walked if isinstance(child, ast.Attribute)}


def _imports(tree: ast.Module) -> dict[str, str]:
    return {alias.asname or alias.name: f"{node.module}.{alias.name}" for node in tree.body if isinstance(node, ast.ImportFrom) for alias in node.names}


def _unique_methods(parsed: dict[str, list[dict]]) -> dict[str, str]:
    owners: dict[str, list[str]] = {}
    for symbol in (symbol for found in parsed.values() for symbol in found if symbol["kind"] == "method"):
        owners.setdefault(symbol["name"].rsplit(".", 1)[1], []).append(symbol["id"])
    return {name: ids[0] for name, ids in owners.items() if len(ids) == 1}


def _resolve(symbol: dict, imported: dict[str, str], siblings: list[dict], methods: dict[str, str]) -> set[str]:
    local = {sibling["name"]: sibling["id"] for sibling in siblings if sibling["name"]} | imported
    names, attributes = symbol["mentions"]
    # ponytail: x.method() resolves by method name when only one class in the repo has it; needs type inference beyond that
    return {local[name] for name in names if name in local} | {methods[name] for name in attributes if name in methods}
