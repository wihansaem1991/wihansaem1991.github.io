#!/usr/bin/env python3
"""Bring contributions.yaml up to date with GitHub, then rebuild the pages.

  python3 sync.py          # needs the gh CLI logged in as the portfolio owner

For every entry, the pull request is looked up and `status` / `decided` are set
to merged (merge date) or approved (date of the latest approving review).
Pull requests by the owner that are approved or merged but have no entry yet
are listed, since their descriptions have to be written by hand.
Edits are made in place so the comments and layout of the YAML file stay.
Evidence links (the PR, each approving review, the merge commit) go to
github.json, which build.py reads.
"""
import json
import os
import re
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "contributions.yaml")
EVIDENCE = os.path.join(HERE, "github.json")


def gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def pr_state(repo, number):
    """('merged'|'approved'|'open'|'closed', 'YYYY-MM-DD' or None)."""
    d = gh("pr", "view", str(number), "-R", repo,
           "--json", "state,mergedAt,reviewDecision,reviews,title")
    if d.get("mergedAt"):
        return "merged", d["mergedAt"][:10], d["title"]
    approvals = [r["submittedAt"][:10] for r in d.get("reviews") or [] if r.get("state") == "APPROVED"]
    if d.get("reviewDecision") == "APPROVED" and approvals:
        return "approved", max(approvals), d["title"]
    return d["state"].lower(), None, d["title"]


def evidence(repo, number):
    pr = gh("api", f"repos/{repo}/pulls/{number}")
    reviews = gh("api", f"repos/{repo}/pulls/{number}/reviews")
    approvals = {}
    for r in reviews:
        if r.get("state") == "APPROVED":
            approvals[r["user"]["login"]] = {"by": r["user"]["login"], "url": r["html_url"],
                                             "date": (r.get("submitted_at") or "")[:10]}
    merge = None
    if pr.get("merged_at") and pr.get("merge_commit_sha"):
        sha = pr["merge_commit_sha"]
        merge = {"sha": sha, "url": f"https://github.com/{repo}/commit/{sha}"}
    return {"url": pr["html_url"], "approvals": list(approvals.values()), "merge": merge}


def set_field(block, key, value):
    pattern = re.compile(rf"^(    {key}: ).*$", re.M)
    if pattern.search(block):
        return pattern.sub(lambda m: m.group(1) + value, block, count=1)
    return block


def main():
    text = open(DATA, encoding="utf-8").read()
    data = yaml.safe_load(text)
    owner = data["owner"]["github"]
    known = {(e["repo"], int(e["pr"])) for e in data.get("entries") or []}

    changed = []
    starts = [m.start() for m in re.finditer(r"^  - project: ", text, re.M)] + [len(text)]
    pieces = [text[:starts[0]]]
    for a, b in zip(starts, starts[1:]):
        block = text[a:b]
        e = yaml.safe_load("\n".join(l[2:] if l.startswith("  ") else l for l in block.splitlines()))[0]
        status, date, _ = pr_state(e["repo"], e["pr"])
        if status in ("merged", "approved") and (status != e.get("status") or date != str(e.get("decided"))):
            block = set_field(set_field(block, "status", status), "decided", date)
            changed.append(f'{e["repo"]}#{e["pr"]}: {e.get("status")} {e.get("decided")} -> {status} {date}')
        pieces.append(block)
    if changed:
        open(DATA, "w", encoding="utf-8").write("".join(pieces))

    links = {f"{e['repo']}#{e['pr']}": evidence(e["repo"], e["pr"]) for e in data.get("entries") or []}
    old_links = json.load(open(EVIDENCE, encoding="utf-8")) if os.path.exists(EVIDENCE) else None
    if links != old_links:
        with open(EVIDENCE, "w", encoding="utf-8") as f:
            json.dump(links, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
        changed.append("github.json evidence links")

    missing = []
    for p in gh("search", "prs", "--author", owner, "--limit", "100", "--json", "repository,number"):
        key = (p["repository"]["nameWithOwner"], int(p["number"]))
        if key in known:
            continue
        status, date, title = pr_state(*key)
        if status in ("merged", "approved"):
            missing.append(f"{key[0]}#{key[1]} {status} {date} {title}")

    for line in changed:
        print("updated", line)
    for line in missing:
        print("missing", line)
    if not changed and not missing:
        print("no change")
    if changed:
        subprocess.run([sys.executable, os.path.join(HERE, "build.py")], check=True)


if __name__ == "__main__":
    main()
