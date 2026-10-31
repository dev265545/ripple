import json
import os
import shutil
import subprocess
from pathlib import Path

from falkordb import Graph

from ripple import checks, code, ingest
from ripple.graph import PREFIX, apply_schema, connect, drop

HOME = Path(os.getenv("RIPPLE_HOME", ".ripple"))
DEFAULT_WORLD = Path(os.getenv("RIPPLE_WORLD", "world/northwind"))
GIT = ["git", "-c", "user.name=ripple", "-c", "user.email=ripple@localhost", "-c", "commit.gpgsign=false", "-c", "advice.detachedHead=false"]


def demo_world(tenant: str) -> Path:
    """The packaged company with this name, or the default one for any other demo tenant."""
    named = DEFAULT_WORLD.parent / tenant
    return named if named.is_dir() else DEFAULT_WORLD


def tenant_of(graph: Graph) -> str:
    return graph.name.removeprefix(PREFIX)


def runtime(tenant: str) -> Path:
    return HOME / tenant


def world_of(tenant: str) -> Path:
    return Path((runtime(tenant) / "world").read_text())


def packaged(tenant: str) -> bool:
    """True for an example company, whose source files are the ones shipped in the repository."""
    return world_of(tenant).resolve() == demo_world(tenant).resolve()


def seed(tenant: str, world: Path = DEFAULT_WORLD) -> Graph:
    """Fresh tenant: empty graph, schema, every source synced, service repositories rebuilt."""
    drop(tenant)
    shutil.rmtree(runtime(tenant), ignore_errors=True)
    (runtime(tenant) / "docs").mkdir(parents=True)
    (runtime(tenant) / "world").write_text(str(world.resolve()))
    graph = connect(tenant)
    apply_schema(graph)
    ingest.sync_all(graph, world)
    for folder in sorted((world / "code").glob("*")):
        _build_repo(repo_path(tenant, folder.name), folder / "patches")
        code.index(graph, repo_path(tenant, folder.name))
    checks.upkeep(graph)
    return graph


def create(tenant: str) -> Graph:
    """A new, empty company: its own folder for uploaded exports and a graph with the schema applied."""
    folder = runtime(tenant) / "company"
    folder.mkdir(parents=True)
    (runtime(tenant) / "docs").mkdir()
    (runtime(tenant) / "world").write_text(str(folder.resolve()))
    graph = connect(tenant)
    apply_schema(graph)
    return graph


def repo_path(tenant: str, repo: str) -> Path:
    return runtime(tenant) / "repos" / repo


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run([*GIT, *args], cwd=repo, capture_output=True, text=True, check=check)


def _build_repo(repo: Path, patches: Path) -> None:
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "am", *[str(patch.resolve()) for patch in sorted(patches.glob("*.patch"))])


def scenarios(world: Path = DEFAULT_WORLD) -> list[dict]:
    return [json.loads(file.read_text()) for file in sorted((world / "scenarios").glob("*.json"))]


def apply_scenario(graph: Graph, scenario: dict) -> None:
    """Feeds a scenario's extra source records through the normal connectors, as if they had just arrived."""
    folder = runtime(tenant_of(graph)) / "scenarios" / scenario["id"]
    folder.mkdir(parents=True, exist_ok=True)
    for source, records in scenario["ingest"].items():
        file = folder / f"{source}.json"
        file.write_text(json.dumps(records))
        ingest.sync(graph, source, file)
