#!/usr/bin/env python3
"""Render the portfolio from contributions.yaml in English and Korean.

  python3 build.py      # writes index.html (en) and ko/index.html (ko)

Only entries whose status is approved or merged are shown.
"""
import datetime as dt
import html
import os
import re

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SHOWN = ("approved", "merged")

UI = {
    "en": {
        "html_lang": "en", "title_suffix": "Open-source security contributions",
        "switch": '<a href="ko/" hreflang="ko">한국어</a>', "glance": "At a glance",
        "contributions": "Contributions", "details": "Details",
        "cols": ["Project", "Contribution", "Type", "CVE", "Status", "Date"],
        "stats": ["approved or merged", "projects", "CVEs"],
        "types": {"hardening": "Hardening", "bugfix": "Bug fix", "vulnerability": "Vulnerability"},
        "status": {"approved": "Approved", "merged": "Merged"},
        "dt": {"cve": "CVE", "defect": "Defect", "found_by": "Found by", "fix": "Fix", "review": "Review"},
        "submitted": "submitted", "reviewer": "reviewer", "empty": "Nothing approved yet.",
        "footer": ("Updated {d}. Only approved or merged work is listed; each entry links to the original "
                   "pull request or advisory. Development was assisted by Claude Code, and every change was "
                   "reproduced, tested and disclosed as AI-assisted in the commit."),
    },
    "ko": {
        "html_lang": "ko", "title_suffix": "오픈소스 보안 기여",
        "switch": '<a href="../" hreflang="en">English</a>', "glance": "한눈에 보기",
        "contributions": "기여 목록", "details": "상세",
        "cols": ["프로젝트", "기여", "종류", "CVE", "상태", "날짜"],
        "stats": ["승인·머지", "프로젝트", "CVE"],
        "types": {"hardening": "보안 강화", "bugfix": "버그 수정", "vulnerability": "취약점"},
        "status": {"approved": "승인", "merged": "머지됨"},
        "dt": {"cve": "CVE", "defect": "결함", "found_by": "찾은 방법", "fix": "수정", "review": "리뷰"},
        "submitted": "제출", "reviewer": "리뷰어", "empty": "아직 승인된 기여가 없습니다.",
        "footer": ("{d} 갱신. 승인되거나 머지된 기여만 싣고, 항목마다 원본 PR이나 보안 권고로 연결합니다. "
                   "Claude Code의 도움을 받아 작업했고, 모든 변경은 직접 재현·시험했으며 커밋에 AI 도움을 밝혔습니다."),
    },
}


def pick(v, lang):
    return (v.get(lang) or v.get("en") or "") if isinstance(v, dict) else (v or "")


def text(s):
    """Escape, then turn `code` spans into <code>."""
    s = html.escape(str(s or "").strip())
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", s)


def anchor(e):
    return f"{e['repo'].replace('/', '-')}-{e['pr']}"


def cve_cell(e):
    if not e.get("cve"):
        return '<span class="none">—</span>'
    cve = html.escape(e["cve"])
    cell = f'<a href="https://www.cve.org/CVERecord?id={cve}">{cve}</a>'
    if e.get("cvss") is not None:
        cell += f' <span class="cvss">CVSS {html.escape(str(e["cvss"]))}</span>'
    return cell


def card(e, lang):
    t = UI[lang]
    url = f'https://github.com/{e["repo"]}/pull/{e["pr"]}'
    meta = [f'{html.escape(e["repo"])} #{e["pr"]}', f'{t["submitted"]} {e["submitted"]}',
            f'{t["status"][e["status"]]} {e["decided"]}']
    if e.get("branches"):
        meta.append(", ".join(html.escape(str(b)) for b in e["branches"]))
    keys = (["cve"] if e.get("cve") else []) + ["defect", "found_by", "fix", "review"]
    dl = "".join(f'<dt>{t["dt"][k]}</dt><dd>{cve_cell(e) if k == "cve" else text(pick(e[k], lang))}</dd>'
                 for k in keys if k == "cve" or e.get(k))
    quote = ""
    if e.get("quote"):
        quote = f'<blockquote>"{text(e["quote"])}" — {t["reviewer"]}'
        if lang == "ko" and e.get("quote_ko"):
            quote += f'<br><span class="tr">(번역) {text(e["quote_ko"])}</span>'
        quote += "</blockquote>"
    badge = f'<span class="badge {e["status"]}">{t["status"][e["status"]]}</span>'
    return f"""
  <article id="{anchor(e)}">
    <h3><a href="{url}">{text(e['project'])} — {text(pick(e['title'], lang))}</a>{badge}</h3>
    <div class="meta">{' · '.join(meta)}</div>
    <dl>{dl}</dl>{quote}
  </article>"""


def render(data, lang, tmpl):
    t, owner = UI[lang], data["owner"]
    shown = sorted((e for e in data.get("entries") or [] if e.get("status") in SHOWN),
                   key=lambda e: str(e["decided"]), reverse=True)
    rows = "".join(
        f"<tr><td>{text(e['project'])}</td>"
        f"<td><a href=\"#{anchor(e)}\">{text(pick(e['title'], lang))}</a></td>"
        f"<td>{t['types'].get(e['type'], text(e['type']))}</td><td>{cve_cell(e)}</td>"
        f"<td><span class=\"badge {e['status']}\">{t['status'][e['status']]}</span></td>"
        f"<td>{e['decided']}</td></tr>" for e in shown)
    numbers = [len(shown), len({e["project"] for e in shown}), sum(1 for e in shown if e.get("cve"))]
    subs = {
        "html_lang": t["html_lang"], "name": html.escape(owner["name"]),
        "title_suffix": t["title_suffix"], "tagline": html.escape(pick(owner["tagline"], lang)),
        "switch": t["switch"], "glance": t["glance"], "contributions": t["contributions"],
        "details": t["details"],
        "tags": "".join(f"<li>{html.escape(a)}</li>" for a in pick(owner["areas"], lang)),
        "stats": "".join(f'<div class="stat"><b>{n}</b><span>{l}</span></div>'
                         for n, l in zip(numbers, t["stats"])),
        "head": "".join(f"<th>{c}</th>" for c in t["cols"]),
        "rows": rows or f'<tr><td colspan="6" class="none">{t["empty"]}</td></tr>',
        "cards": "".join(card(e, lang) for e in shown),
        "footer": html.escape(t["footer"].format(d=dt.date.today().isoformat())),
    }
    return re.sub(r"\{\{(\w+)\}\}", lambda m: subs[m.group(1)], tmpl), len(shown)


def main():
    data = yaml.safe_load(open(os.path.join(HERE, "contributions.yaml"), encoding="utf-8"))
    tmpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    for lang, path in (("en", "index.html"), ("ko", os.path.join("ko", "index.html"))):
        out, n = render(data, lang, tmpl)
        os.makedirs(os.path.dirname(os.path.join(HERE, path)) or HERE, exist_ok=True)
        open(os.path.join(HERE, path), "w", encoding="utf-8").write(out)
        print(f"{path}: {n} entries")


if __name__ == "__main__":
    main()
