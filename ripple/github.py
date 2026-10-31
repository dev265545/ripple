import json
import re
import urllib.error
import urllib.request

MAX_CHANGES = 30
TIMEOUT_SECONDS = 30
INCIDENT_LABEL = "incident"
API = "https://api.github.com/repos"
REPO = re.compile(r"(?:github\.com[/:])?([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def split(repo: str) -> tuple[str, str]:
    found = REPO.search(repo.strip())
    if not found:
        raise ValueError("Give a repository as owner/name or as its github.com link.")
    return found.groups()


def changes(repo: str, token: str = "", limit: int = 10, known: frozenset = frozenset()) -> list[dict]:
    """A repository's newest merged pull requests in the Git host export's shape, minus the known ones; commits stand in when it has none."""
    owner, name = split(repo)
    limit = min(MAX_CHANGES, max(1, limit))
    api = f"{API}/{owner}/{name}"
    # ponytail: only the newest 100 closed pull requests are looked at, and at most 100 files of each; page when a repo needs more
    merged = [pull for pull in _get(f"{api}/pulls?state=closed&sort=updated&direction=desc&per_page=100", token) if pull.get("merged_at")][:limit]
    if merged:
        return [
            {
                "number": pull["number"], "title": pull["title"], "user": {"login": _login(pull["user"])}, "merged_at": pull["merged_at"],
                "base": {"repo": {"name": name}}, "body": pull.get("body") or "", "html_url": pull["html_url"],
                "files": [file["filename"] for file in _get(f"{api}/pulls/{pull['number']}/files?per_page=100", token)],
                "reviews": [{"user": {"login": login}} for login in dict.fromkeys(_login(review["user"]) for review in _get(f"{api}/pulls/{pull['number']}/reviews", token))],
            }
            for pull in merged
            if pull["number"] not in known
        ]
    return [_commit(name, _get(f"{api}/commits/{commit['sha']}", token)) for commit in _get(f"{api}/commits?per_page={limit}", token) if commit["sha"][:7] not in known]


def issues(repo: str, token: str, since: str) -> list[dict]:
    """Open issues carrying the incident label that were created after the given moment."""
    owner, name = split(repo)
    found = _get(f"{API}/{owner}/{name}/issues?labels={INCIDENT_LABEL}&state=open&since={since}&per_page=30", token)
    return [issue for issue in found if "pull_request" not in issue and issue["created_at"] > since]


def comment(issue: str, token: str, body: str) -> str:
    repo, _, number = issue.partition("#")
    return _get(f"{API}/{repo}/issues/{number}/comments", token, {"body": body})["html_url"]


REVERT = "mutation($id: ID!, $title: String, $body: String) { revertPullRequest(input: {pullRequestId: $id, title: $title, body: $body}) { revertPullRequest { url } } }"


def revert(pull: str, token: str, title: str, body: str) -> str:
    """Opens the pull request that undoes a merged one, the way GitHub's own Revert button does, and returns its link."""
    repo, _, number = pull.partition("#")
    merged = _get(f"{API}/{repo}/pulls/{number}", token)
    reply = _get("https://api.github.com/graphql", token, {"query": REVERT, "variables": {"id": merged["node_id"], "title": title, "body": body}})
    if reply.get("errors"):
        raise ValueError(f"GitHub did not open a revert of {pull}: {reply['errors'][0]['message']}")
    return reply["data"]["revertPullRequest"]["revertPullRequest"]["url"]


def _commit(repo: str, commit: dict) -> dict:
    title, _, body = commit["commit"]["message"].partition("\n")
    author = _login(commit.get("author")) if commit.get("author") else commit["commit"]["author"]["name"]
    return {
        "number": commit["sha"][:7], "title": title, "user": {"login": author}, "merged_at": commit["commit"]["author"]["date"],
        "base": {"repo": {"name": repo}}, "body": body.strip(), "html_url": commit["html_url"],
        "files": [file["filename"] for file in commit.get("files", [])], "reviews": [],
    }


def _login(user: dict | None) -> str:
    return (user or {}).get("login") or "ghost"


def _get(url: str, token: str, send: dict | None = None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ripple"} | ({"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers, data=json.dumps(send).encode() if send else None), timeout=TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as problem:
        reasons = {401: "the token was refused", 403: "the hourly limit is used up or the token is not allowed to do this; a token raises the limit", 404: "no such repository, or it is private and needs a token"}
        raise ValueError(f"GitHub did not return {url.split('?')[0].removeprefix('https://api.github.com/')}: {reasons.get(problem.code, problem.reason)}.") from problem
    except (OSError, ValueError) as problem:
        raise ValueError(f"GitHub could not be reached: {problem}") from problem
