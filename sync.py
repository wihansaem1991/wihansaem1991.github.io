#!/usr/bin/env python3
"""Bring contributions.yaml and github.json up to date with GitHub, then rebuild the pages.

  python3 sync.py          # needs the gh CLI logged in (locally) or GH_TOKEN (in Actions)

For every pull request entry:
- `status` / `decided` in contributions.yaml are set to merged (merge date) or approved (date of
  the latest approving review);
- github.json gets the evidence links (the PR, each approving review, the merge commit) and the
  live state shown on the page: stage, CI summary, first and last maintainer response.
Entries with a `gerrit:` link are changes on a Gerrit server instead of GitHub pull requests; they
are read from that server's public REST API (Code-Review +2 is approved, +1 approved and awaiting
another review, a negative vote asks for changes).
Pull requests by the owner that are approved or merged but have no entry yet are listed, since
their briefings have to be written by hand.

Vulnerability reports: when `.private/advisories.json` exists (it is git-ignored and only on the
owner's machine), the state of each private advisory is read and copied to the matching
`vulnerabilities` entry by label, so the page shows the stage without naming the project.
Edits are made in place so the comments and layout of the YAML file stay.
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "contributions.yaml")
EVIDENCE = os.path.join(HERE, "github.json")
PRIVATE = os.path.join(HERE, ".private", "advisories.json")
# `gh pr view` drops the "[bot]" suffix from GitHub App logins, so name the common service bots
BOT = re.compile(r"bot\b|\[bot\]|^app/|^(codecov|coveralls|github-actions|netlify|vercel|sonarcloud|mergify|renovate|dependabot|gitguardian|cla-assistant|claassistant)$", re.I)
# GitHub advisory states -> stages shown on the page
ADVISORY_STAGE = {"triage": "triage", "draft": "accepted", "published": "published", "closed": "closed"}


def gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


_GERRIT = {}


def gerrit(e):
    """The change behind a `gerrit:` link (https://host/c/project/+/123), from the public REST API."""
    if e["gerrit"] in _GERRIT:
        return _GERRIT[e["gerrit"]]
    u = urllib.parse.urlsplit(e["gerrit"])
    url = (f"{u.scheme}://{u.netloc}/changes/{int(e['pr'])}"
           "?o=DETAILED_LABELS&o=DETAILED_ACCOUNTS&o=MESSAGES&o=ALL_REVISIONS")
    with urllib.request.urlopen(url, timeout=30) as r:
        body = r.read().decode("utf-8")
    _GERRIT[e["gerrit"]] = json.loads(body.split("\n", 1)[1])  # the reply starts with )]}'
    return _GERRIT[e["gerrit"]]


def gerrit_votes(c):
    """[(value, name, date)] of the Code-Review votes on the current patch set. A vote copied to a
    new patch set carries the copy time, so the date is taken from the voter's last message that
    cast a Code-Review vote."""
    cast = {}
    for m in c.get("messages") or []:
        who = (m.get("author") or {}).get("_account_id")
        if who and re.search(r"Code-Review[+-]\d", m.get("message") or ""):
            cast[who] = m["date"]
    return [(v["value"], v.get("name") or v.get("username") or "", cast.get(v.get("_account_id"), v.get("date") or ""))
            for v in (c.get("labels") or {}).get("Code-Review", {}).get("all") or [] if v.get("value")]


def gerrit_state(e):
    c = gerrit(e)
    if c["status"] == "MERGED":
        return "merged", (c.get("submitted") or c["updated"])[:10], c["subject"]
    plus = [d for v, _, d in gerrit_votes(c) if v >= 2]
    if c["status"] == "NEW" and plus and min(v for v, _, _ in gerrit_votes(c)) > 0:
        return "approved", max(plus)[:10], c["subject"]
    return ("closed" if c["status"] == "ABANDONED" else "open"), None, c["subject"]


def gerrit_evidence(e):
    c = gerrit(e)
    approvals = [{"by": name, "url": e["gerrit"], "date": d[:10]} for v, name, d in gerrit_votes(c) if v >= 2]
    return {"url": e["gerrit"], "approvals": approvals, "merge": None}


def gerrit_live(e):
    c = gerrit(e)
    me = (c.get("owner") or {}).get("_account_id")
    replies = sorted(m["date"] for m in c.get("messages") or []
                     if (m.get("author") or {}).get("_account_id") not in (None, me)
                     and not BOT.search((m.get("author") or {}).get("name") or ""))
    votes = gerrit_votes(c)
    uploaded = max(r["created"] for r in c["revisions"].values())
    if c["status"] == "MERGED":
        stage = "merged"
    elif c["status"] == "ABANDONED":
        stage = "closed"
    elif votes and min(v for v, _, _ in votes) < 0:
        last_no = max(d for v, _, d in votes if v < 0)
        stage = "rereview" if uploaded > last_no else "changes"
    elif votes and max(v for v, _, _ in votes) >= 2:
        stage = "approved"
    elif votes:
        stage = "approved_pending"
    else:
        stage = "review"
    end = c.get("submitted") if stage == "merged" else (c["updated"] if stage == "closed" else None)
    return {
        "stage": stage,
        "draft": bool(c.get("work_in_progress")),
        "opened": c["created"][:10],
        "ended": end[:10] if end else None,
        "first_response": replies[0][:10] if replies else None,
        "last_response": replies[-1][:10] if replies else None,
        "checks": {"pass": 0, "fail": 0, "pending": 0},
        "ci_waiting": 0,
    }


def pr_state(repo, number):
    """('merged'|'approved'|'open'|'closed', 'YYYY-MM-DD' or None, title)."""
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


def checks(rollup):
    counts = {"pass": 0, "fail": 0, "pending": 0}
    for c in rollup or []:
        result = (c.get("conclusion") or c.get("state") or "").upper()
        if result in ("SUCCESS", "NEUTRAL"):
            counts["pass"] += 1
        elif result in ("FAILURE", "TIMED_OUT", "CANCELLED", "ERROR", "STARTUP_FAILURE"):
            counts["fail"] += 1
        elif result != "SKIPPED":
            counts["pending"] += 1
    return counts


def live(repo, number, owner):
    """Where the pull request stands now, as shown in the challenge table."""
    d = gh("pr", "view", str(number), "-R", repo, "--json",
           "state,isDraft,createdAt,mergedAt,closedAt,reviewDecision,reviews,comments,headRefOid,"
           "statusCheckRollup")
    def who(x):
        return (x.get("author") or {}).get("login") or ""
    activity = [(x.get("submittedAt") or x.get("createdAt"), who(x))
                for x in (d.get("reviews") or []) + (d.get("comments") or [])]
    maintainers = sorted(t for t, by in activity if t and by and by != owner and not BOT.search(by))
    own = sorted(t for t, by in activity if t and by == owner)
    changes = sorted(r["submittedAt"] for r in d.get("reviews") or []
                     if r.get("state") == "CHANGES_REQUESTED" and r.get("submittedAt"))
    # each reviewer's latest verdict; an approval counts until that reviewer changes it
    verdict = {}
    for r in sorted(d.get("reviews") or [], key=lambda r: r.get("submittedAt") or ""):
        if r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED") and who(r) != owner:
            verdict[who(r)] = r["state"]
    runs = gh("api", f"repos/{repo}/actions/runs?head_sha={d['headRefOid']}&per_page=100")
    waiting = sum(1 for r in runs.get("workflow_runs") or [] if r.get("conclusion") == "action_required")
    if d.get("mergedAt"):
        stage = "merged"
    elif d["state"] == "CLOSED":
        stage = "closed"
    elif d.get("reviewDecision") == "APPROVED":
        stage = "approved"
    elif d.get("reviewDecision") == "CHANGES_REQUESTED":
        stage = "rereview" if own and changes and own[-1] > changes[-1] else "changes"
    elif "APPROVED" in verdict.values():
        stage = "approved_pending"  # approved, but the repository requires more approving reviews
    elif waiting:
        stage = "ci_approval"
    else:
        stage = "review"
    end = d.get("mergedAt") or d.get("closedAt")
    return {
        "stage": stage,
        "draft": bool(d.get("isDraft")),
        "opened": d["createdAt"][:10],
        "ended": end[:10] if end else None,
        "first_response": maintainers[0][:10] if maintainers else None,
        "last_response": maintainers[-1][:10] if maintainers else None,
        "checks": checks(d.get("statusCheckRollup")),
        "ci_waiting": waiting,
    }


def set_field(block, key, value, indent="    "):
    pattern = re.compile(rf"^({indent}{key}: ).*$", re.M)
    if pattern.search(block):
        return pattern.sub(lambda m: m.group(1) + value, block, count=1)
    return block


def blocks(text, section, marker):
    """Split the list under `section:` into per-item blocks that start with `marker`."""
    start = re.search(rf"^{section}:\s*$", text, re.M)
    if not start:
        return None
    end = re.search(r"^\S", text[start.end():], re.M)
    stop = start.end() + end.start() if end else len(text)
    body = text[start.end():stop]
    starts = [m.start() for m in re.finditer(rf"^  - {marker}: ", body, re.M)] + [len(body)]
    if len(starts) == 1:
        return None
    head = text[:start.end()] + body[:starts[0]]
    items = [body[a:b] for a, b in zip(starts, starts[1:])]
    return head, items, text[stop:]


def parse(block):
    return yaml.safe_load("\n".join(l[2:] if l.startswith("  ") else l for l in block.splitlines()))[0]


def main():
    text = open(DATA, encoding="utf-8").read()
    data = yaml.safe_load(text)
    owner = data["owner"]["github"]
    known = {(e["repo"], int(e["pr"])) for e in data.get("entries") or []}

    changed = []
    split = blocks(text, "entries", "project")
    if split:
        head, items, tail = split
        for i, block in enumerate(items):
            e = parse(block)
            status, date, _ = gerrit_state(e) if e.get("gerrit") else pr_state(e["repo"], e["pr"])
            if status in ("merged", "approved") and (status != e.get("status") or date != str(e.get("decided"))):
                items[i] = set_field(set_field(block, "status", status), "decided", date)
                changed.append(f'{e["repo"]}#{e["pr"]}: {e.get("status")} {e.get("decided")} -> {status} {date}')
        text = head + "".join(items) + tail

    if os.path.exists(PRIVATE):
        private = {a["label"]: a for a in json.load(open(PRIVATE, encoding="utf-8"))}
        split = blocks(text, "vulnerabilities", "label")
        if split:
            head, items, tail = split
            for i, block in enumerate(items):
                v = parse(block)
                a = private.get(v["label"])
                if not a:
                    continue
                adv = gh("api", f"repos/{a['repo']}/security-advisories/{a['ghsa']}")
                stage = ADVISORY_STAGE.get(adv.get("state"), adv.get("state"))
                if stage != v.get("status"):
                    items[i] = set_field(block, "status", stage)
                    changed.append(f'{v["label"]}: {v.get("status")} -> {stage}')
                if adv.get("cve_id") and adv["cve_id"] != v.get("cve"):
                    items[i] = set_field(items[i], "cve", adv["cve_id"])
                    changed.append(f'{v["label"]}: CVE {adv["cve_id"]}')
            text = head + "".join(items) + tail

    if changed:
        open(DATA, "w", encoding="utf-8").write(text)

    links = {}
    for e in data.get("entries") or []:
        key = f"{e['repo']}#{e['pr']}"
        if e.get("gerrit"):
            links[key] = {**gerrit_evidence(e), "live": gerrit_live(e)}
        else:
            links[key] = {**evidence(e["repo"], e["pr"]), "live": live(e["repo"], e["pr"], owner)}
    old_links = json.load(open(EVIDENCE, encoding="utf-8")) if os.path.exists(EVIDENCE) else None
    if links != old_links:
        with open(EVIDENCE, "w", encoding="utf-8") as f:
            json.dump(links, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
        changed.append("github.json")

    missing = []
    for p in gh("search", "prs", "--author", owner, "--limit", "100", "--json", "repository,number"):
        key = (p["repository"]["nameWithOwner"], int(p["number"]))
        # pull requests to the owner's own repositories (this site, for one) are not contributions
        if key in known or key[0].split("/")[0] == owner:
            continue
        status, date, title = pr_state(*key)
        missing.append(f"{key[0]}#{key[1]} {status} {date or ''} {title}")

    for line in changed:
        print("updated", line)
    for line in missing:
        print("missing", line)
    if not changed and not missing:
        print("no change")
    subprocess.run([sys.executable, os.path.join(HERE, "build.py")], check=True)


if __name__ == "__main__":
    main()
