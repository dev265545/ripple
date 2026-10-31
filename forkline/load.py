"""Loads Forkline into a running Ripple through the same endpoints the Connect screen uses.

Run: uv run python forkline/load.py [--repo owner/name]   (a public repository to read once; connect it in the app to keep watching it)
"""

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8642/api"
TENANT = "forkline"
DATA = Path(__file__).parent / "data"
EXPORTS = {"hr": "people.csv", "catalog": "catalog.yaml", "product_map": "product_map.yaml", "crm": "customers.csv", "oncall": "oncall.json", "projects": "projects.json", "calendar": "calendar.ics", "vendor_status": "vendor_status.json"}


def post(path: str, body: dict | bytes) -> dict:
    data, kind = (body, "application/octet-stream") if isinstance(body, bytes) else (json.dumps(body).encode(), "application/json")
    try:
        # Reading mail with a model on a free tier waits out rate limits, so one request can run for many minutes.
        with urllib.request.urlopen(urllib.request.Request(f"{API}{path}", data=data, headers={"Content-Type": kind}), timeout=7200) as response:
            return json.load(response)
    except urllib.error.HTTPError as problem:
        return {"refused": problem.code, "detail": problem.read().decode()[:300]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo")
    args = parser.parse_args()
    print("company", post("/tenants", {"name": TENANT}))
    for source, file in EXPORTS.items():
        print(source, post(f"/{TENANT}/sources/{source}/file", {"text": (DATA / file).read_text()}))
    if args.repo:
        print("git", post(f"/{TENANT}/sources/git/pull", {"fields": {"repo": args.repo, "limit": "20"}}))
        urllib.request.urlopen(urllib.request.Request(f"{API}/{TENANT}/github", method="DELETE"))
    for file in sorted((DATA / "documents").glob("*.md")):
        added = post(f"/{TENANT}/documents", {"name": file.name, "text": file.read_text()})
        print(file.name, {key: len(added[key]) for key in ("linked", "things", "links", "promises")} if "links" in added else added, flush=True)
    for source, name in (("slack", "slack-export.zip"), ("gmail", "mail.mbox")):
        print(source, post(f"/{TENANT}/inbox/{source}/file?{urllib.parse.urlencode({'name': name})}", (DATA / name).read_bytes()), flush=True)


if __name__ == "__main__":
    main()
