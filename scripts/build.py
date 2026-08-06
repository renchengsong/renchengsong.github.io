#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data/ 里的数据渲染成站点根目录下的静态 HTML。

    python3 scripts/build.py

只读 data/ 和 templates/，只写 index.html / publications.html / students.html / sitemap.xml。
手写内容一律改 data/，不要直接改生成出来的 HTML（会被覆盖）。
"""
import json, os, re, html
from datetime import date, datetime, timezone

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

COLORS = {"vision": "#0e7c86", "hmi": "#7248a8", "em": "#b0611c"}


def load(name, default=None):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) if name.endswith((".yml", ".yaml")) else json.load(f)


def bold_me(authors, variants):
    """把自己的名字加粗。authors 是纯文本，输出是 HTML 片段。"""
    out = html.escape(authors)
    for v in sorted(variants, key=len, reverse=True):
        out = re.sub(r"(?<![\w>])" + re.escape(html.escape(v)) + r"(?![\w<])",
                     f'<span class="me">{html.escape(v)}</span>', out)
    return out


def jsonld(p, n):
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "Person",
        "name": p["person"]["name"],
        "alternateName": p["person"]["name_cn"],
        "jobTitle": p["person"]["title"],
        "email": "mailto:" + p["person"]["email"],
        "url": p["site"]["url"],
        "affiliation": {"@type": "Organization", "name": "Hefei University of Technology"},
        "sameAs": [l["url"] for l in p["person"]["links"] if l["url"].startswith("http")],
        "knowsAbout": [c["name"] for c in p["site"]["categories"]],
        "description": f"{n} peer-reviewed publications.",
    }, ensure_ascii=False)


def main():
    p = load("profile.yml")
    pubs = load("publications.json", [])
    overrides = load("overrides.json", {})
    patents = load("patents.json", [])
    conferences = (load("conferences.json", {}) or {}).get("conferences", [])
    students = load("students.json", {"current": [], "graduated": []})

    # 人工修正优先于自动抓取的一切字段
    for x in pubs:
        ov = overrides.get(x["id"]) or overrides.get(x.get("scholar_id") or "")
        if ov:
            x.update(ov)
    pubs = [x for x in pubs if not x.get("hidden")]

    variants = p["scholar"]["name_variants"]
    for x in pubs:
        x["authors_html"] = bold_me(x.get("authors", ""), variants)
        x.setdefault("category", "vision")

    pubs.sort(key=lambda x: (-(x.get("year") or 0), -(x.get("citations") or 0), x["title"]))
    counts = {c["key"]: sum(1 for x in pubs if x["category"] == c["key"]) for c in p["site"]["categories"]}
    cat_short = {c["key"]: c["short"] for c in p["site"]["categories"]}

    env = Environment(loader=FileSystemLoader(os.path.join(ROOT, "templates")),
                      autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)

    ctx = dict(p=p, site=p["site"]["url"].rstrip("/"), colors=COLORS, counts=counts,
               cat_short=cat_short, patents=patents, conferences=conferences,
               students=students, n_pubs=len(pubs), built=date.today().isoformat(),
               jsonld=jsonld(p, len(pubs)))

    # 首页只放 selected；如果一篇都没标，退化为按引用量取前 12
    sel = [x for x in pubs if x.get("selected")]
    if not sel:
        sel = sorted(pubs, key=lambda x: -(x.get("citations") or 0))[:12]

    pages = [
        ("index.html", "index.html", dict(page="index", page_url="", pubs=sel)),
        ("publications.html", "publications.html", dict(page="pubs", page_url="publications.html", pubs=pubs)),
        ("students.html", "students.html", dict(page="students", page_url="students.html", pubs=[])),
    ]
    for tpl, out, extra in pages:
        rendered = env.get_template(tpl).render(**{**ctx, **extra})
        with open(os.path.join(ROOT, out), "w", encoding="utf-8") as f:
            f.write(rendered)
        print("写出", out)

    write_sitemap(p, pubs)


def write_sitemap(p, pubs):
    base = p["site"]["url"].rstrip("/")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    urls = [(base + "/", "1.00"), (base + "/publications.html", "0.80"),
            (base + "/students.html", "0.60")]
    for x in pubs:
        if x.get("pdf"):
            urls.append((f"{base}/{x['pdf'].lstrip('/')}", "0.50"))
    body = "\n".join(
        f"  <url>\n    <loc>{html.escape(u)}</loc>\n    <lastmod>{now}</lastmod>\n"
        f"    <priority>{pr}</priority>\n  </url>" for u, pr in urls)
    with open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"{body}\n</urlset>\n")
    print("写出 sitemap.xml")


if __name__ == "__main__":
    main()
