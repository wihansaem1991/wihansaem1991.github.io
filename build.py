#!/usr/bin/env python3
"""Render the contribution and CVE challenge board from contributions.yaml and github.json.

  python3 build.py      # writes index.html (en) and ko/index.html (ko)

Every pull request entry is listed with the stage sync.py recorded in github.json. In the browser,
the page asks the GitHub search API for merged, closed and approved pull requests on every load,
so those stages are current on refresh. Private vulnerability reports show only their stage until
`public: true`.
"""
import datetime as dt
import html
import json
import os
import re

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
KST = dt.timezone(dt.timedelta(hours=9))
DONE = ("approved", "merged")
# order of the challenge table: finished work first, then what waits on maintainers
STAGE_ORDER = ["merged", "approved", "approved_pending", "rereview", "changes", "review", "ci_approval", "closed"]
# tabs: each stage belongs to one group
GROUP = {"merged": "done", "approved": "done", "approved_pending": "review", "rereview": "review", "changes": "review", "review": "review",
         "open": "review", "ci_approval": "ci", "closed": "closed"}
TABS = ["all", "done", "review", "ci", "closed", "cve", "repos"]
# fixed colour order for the type-mix bar (CSS vars --c-<type> carry the hue, with a dark variant)
TYPE_ORDER = ["hardening", "bugfix", "test", "cleanup", "docs", "feature"]

UI = {
    "en": {
        "html_lang": "en", "title_suffix": "Open-source security contributions & CVE challenge",
        "switch": '<a href="ko/" hreflang="ko">한국어</a>',
        "tabs": {"all": "All", "done": "Approved / merged", "review": "In review", "ci": "Awaiting CI approval",
                 "closed": "Closed", "cve": "CVE challenge", "repos": "Repositories"},
        "repos_hint": "Repositories I am auditing now: what each project is and what I look at there.",
        "focus": "Looking at", "prs": "{n} pull requests", "no_prs": "No pull request yet",
        "wins_title": "Contributions that landed",
        "wins_intro": "{n} contributions are in {projects} open-source projects.",
        "wins_count": "{n}",
        "kpi_landed": "Landed", "kpi_projects": "Projects",
        "chart_by_project": "Landed by project", "chart_by_type": "By type",
        "repos_title": "Repositories I audit",
        "vulns_title": "Vulnerability reports",
        "vulns_hint": "Reported through each project's private channel; named once the project publishes a fix.",
        "summary": "{prs} pull requests and {vulns} vulnerability reports · {replied} with a maintainer reply · {cves} CVEs",
        "vuln": "Vulnerability report",
        "private_body": "Reported through the project's private channel. Details follow once the project publishes a fix.",
        "hint": "Open an entry to read its briefing.",
        "cve_cols": ["Report", "Submitted", "Channel", "Stage", "CVE", "Details"],
        "days": "{n} days", "first": "first reply {d}", "no_reply": "no reply yet", "ci": "CI",
        "empty_tab": "Nothing here right now.",
        "types": {"hardening": "Hardening", "bugfix": "Bug fix", "test": "Test coverage",
                  "docs": "Documentation", "cleanup": "Cleanup", "feature": "Feature",
                  "vulnerability": "Vulnerability"},
        "stages": {"merged": "Merged", "approved": "Approved", "approved_pending": "Approved, awaiting another review",
                   "rereview": "Updated, awaiting re-review",
                   "changes": "Changes requested", "review": "Awaiting review",
                   "ci_approval": "Awaiting CI approval", "closed": "Closed", "open": "Open"},
        "vstages": {"triage": "Under triage", "accepted": "Accepted", "fixed": "Fixed",
                    "published": "Published", "closed": "Closed",
                    "public_pr": "Moved to a public pull request"},
        "draft": "draft", "none_yet": "none yet", "private": "Project and details withheld until disclosure",
        "dt": {"cve": "CVE", "defect": "Problem", "background": "Background", "found_by": "How it was found",
               "fix": "Fix", "review": "Review", "evidence": "Evidence"},
        "ev": {"pr": "Pull request", "files": "Changed files", "approved_by": "Approved by", "merge": "Merge commit"},
        "submitted": "submitted", "reviewer": "reviewer", "empty": "Nothing submitted yet.",
        "no_cve": "No vulnerability reports yet.",
        "live": "Stages read from GitHub just now ({t}).",
        "snapshot": "Showing the snapshot of {d}; GitHub could not be reached from this browser.",
        "loading": "Reading current stages from GitHub…",
        "footer": ("Updated {d}. Private vulnerability reports stay unnamed "
                   "until the project discloses them. Development was assisted by Claude Code; every change was "
                   "reproduced and tested, and AI assistance is disclosed in each commit."),
    },
    "ko": {
        "html_lang": "ko", "title_suffix": "오픈소스 보안 기여 · CVE 도전",
        "switch": '<a href="../" hreflang="en">English</a>',
        "tabs": {"all": "전체", "done": "승인·머지", "review": "리뷰 중", "ci": "CI 허가 대기", "closed": "닫힘",
                 "cve": "CVE 도전", "repos": "분석 중인 저장소"},
        "repos_hint": "지금 결함을 찾고 있는 저장소입니다. 프로젝트가 무엇인지, 그 안에서 무엇을 보는지 적었습니다.",
        "focus": "보는 것", "prs": "PR {n}건", "no_prs": "아직 PR 없음",
        "wins_title": "오픈소스에 반영된 기여",
        "wins_intro": "오픈소스 프로젝트 {projects}곳에 기여 {n}건이 들어갔습니다.",
        "wins_count": "{n}건",
        "kpi_landed": "반영된 기여", "kpi_projects": "기여한 프로젝트",
        "chart_by_project": "프로젝트별 반영 기여", "chart_by_type": "종류별 기여",
        "repos_title": "분석 중인 저장소",
        "vulns_title": "취약점 보고",
        "vulns_hint": "각 프로젝트의 비공개 경로로 보고했고, 프로젝트가 수정을 공개하면 이름을 채웁니다.",
        "summary": "제출 PR {prs}건 · 취약점 보고 {vulns}건 · 메인테이너 응답 {replied}건 · CVE {cves}건",
        "vuln": "취약점 보고",
        "private_body": "프로젝트의 비공개 경로로 보고했습니다. 프로젝트가 수정을 공개하면 내용을 채웁니다.",
        "hint": "항목을 누르면 브리핑이 펼쳐집니다.",
        "cve_cols": ["보고", "제출", "경로", "단계", "CVE", "내용"],
        "days": "{n}일째", "first": "첫 응답 {d}", "no_reply": "응답 아직", "ci": "CI",
        "empty_tab": "지금은 해당 항목이 없습니다.",
        "types": {"hardening": "보안 강화", "bugfix": "버그 수정", "test": "시험 보강", "docs": "문서 수정",
                  "cleanup": "코드 정리", "feature": "기능 추가", "vulnerability": "취약점"},
        "stages": {"merged": "머지됨", "approved": "승인", "approved_pending": "승인, 추가 리뷰 대기",
                   "rereview": "수정 반영, 재리뷰 대기",
                   "changes": "수정 요청", "review": "리뷰 대기", "ci_approval": "CI 실행 허가 대기",
                   "closed": "닫힘", "open": "열림"},
        "vstages": {"triage": "분류 중", "accepted": "인정됨", "fixed": "수정됨", "published": "공개됨",
                    "closed": "종결", "public_pr": "공개 PR로 전환"},
        "draft": "초안", "none_yet": "아직 없음", "private": "공개 전까지 프로젝트·내용 비공개",
        "dt": {"cve": "CVE", "defect": "문제", "background": "배경 지식", "found_by": "찾은 방법",
               "fix": "수정", "review": "리뷰", "evidence": "증빙"},
        "ev": {"pr": "PR 원문", "files": "바뀐 코드", "approved_by": "승인한 리뷰어", "merge": "머지 커밋"},
        "submitted": "제출", "reviewer": "리뷰어", "empty": "아직 제출한 PR이 없습니다.",
        "no_cve": "아직 취약점 보고가 없습니다.",
        "live": "GitHub에서 방금 단계를 다시 읽었습니다({t}).",
        "snapshot": "{d} 기준 자료입니다. 이 브라우저에서 GitHub에 연결하지 못했습니다.",
        "loading": "GitHub에서 현재 단계를 읽는 중…",
        "footer": ("{d} 갱신. 비공개 취약점 보고는 프로젝트가 공개하기 "
                   "전까지 이름을 가립니다. Claude Code의 도움을 받아 작업했고, 모든 변경은 직접 재현·시험했으며 "
                   "커밋에 AI 도움을 밝혔습니다."),
    },
}


def pick(v, lang):
    return (v.get(lang) or v.get("en") or "") if isinstance(v, dict) else (v or "")


def text(s):
    """Escape, then turn `code` spans into <code>."""
    s = html.escape(str(s or "").strip())
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", s)


def ext(url, label):
    return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{label} ↗</a>'


def key(e):
    return f'{e["repo"]}#{e["pr"]}'


def pr_url(e):
    """The pull request on GitHub, or the change on Gerrit for entries with a `gerrit:` link."""
    return e.get("gerrit") or f'https://github.com/{e["repo"]}/pull/{e["pr"]}'


def pr_label(e):
    return f'Gerrit {e["pr"]}' if e.get("gerrit") else f'#{e["pr"]}'


def anchor(e):
    return f"{e['repo'].replace('/', '-')}-{e['pr']}"


def stage_of(e, ev):
    live = (ev.get(key(e)) or {}).get("live") or {}
    return live.get("stage") or ("open" if e.get("status") not in DONE else e["status"])


def landed(e, ev):
    """A contribution that reached the project: merged, or applied/approved by a maintainer.
    `approved` covers OpenSSL-style projects that commit a change to master by hand (the pull
    request then shows as closed on GitHub, which is not a rejection)."""
    return e.get("status") in ("merged", "approved", "accepted") or stage_of(e, ev) == "merged"


def badge(e, ev, t):
    s = stage_of(e, ev)
    draft = ((ev.get(key(e)) or {}).get("live") or {}).get("draft")
    label = t["stages"].get(s, s) + (f' · {t["draft"]}' if draft and s not in DONE else "")
    return f'<span class="badge {s}" data-pr="{html.escape(key(e))}">{html.escape(label)}</span>'


def days(e, ev, today):
    live = (ev.get(key(e)) or {}).get("live") or {}
    start = live.get("opened") or str(e.get("submitted"))
    end = live.get("ended") or (str(e["decided"]) if e.get("status") in DONE and e.get("decided") else None)
    try:
        a = dt.date.fromisoformat(start)
        b = dt.date.fromisoformat(end) if end else today
        return str((b - a).days)
    except ValueError:
        return "—"


def ci_cell(e, ev):
    live = (ev.get(key(e)) or {}).get("live") or {}
    c = live.get("checks") or {}
    parts = []
    if c.get("pass"):
        parts.append(f'<span class="ok">✓{c["pass"]}</span>')
    if c.get("fail"):
        parts.append(f'<span class="bad">✗{c["fail"]}</span>')
    if c.get("pending"):
        parts.append(f'<span class="wait">…{c["pending"]}</span>')
    if live.get("ci_waiting"):
        parts.append(f'<span class="wait">⏸{live["ci_waiting"]}</span>')
    return " ".join(parts) or '<span class="none">—</span>'


def evidence_cell(e, lang, ev):
    t = UI[lang]["ev"]
    url = pr_url(e)
    if e.get("gerrit"):  # the change page on Gerrit shows the description and the files together
        parts = [ext(url, pr_label(e))]
    else:
        parts = [ext(url, f'{t["pr"]} {pr_label(e)}'), ext(url + "/files", t["files"])]
    info = ev.get(key(e)) or {}
    if info.get("approvals"):
        people = ", ".join(ext(a["url"], html.escape(a["by"])) for a in info["approvals"])
        parts.append(f'{t["approved_by"]}: {people}')
    if info.get("merge"):
        parts.append(ext(info["merge"]["url"], f'{t["merge"]} {info["merge"]["sha"][:10]}'))
    return " · ".join(parts)


def cve_cell(cve, cvss=None):
    if not cve:
        return '<span class="none">—</span>'
    c = html.escape(cve)
    cell = f'<a href="https://www.cve.org/CVERecord?id={c}">{c}</a>'
    if cvss is not None:
        cell += f' <span class="cvss">CVSS {html.escape(str(cvss))}</span>'
    return cell


def entry(e, lang, ev, today):
    """One pull request: a summary line that opens into its briefing."""
    t = UI[lang]
    url = pr_url(e)
    live = (ev.get(key(e)) or {}).get("live") or {}
    first = live.get("first_response")
    facts = [f'{t["submitted"]} {e["submitted"]}', t["days"].format(n=days(e, ev, today)),
             t["first"].format(d=first) if first else t["no_reply"], f'{t["ci"]} {ci_cell(e, ev)}']
    meta = [f'{html.escape(e["repo"])} {pr_label(e)}', t["types"].get(e["type"], text(e["type"]))]
    if e.get("status") in DONE and e.get("decided"):
        meta.append(f'{t["stages"][e["status"]]} {e["decided"]}')
    if e.get("branches"):
        meta.append(", ".join(html.escape(str(b)) for b in e["branches"]))
    keys = (["cve"] if e.get("cve") else []) + ["defect", "background", "found_by", "fix", "review"]
    dl = "".join(f'<dt>{t["dt"][k]}</dt><dd>{cve_cell(e.get("cve"), e.get("cvss")) if k == "cve" else text(pick(e[k], lang))}</dd>'
                 for k in keys if k == "cve" or e.get(k))
    dl += f'<dt>{t["dt"]["evidence"]}</dt><dd class="evidence">{evidence_cell(e, lang, ev)}</dd>'
    quote = ""
    if e.get("quote"):
        quote = f'<blockquote>"{text(e["quote"])}" — {t["reviewer"]}'
        if lang == "ko" and e.get("quote_ko"):
            quote += f'<br><span class="tr">(번역) {text(e["quote_ko"])}</span>'
        quote += "</blockquote>"
    return f"""
  <details class="entry" id="{anchor(e)}" data-group="{GROUP.get(stage_of(e, ev), "review")}">
    <summary>
      <span class="line1"><b>{text(e['project'])}</b> {badge(e, ev, t)}</span>
      <span class="line2">{text(pick(e['title'], lang))}</span>
      <span class="line3">{' · '.join(facts)}</span>
    </summary>
    <div class="body">
      <div class="meta"><a href="{url}" target="_blank" rel="noopener">{' · '.join(meta)} ↗</a></div>
      <dl>{dl}</dl>{quote}
    </div>
  </details>"""


def vuln_entry(v, lang):
    """A vulnerability report, in the same list as the pull requests. Until the project discloses
    it, only the label, date, channel and stage are shown."""
    t = UI[lang]
    facts = [f'{t["submitted"]} {v.get("submitted")}', text(pick(v.get("channel"), lang)),
             f'CVE {v["cve"]}' if v.get("cve") else f'CVE {t["none_yet"]}']
    if v.get("public"):
        head = f'{text(v.get("project"))}'
        title = text(pick(v.get("title"), lang))
        keys = ["defect", "background", "found_by", "fix"]
        dl = "".join(f'<dt>{t["dt"][k]}</dt><dd>{text(pick(v[k], lang))}</dd>' for k in keys if v.get(k))
        links = [ext(v["advisory"], "Advisory")] if v.get("advisory") else []
        if v.get("cve"):
            links.append(cve_cell(v["cve"], v.get("cvss")))
        body = f'<dl>{dl}<dt>{t["dt"]["evidence"]}</dt><dd class="evidence">{" · ".join(links) or "—"}</dd></dl>'
    else:
        head = f'{t["vuln"]} {html.escape(v["label"])}'
        title = t["private"]
        body = f'<p class="none">{t["private_body"]}</p>'
    return f"""
    <details class="entry" id="{html.escape(v['label'])}">
      <summary>
        <span class="line1"><b>{head}</b> <span class="badge vuln">{t["types"]["vulnerability"]}</span></span>
        <span class="line2">{title}</span>
        <span class="line3">{' · '.join(facts)}</span>
      </summary>
      <div class="body">{body}</div>
    </details>"""


def repo_chip(r, lang, entries):
    """One repository I audit, as a compact chip: project name, a link, and how many of my pull
    requests it carries. The full what-it-is / what-I-look-at text is in its title tooltip."""
    t = UI[lang]
    mine = [e for e in entries if e["repo"] == r["repo"]]
    url = r.get("link") or f'https://github.com/{r["repo"]}'
    n = f'<span class="chip-n">{len(mine)}</span>' if mine else ""
    about = pick(r.get("about"), lang) or ""
    focus = pick(r.get("focus"), lang) or ""
    tip = f'{about} · {t["focus"]}: {focus}'.strip(" ·") if (about or focus) else html.escape(r["repo"])
    return (f'<a class="chip" href="{html.escape(url)}" target="_blank" rel="noopener" '
            f'title="{html.escape(tip)}">{text(r["project"])}{n}</a>')


def win_entry(e, lang):
    """One landed contribution, as what it fixed — no review stage, no open-for-N-days facts."""
    t = UI[lang]
    url = pr_url(e)
    keys = (["cve"] if e.get("cve") else []) + ["defect", "background", "found_by", "fix", "review"]
    dl = "".join(
        f'<dt>{t["dt"][k]}</dt><dd>{cve_cell(e.get("cve"), e.get("cvss")) if k == "cve" else text(pick(e[k], lang))}</dd>'
        for k in keys if k == "cve" or e.get(k))
    files = "" if e.get("gerrit") else f' · {ext(url + "/files", t["ev"]["files"])}'
    dl += f'<dt>{t["dt"]["evidence"]}</dt><dd class="evidence">{ext(url, pr_label(e))}{files}</dd>'
    quote = ""
    if e.get("quote"):
        quote = f'<blockquote>"{text(e["quote"])}" — {t["reviewer"]}'
        if lang == "ko" and e.get("quote_ko"):
            quote += f'<br><span class="tr">(번역) {text(e["quote_ko"])}</span>'
        quote += "</blockquote>"
    typ = t["types"].get(e["type"], text(e["type"]))
    return f"""
        <details class="entry" id="{anchor(e)}">
          <summary>
            <span class="line2">{text(pick(e['title'], lang))}</span>
            <span class="line3">{html.escape(e['repo'])} {pr_label(e)} · {typ}</span>
          </summary>
          <div class="body"><dl>{dl}</dl>{quote}</div>
        </details>"""


def kpi_tile(n, label):
    return f'<div class="kpi"><div class="kpi-n">{n}</div><div class="kpi-l">{html.escape(label)}</div></div>'


def _pr_key(e):
    return int(str(e["pr"])) if str(e["pr"]).isdigit() else 0


def proj_bars(data, lang, ev):
    """Landed contributions as one horizontal bar per project, longest first. A bar opens into that
    project's contributions — this is the drill-down from the overview to the detail."""
    t = UI[lang]
    won = [e for e in (data.get("entries") or []) if landed(e, ev)]
    if not won:
        return ""
    groups = {}
    for e in won:
        groups.setdefault(str(e["project"]), []).append(e)
    order = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))
    mx = max(len(es) for _, es in order)
    rows = []
    for proj, es in order:
        es = sorted(es, key=lambda e: (e["repo"], -_pr_key(e)))
        pct = round(len(es) / mx * 100)
        body = "".join(win_entry(e, lang) for e in es)
        rows.append(f"""
      <details class="bar">
        <summary>
          <span class="bar-name">{text(proj)}</span>
          <span class="bar-track"><span class="bar-fill" style="width:{pct}%"></span></span>
          <span class="bar-n">{len(es)}</span>
        </summary>
        <div class="bar-body">{body}</div>
      </details>""")
    return (f'<h3 class="chart-h">{html.escape(t["chart_by_project"])}</h3>'
            f'<div class="bars">{"".join(rows)}</div>')


def type_mix(data, lang, ev):
    """The mix of what landed, as a single 100%-stacked bar with a labelled legend. Colour follows
    the contribution type in a fixed order (CSS vars --c-<type>), not its rank."""
    t = UI[lang]
    won = [e for e in (data.get("entries") or []) if landed(e, ev)]
    if not won:
        return ""
    counts = {}
    for e in won:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    present = [ty for ty in TYPE_ORDER if counts.get(ty)] + [ty for ty in counts if ty not in TYPE_ORDER]
    total = sum(counts.values()) or 1
    segs, legend = [], []
    for ty in present:
        c = counts[ty]
        name = t["types"].get(ty, text(ty))
        segs.append(f'<span class="seg" style="width:{c / total * 100:.1f}%;background:var(--c-{ty},var(--accent))" '
                    f'title="{html.escape(name)} {c}"></span>')
        legend.append(f'<span class="lg"><span class="sw" style="background:var(--c-{ty},var(--accent))"></span>'
                      f'{html.escape(name)} {c}</span>')
    return (f'<h3 class="chart-h">{html.escape(t["chart_by_type"])}</h3>'
            f'<div class="stack">{"".join(segs)}</div><div class="legend">{"".join(legend)}</div>')


def stats_section(data, lang, ev):
    """The at-a-glance overview: a row of headline numbers, then the two bar charts."""
    t = UI[lang]
    entries = data.get("entries") or []
    won = [e for e in entries if landed(e, ev)]
    tiles = (kpi_tile(len(won), t["kpi_landed"])
             + kpi_tile(len({str(e["project"]) for e in won}), t["kpi_projects"])
             + kpi_tile(len(data.get("vulnerabilities") or []), t["vulns_title"])
             + kpi_tile(len(data.get("repos") or []), t["repos_title"]))
    return f"""
  <section class="stats" id="stats">
    <div class="kpis">{tiles}</div>
    {proj_bars(data, lang, ev)}
    {type_mix(data, lang, ev)}
    <p class="hint">{t["hint"]}</p>
  </section>"""


def vulns_block(data, lang):
    """Vulnerability reports, folded away by default so the page stays short; the headline count is
    in the overview. Open to read each report (named only once a project discloses it)."""
    t = UI[lang]
    vulns = list(data.get("vulnerabilities") or [])
    if not vulns:
        return ""
    body = "".join(vuln_entry(v, lang) for v in vulns)
    return f"""
  <details class="fold" id="vulns">
    <summary><b>{t["vulns_title"]}</b> <span class="fold-n">{len(vulns)}</span></summary>
    <div class="fold-body"><p class="hint">{t["vulns_hint"]}</p>{body}</div>
  </details>"""


def repos_block(data, lang, entries):
    """Repositories I audit, folded away by default as a strip of chips; the headline count is in
    the overview. Each chip links to the repository and carries my open pull-request count."""
    t = UI[lang]
    repos = list(data.get("repos") or [])
    if not repos:
        return ""
    chips = "".join(repo_chip(r, lang, entries) for r in repos)
    return f"""
  <details class="fold" id="repos">
    <summary><b>{t["repos_title"]}</b> <span class="fold-n">{len(repos)}</span></summary>
    <div class="fold-body"><p class="hint">{t["repos_hint"]}</p><div class="chips">{chips}</div></div>
  </details>"""


def render(data, lang, tmpl, ev, today):
    t, owner = UI[lang], data["owner"]
    entries = data.get("entries") or []
    subs = {
        "html_lang": t["html_lang"], "name": html.escape(owner["name"]),
        "title_suffix": t["title_suffix"], "tagline": html.escape(pick(owner["tagline"], lang)),
        "switch": t["switch"],
        "tags": "".join(f"<li>{html.escape(a)}</li>" for a in pick(owner["areas"], lang)),
        "stats": stats_section(data, lang, ev),
        "vulns": vulns_block(data, lang),
        "repos": repos_block(data, lang, entries),
        "footer": html.escape(t["footer"].format(d=today.isoformat())),
    }
    n = sum(1 for e in entries if landed(e, ev))
    return re.sub(r"\{\{(\w+)\}\}", lambda m: subs[m.group(1)], tmpl), n


def main():
    data = yaml.safe_load(open(os.path.join(HERE, "contributions.yaml"), encoding="utf-8"))
    tmpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    ev_path = os.path.join(HERE, "github.json")
    ev = json.load(open(ev_path, encoding="utf-8")) if os.path.exists(ev_path) else {}
    today = dt.datetime.now(KST).date()
    listed = {r["repo"] for r in data.get("repos") or []}
    for repo in sorted({e["repo"] for e in data.get("entries") or []} - listed):
        print(f"note: {repo} has pull requests but no card under repos:")
    for lang, path in (("en", "index.html"), ("ko", os.path.join("ko", "index.html"))):
        out, n = render(data, lang, tmpl, ev, today)
        os.makedirs(os.path.dirname(os.path.join(HERE, path)) or HERE, exist_ok=True)
        open(os.path.join(HERE, path), "w", encoding="utf-8").write(out)
        print(f"{path}: {n} landed contributions")


if __name__ == "__main__":
    main()
