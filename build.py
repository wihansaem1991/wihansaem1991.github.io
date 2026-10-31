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
STAGE_ORDER = ["merged", "approved", "rereview", "changes", "review", "ci_approval", "closed"]

UI = {
    "en": {
        "html_lang": "en", "title_suffix": "Open-source security contributions & CVE challenge",
        "switch": '<a href="ko/" hreflang="ko">한국어</a>',
        "glance": "Progress", "challenge": "Pull requests", "cve": "CVE challenge", "details": "Briefings",
        "cols": ["Project", "Contribution", "Type", "Stage", "Submitted", "Days", "First response", "CI"],
        "cve_cols": ["Report", "Submitted", "Channel", "Stage", "CVE", "Details"],
        "stats": ["pull requests", "maintainer replied", "approved or merged", "vulnerability reports", "CVEs"],
        "types": {"hardening": "Hardening", "bugfix": "Bug fix", "test": "Test coverage",
                  "vulnerability": "Vulnerability"},
        "stages": {"merged": "Merged", "approved": "Approved", "rereview": "Updated, awaiting re-review",
                   "changes": "Changes requested", "review": "Awaiting review",
                   "ci_approval": "Awaiting CI approval", "closed": "Closed", "open": "Open"},
        "vstages": {"triage": "Under triage", "accepted": "Accepted", "fixed": "Fixed",
                    "published": "Published", "closed": "Closed"},
        "draft": "draft", "none_yet": "none yet", "private": "Project and details withheld until disclosure",
        "dt": {"cve": "CVE", "defect": "Problem", "background": "Background", "found_by": "How it was found",
               "fix": "Fix", "review": "Review", "evidence": "Evidence"},
        "ev": {"pr": "Pull request", "files": "Changed files", "approved_by": "Approved by", "merge": "Merge commit"},
        "submitted": "submitted", "reviewer": "reviewer", "empty": "Nothing submitted yet.",
        "no_cve": "No vulnerability reports yet.",
        "live": "Stages read from GitHub just now ({t}).",
        "snapshot": "Showing the snapshot of {d}; GitHub could not be reached from this browser.",
        "loading": "Reading current stages from GitHub…",
        "footer": ("Updated {d}; refreshed from GitHub every hour, and merged, closed and approved stages are "
                   "re-read on every page load. Private vulnerability reports show only their stage until the "
                   "project discloses them. Development was assisted by Claude Code; every change was "
                   "reproduced and tested, and AI assistance is disclosed in each commit."),
    },
    "ko": {
        "html_lang": "ko", "title_suffix": "오픈소스 보안 기여 · CVE 도전",
        "switch": '<a href="../" hreflang="en">English</a>',
        "glance": "진행 현황", "challenge": "PR 도전 현황", "cve": "CVE 도전", "details": "브리핑",
        "cols": ["프로젝트", "기여", "종류", "단계", "제출", "경과일", "첫 응답", "CI"],
        "cve_cols": ["보고", "제출", "경로", "단계", "CVE", "내용"],
        "stats": ["제출한 PR", "메인테이너 응답", "승인·머지", "취약점 보고", "CVE"],
        "types": {"hardening": "보안 강화", "bugfix": "버그 수정", "test": "시험 보강", "vulnerability": "취약점"},
        "stages": {"merged": "머지됨", "approved": "승인", "rereview": "수정 반영, 재리뷰 대기",
                   "changes": "수정 요청", "review": "리뷰 대기", "ci_approval": "CI 실행 허가 대기",
                   "closed": "닫힘", "open": "열림"},
        "vstages": {"triage": "분류 중", "accepted": "인정됨", "fixed": "수정됨", "published": "공개됨",
                    "closed": "종결"},
        "draft": "초안", "none_yet": "아직 없음", "private": "공개 전까지 프로젝트·내용 비공개",
        "dt": {"cve": "CVE", "defect": "문제", "background": "배경 지식", "found_by": "찾은 방법",
               "fix": "수정", "review": "리뷰", "evidence": "증빙"},
        "ev": {"pr": "PR 원문", "files": "바뀐 코드", "approved_by": "승인한 리뷰어", "merge": "머지 커밋"},
        "submitted": "제출", "reviewer": "리뷰어", "empty": "아직 제출한 PR이 없습니다.",
        "no_cve": "아직 취약점 보고가 없습니다.",
        "live": "GitHub에서 방금 단계를 다시 읽었습니다({t}).",
        "snapshot": "{d} 기준 자료입니다. 이 브라우저에서 GitHub에 연결하지 못했습니다.",
        "loading": "GitHub에서 현재 단계를 읽는 중…",
        "footer": ("{d} 갱신. 매시간 GitHub에서 자동으로 다시 읽고, 머지·닫힘·승인 단계는 페이지를 열 때마다 "
                   "다시 확인합니다. 비공개 취약점 보고는 프로젝트가 공개하기 전까지 단계만 보입니다. "
                   "Claude Code의 도움을 받아 작업했고, 모든 변경은 직접 재현·시험했으며 커밋에 AI 도움을 밝혔습니다."),
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


def anchor(e):
    return f"{e['repo'].replace('/', '-')}-{e['pr']}"


def stage_of(e, ev):
    live = (ev.get(key(e)) or {}).get("live") or {}
    return live.get("stage") or ("open" if e.get("status") not in DONE else e["status"])


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
    url = f'https://github.com/{e["repo"]}/pull/{e["pr"]}'
    parts = [ext(url, f'{t["pr"]} #{e["pr"]}'), ext(url + "/files", t["files"])]
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


def card(e, lang, ev):
    t = UI[lang]
    url = f'https://github.com/{e["repo"]}/pull/{e["pr"]}'
    meta = [f'{html.escape(e["repo"])} #{e["pr"]}', f'{t["submitted"]} {e["submitted"]}']
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
  <article id="{anchor(e)}">
    <h3><a href="{url}" target="_blank" rel="noopener">{text(e['project'])} — {text(pick(e['title'], lang))}</a>{badge(e, ev, t)}</h3>
    <div class="meta">{' · '.join(meta)}</div>
    <dl>{dl}</dl>{quote}
  </article>"""


def vuln_row(v, lang):
    t = UI[lang]
    stage = f'<span class="badge v-{html.escape(v.get("status", ""))}">{t["vstages"].get(v.get("status"), v.get("status"))}</span>'
    if v.get("public"):
        title = text(pick(v.get("title"), lang))
        if v.get("advisory"):
            title = ext(v["advisory"], f'{text(v.get("project"))} — {title}')
        detail = title
    else:
        detail = f'<span class="none">{t["private"]}</span>'
    return (f"<tr><td>{html.escape(v['label'])}</td><td>{v.get('submitted')}</td>"
            f"<td>{text(pick(v.get('channel'), lang))}</td><td>{stage}</td>"
            f"<td>{cve_cell(v.get('cve'), v.get('cvss'))}</td><td>{detail}</td></tr>")


def render(data, lang, tmpl, ev, today):
    t, owner = UI[lang], data["owner"]
    entries = list(data.get("entries") or [])
    entries.sort(key=lambda e: (STAGE_ORDER.index(stage_of(e, ev)) if stage_of(e, ev) in STAGE_ORDER else 99,
                                str(e.get("submitted"))), reverse=False)
    vulns = list(data.get("vulnerabilities") or [])
    rows = "".join(
        f"<tr><td>{text(e['project'])}</td>"
        f"<td><a href=\"https://github.com/{e['repo']}/pull/{e['pr']}\" target=\"_blank\" rel=\"noopener\">"
        f"{text(pick(e['title'], lang))} ↗</a> <a class=\"more\" href=\"#{anchor(e)}\">#</a></td>"
        f"<td>{t['types'].get(e['type'], text(e['type']))}</td><td>{badge(e, ev, t)}</td>"
        f"<td>{e['submitted']}</td><td>{days(e, ev, today)}</td>"
        f"<td>{((ev.get(key(e)) or {}).get('live') or {}).get('first_response') or '<span class=\"none\">—</span>'}</td>"
        f"<td>{ci_cell(e, ev)}</td></tr>" for e in entries)
    replied = sum(1 for e in entries if ((ev.get(key(e)) or {}).get("live") or {}).get("first_response"))
    done = sum(1 for e in entries if stage_of(e, ev) in DONE)
    cves = sum(1 for e in entries if e.get("cve")) + sum(1 for v in vulns if v.get("cve"))
    numbers = [len(entries), replied, done, len(vulns), cves]
    stat_ids = ["s-prs", "s-replied", "s-done", "s-vulns", "s-cves"]
    labels = {"owner": owner["github"], "stages": t["stages"], "live": t["live"], "loading": t["loading"],
              "snapshot": t["snapshot"].format(d=today.isoformat()), "done": list(DONE)}
    subs = {
        "html_lang": t["html_lang"], "name": html.escape(owner["name"]),
        "title_suffix": t["title_suffix"], "tagline": html.escape(pick(owner["tagline"], lang)),
        "switch": t["switch"], "glance": t["glance"], "challenge": t["challenge"], "cve": t["cve"],
        "details": t["details"], "loading": t["loading"],
        "tags": "".join(f"<li>{html.escape(a)}</li>" for a in pick(owner["areas"], lang)),
        "stats": "".join(f'<div class="stat"><b id="{i}">{n}</b><span>{l}</span></div>'
                         for i, n, l in zip(stat_ids, numbers, t["stats"])),
        "head": "".join(f"<th>{c}</th>" for c in t["cols"]),
        "rows": rows or f'<tr><td colspan="8" class="none">{t["empty"]}</td></tr>',
        "cve_head": "".join(f"<th>{c}</th>" for c in t["cve_cols"]),
        "cve_rows": "".join(vuln_row(v, lang) for v in vulns)
        or f'<tr><td colspan="6" class="none">{t["no_cve"]}</td></tr>',
        "cards": "".join(card(e, lang, ev) for e in entries),
        "labels": json.dumps(labels, ensure_ascii=False).replace("</", "<\\/"),
        "footer": html.escape(t["footer"].format(d=today.isoformat())),
    }
    return re.sub(r"\{\{(\w+)\}\}", lambda m: subs[m.group(1)], tmpl), len(entries)


def main():
    data = yaml.safe_load(open(os.path.join(HERE, "contributions.yaml"), encoding="utf-8"))
    tmpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    ev_path = os.path.join(HERE, "github.json")
    ev = json.load(open(ev_path, encoding="utf-8")) if os.path.exists(ev_path) else {}
    today = dt.datetime.now(KST).date()
    for lang, path in (("en", "index.html"), ("ko", os.path.join("ko", "index.html"))):
        out, n = render(data, lang, tmpl, ev, today)
        os.makedirs(os.path.dirname(os.path.join(HERE, path)) or HERE, exist_ok=True)
        open(os.path.join(HERE, path), "w", encoding="utf-8").write(out)
        print(f"{path}: {n} entries")


if __name__ == "__main__":
    main()
