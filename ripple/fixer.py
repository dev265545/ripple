import json
import re
import subprocess
import sys
from pathlib import Path

from falkordb import Graph

from ripple import code, ingest, model
from ripple.graph import now, read, write
from ripple.investigation import Context
from ripple.world import git, repo_path, tenant_of, world_of


def propose_rollback(ctx: Context, pr: str) -> str | None:
    """Revert of the offending change on its own branch. Deterministic: no model involved."""
    repo = _repo_of(ctx.graph, pr)
    commit = repo and _commit_of(repo, pr)
    if not commit:
        return None
    branch = f"rollback/{pr}"
    git(repo, "checkout", "-q", "-B", branch, "main")
    git(repo, "revert", "--no-edit", commit)
    reopened = undone_by_reverting(ctx.graph, pr)
    id = _record(ctx, "rollback", repo, branch, f"Revert {pr}", f"Restores the behaviour before {pr}.", revert_warning(reopened))
    write(ctx.graph, "MATCH (r:Remediation {id: $id}), (p:PR {id: $pr}) MERGE (r)-[:REVERTS]->(p)", id=id, pr=pr)
    write(
        ctx.graph,
        "MATCH (r:Remediation {id: $id}) UNWIND $decisions AS decision MATCH (d:Decision {id: decision}) MERGE (r)-[:REOPENS_RISK_OF]->(d)",
        id=id, decisions=[row["decision"] for row in reopened],
    )
    return id


def undone_by_reverting(graph: Graph, pr: str) -> list[dict]:
    return read(
        graph,
        """
        MATCH (:PR {id: $pr})-[:IMPLEMENTS]->(d:Decision)
        OPTIONAL MATCH (d)-[:MOTIVATED_BY]->(i:Incident)
        RETURN d.id AS decision, d.title AS title, collect(i.id) AS incidents
        """,
        pr=pr,
    )


def revert_warning(reopened: list[dict]) -> str:
    return " ".join(
        f"Reverting undoes {row['decision']} ({row['title']})" + (f", which was written to prevent a repeat of {', '.join(row['incidents'])}." if row["incidents"] else ".")
        for row in reopened
    )


def propose_fix(ctx: Context, pr: str) -> str | None:
    """Forward fix on its own branch; only recorded as ready when the repository's checks pass."""
    repo = _repo_of(ctx.graph, pr)
    commit = repo and _commit_of(repo, pr)
    if not commit:
        return None
    branch = f"fix/{ctx.incident}"
    git(repo, "checkout", "-q", "-B", branch, "main")
    relanded = _reland_if_reverted(repo, commit)
    changed = ctx.tool("code_impact", pr=pr)
    around = ctx.tool("code_context", pr=pr)
    history = ctx.tool("code_history", pr=pr, before=ctx.at)
    for earlier in history:
        names = ", ".join(symbol.split(":", 1)[1] for symbol in earlier["symbols"])
        ctx.finding("code_history", earlier["pr"], f"{earlier['pr']} ({earlier['title']}) changed {names} on {earlier['merged_at'][:10]}. {pr} runs through that code, so the two changes have to be read together.", [f"PR:{earlier['pr']}", f"PR:{pr}", *[f"Symbol:{symbol}" for symbol in earlier["symbols"]]])
    governing = read(
        ctx.graph,
        "MATCH (:PR {id: $pr})-[:CHANGES]->(s:Service)<-[:GOVERNS]-(d:Decision {status: 'accepted'}) RETURN d.id AS decision, d.title AS title, d.risk AS risk ORDER BY decision",
        pr=pr,
    )
    paths = sorted({file.split(":", 1)[1] for row in changed for file in [row["file"], *row["used_in"], *row["tests"]]} | {row["path"] for row in around})
    title, written_by, attempts = write_fix(repo, tenant_of(ctx.graph), pr, _brief(ctx, repo, [commit, *filter(None, (_commit_of(repo, row["pr"]) for row in history))], governing, paths))
    ctx.step("write_fix", {"pr": pr, "written_by": written_by}, attempts, [f"File:{repo.name}:{path}" for path in paths])
    if title is None:
        git(repo, "checkout", "-q", "main")
        return None
    respected = [row["decision"] for row in governing]
    summary = f"Keeps {', '.join(respected)} in force." if respected else "No governing decisions on this service."
    if relanded:
        summary = f"Re-applies {pr} on top of the rollback, then fixes it. " + summary
    id = _record(ctx, "fix", repo, branch, title, summary, "")
    write(
        ctx.graph,
        "MATCH (r:Remediation {id: $id}) SET r.written_by = $by WITH r UNWIND $decisions AS decision MATCH (d:Decision {id: decision}) MERGE (r)-[:RESPECTS]->(d)",
        id=id, by=written_by, decisions=respected,
    )
    return id


FIX_INSTRUCTIONS = (
    "You fix a production incident in a small Python repository. Keep what the offending change set out to do and keep every listed decision in force: "
    "make the code around it cope instead of undoing it. Fix the mechanism, not the one input: no special case keyed on an id, "
    "and no size threshold that an attacker or a larger customer could step around. "
    "Do not edit loadcheck.py or any existing test; you may add one new test file under tests/. "
    "Reply with the commit subject (under 70 characters) on the first line. Then, for every file you change, a line '--- <path>' "
    "followed by the complete new content of that file in a ``` fenced block. Nothing else."
)
REPLY_FILE = re.compile(r"^--- (\S+)[ \t]*\n```[a-z]*\n(.*?)\n```", re.S | re.M)
MODEL_ATTEMPTS = 2
PREPARED = "prepared patch"


def write_fix(repo: Path, tenant: str, pr: str, brief: str) -> tuple[str | None, str, list[dict]]:
    """The model writes the fix and the repository's checks judge it; a fix that fails them is thrown away for the prepared patch."""
    attempts = []
    messages = [{"role": "system", "content": FIX_INSTRUCTIONS}, {"role": "user", "content": brief}]
    for _ in range(MODEL_ATTEMPTS):
        try:
            reply = model.chat(messages)
        except model.ModelUnavailable as failure:
            attempts.append({"written_by": model.name() or "model", "outcome": f"no reply: {failure}"[:200]})
            break
        content = (reply.get("content") or "").strip()
        title, files = content.partition("\n")[0].strip("# `\"")[:70], {path: text + "\n" for path, text in REPLY_FILE.findall(content)}
        problem = _apply(repo, files)
        checks = None if problem else run_checks(repo)
        problem = problem or _failure(checks)
        attempts.append({"written_by": reply.get("model", model.name()), "title": title, "outcome": problem or "tests and load check pass"})
        if not problem:
            git(repo, "add", "--", *files)
            git(repo, "commit", "-q", "-m", title)
            return title, attempts[-1]["written_by"], attempts
        git(repo, "reset", "-q", "--hard")
        git(repo, "clean", "-fdq")
        messages += [{"role": "assistant", "content": reply["content"]}, {"role": "user", "content": f"That was rejected: {problem}\nReply again in the same format."}]
    patch = world_of(tenant) / "code" / repo.name / "fixes" / f"{pr}.patch"
    if not patch.exists():
        return None, PREPARED, attempts
    git(repo, "am", str(patch))
    title = git(repo, "log", "-1", "--format=%s").stdout.strip()
    return title, PREPARED, [*attempts, {"written_by": PREPARED, "title": title, "outcome": "applied"}]


def _apply(repo: Path, files: dict[str, str]) -> str | None:
    existing = set(git(repo, "ls-files").stdout.split())
    for path, content in files.items():
        target = (repo / path).resolve()
        if not target.is_relative_to(repo.resolve()) or path == "loadcheck.py" or (path.startswith("tests/") and path in existing):
            return f"{path} may not be edited"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return None if files else "no files were changed"


def _failure(checks: dict) -> str | None:
    if checks["tests_passed"] and checks["load_passed"]:
        return None
    return f"unit tests: {checks['tests_output']}; load check: {checks['load_output']}"[:600]


def _brief(ctx: Context, repo: Path, commits: list[str], governing: list[dict], paths: list[str]) -> str:
    checks = run_checks(repo)
    decisions = "\n".join(f"- {row['decision']}: {row['title']}. Known risk: {row['risk']}" for row in governing) or "- none"
    files = "\n\n".join(f"### {path}\n{(repo / path).read_text()}" for path in paths if (repo / path).exists())
    return (
        f"Incident: {ctx.symptom} on {ctx.service}.\n\nThe change that caused it, then earlier changes to the code it runs through:\n"
        + "\n".join(git(repo, "show", "--format=%s%n%b", commit).stdout for commit in commits)
        + "\n"
        f"Decisions in force that the fix must keep:\n{decisions}\n\n"
        f"Checks right now: unit tests {checks['tests_output']}; load check: {checks['load_output']}\n\n"
        f"The files the graph says this change reaches:\n\n{files}"
    )


def merge(graph: Graph, remediation: str, user: str) -> dict:
    """Human-approved merge: lands the branch, re-runs the checks on main, and resolves the incident if they pass."""
    item = read(
        graph,
        """
        MATCH (v:Investigation)-[:PROPOSED]->(r:Remediation {id: $id})
        RETURN r.kind AS kind, r.branch AS branch, r.repo AS repo, r.title AS title, r.status AS status,
               v.id AS investigation, v.incident AS incident
        """,
        id=remediation,
    )
    if not item or item[0]["status"] != "proposed":
        raise ValueError(f"{remediation} is not awaiting approval")
    item = item[0]
    repo = repo_path(tenant_of(graph), item["repo"])
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "--no-ff", "-m", f"Merge {item['branch']}", item["branch"])
    checks = run_checks(repo)
    pr = _ingest_merged_pr(graph, item, user, checks)
    code.index(graph, repo)
    code.link(graph, repo, pr, "main")
    merged_at = now()
    write(
        graph,
        "MATCH (r:Remediation {id: $id}) SET r.status = 'merged', r.merged_by = $user, r.merged_at = $at, r.pr = $pr",
        id=remediation, user=user, at=merged_at, pr=pr,
    )
    if checks["load_passed"]:
        write(
            graph,
            "MATCH (i:Incident {id: $id}) WHERE i.status = 'open' SET i.status = 'resolved', i.resolved_at = $at",
            id=item["incident"], at=merged_at,
        )
    if item["kind"] == "rollback":
        _rebase_open_fix(graph, item["investigation"])
    elif checks["load_passed"]:
        write(
            graph,
            "MATCH (:Investigation {id: $id})-[:PROPOSED]->(r:Remediation {kind: 'rollback', status: 'proposed'}) SET r.status = 'withdrawn'",
            id=item["investigation"],
        )
    return {"pr": pr, **checks}


def run_checks(repo: Path) -> dict:
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=repo, capture_output=True, text=True)
    load = subprocess.run([sys.executable, "loadcheck.py"], cwd=repo, capture_output=True, text=True)
    return {
        "tests_passed": tests.returncode == 0,
        "load_passed": load.returncode == 0,
        "tests_output": tests.stderr.strip().splitlines()[-1] if tests.stderr.strip() else "",
        "load_output": load.stdout.strip(),
    }


def _repo_of(graph: Graph, pr: str) -> Path | None:
    found = read(graph, "MATCH (p:PR {id: $pr}) RETURN p.repo AS repo", pr=pr)
    path = found and repo_path(tenant_of(graph), found[0]["repo"])
    return path if path and path.exists() else None


def _commit_of(repo: Path, pr: str) -> str | None:
    commits = git(repo, "log", "main", "--topo-order", "--format=%H", "-F", f"--grep=({pr})").stdout.split()
    return commits[-1] if commits else None


def _reland_if_reverted(repo: Path, commit: str) -> bool:
    revert = git(repo, "log", "--format=%H", "-F", f"--grep=This reverts commit {commit}").stdout.strip()
    if not revert:
        return False
    git(repo, "revert", "--no-edit", revert.splitlines()[0])
    return True


def _record(ctx: Context, kind: str, repo: Path, branch: str, title: str, summary: str, warning: str) -> str:
    checks = run_checks(repo)
    ctx.step("run_checks", {"branch": branch}, [{"check": "unit tests", "passed": checks["tests_passed"], "output": checks["tests_output"]}, {"check": "load check", "passed": checks["load_passed"], "output": checks["load_output"]}], [])
    diff = git(repo, "diff", "main..." + branch).stdout
    git(repo, "checkout", "-q", "main")
    id = f"{ctx.investigation}:R:{kind}"
    write(
        ctx.graph,
        """
        MATCH (v:Investigation {id: $inv})
        MERGE (r:Remediation {id: $id})
        SET r.kind = $kind, r.repo = $repo, r.branch = $branch, r.title = $title, r.summary = $summary,
            r.warning = $warning, r.diff = $diff, r.status = 'proposed', r.proposed_at = $at, r += $checks
        MERGE (v)-[:PROPOSED]->(r)
        WITH r MATCH (f:Finding {id: $finding}) MERGE (r)-[:JUSTIFIED_BY]->(f)
        """,
        inv=ctx.investigation, id=id, kind=kind, repo=repo.name, branch=branch, title=title, summary=summary,
        warning=warning, diff=diff, at=now(), checks=checks, finding=f"{ctx.investigation}:F:root_cause:root",
    )
    return id


def _ingest_merged_pr(graph: Graph, item: dict, user: str, checks: dict) -> str:
    """The merged change enters the graph through the git source, like any other pull request."""
    number = read(graph, "MATCH (p:PR) RETURN max(toInteger(substring(p.id, 3))) + 1 AS next")[0]["next"]
    pr = f"PR-{number}"
    at = now()
    record = ingest.Record(pr, f"ripple://{item['repo']}/{item['branch']}", json.dumps({**item, "merged_by": user, "at": at}))
    node = record.node("PR", pr, title=item["title"], merged_at=at, repo=item["repo"], files=[], risk=[], merged_by=user, body=f"Fixes {item['incident']}.")
    record.edge(node, "CHANGES", ("Service", item["repo"]))
    record.edge(node, "FIXES", ("Incident", item["incident"]))
    deploy = record.node("Deploy", f"D-{number}", at=at, env="production", status="success" if checks["load_passed"] else "degraded")
    record.edge(deploy, "SHIPPED", node)
    record.edge(deploy, "DEPLOYED_TO", ("Service", item["repo"]))
    write(graph, "MERGE (s:Source {id: 'git'})")
    ingest.store(graph, "git", record)
    return pr


def _rebase_open_fix(graph: Graph, investigation: str) -> None:
    """A fix branch cut before the rollback landed no longer merges cleanly; rebuild it on the new main."""
    still_open = read(graph, "MATCH (:Investigation {id: $id})-[:PROPOSED]->(r:Remediation {kind: 'fix', status: 'proposed'}) RETURN r.id AS id", id=investigation)
    if not still_open:
        return
    ctx = Context.load(graph, investigation, "fixer")
    propose_fix(ctx, ctx.root()["id"])
