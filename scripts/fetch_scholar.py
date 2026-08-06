#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从谷歌学术抓取论文列表，合并进 data/publications.json。

两种数据源，自动二选一：
  * SERPAPI_KEY 存在  -> 走 SerpApi（稳定，推荐；免费额度足够每月跑一次）
  * 否则              -> 走 scholarly 库直连（免费，但 GitHub 机房 IP 常被谷歌拦）

合并规则（重要）：
  * 已有论文：只更新引用数，其余字段不动——你手工修过的标题/期刊不会被覆盖
  * 新论文：自动归类，打上 needs_review 标记，等你在 PR 里过一眼
  * data/overrides.json 里的内容永远优先，抓取永远不会碰它
"""
import json, os, re, sys, unicodedata
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from classify import classify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBS = os.path.join(ROOT, "data", "publications.json")
PROFILE = os.path.join(ROOT, "data", "profile.yml")

MIN_YEAR = int(os.getenv("MIN_YEAR", "2005"))


# ---------------------------------------------------------------- 工具

def norm_key(title):
    t = unicodedata.normalize("NFKD", title or "").lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_publication(s):
    """'IEEE Trans. Instrum. Meas. 69 (10), 7411-7421, 2020' -> (venue, year, detail)"""
    s = (s or "").strip()
    year = None
    m = re.search(r"\b(19|20)\d{2}\b(?!.*\b(19|20)\d{2}\b)", s)
    if m:
        year = int(m.group(0))
        s = (s[:m.start()] + s[m.end():]).strip(" ,")
    m = re.search(r"\s(\d+)\s*(\(\d+\))?\s*,\s*([\dA-Za-z\-–]+)\s*$", s)
    detail = ""
    if m:
        vol, iss, pages = m.group(1), m.group(2) or "", m.group(3)
        detail = f"{vol}{iss}: p. {pages}"
        s = s[:m.start()].strip(" ,")
    return s.strip(" ,"), year, detail


def format_authors(s):
    """'R Song, S Zhang, C Li' -> 'Song, R., S. Zhang, C. Li'（与旧站体例一致）"""
    parts = [a.strip() for a in re.split(r",| and ", s or "") if a.strip()]
    out = []
    for i, a in enumerate(parts):
        toks = a.split()
        if len(toks) < 2:
            out.append(a); continue
        initials, last = toks[:-1], toks[-1]
        ini = " ".join(t if t.endswith(".") else t + "." for t in initials)
        out.append(f"{last}, {ini}" if i == 0 else f"{ini} {last}")
    if len(out) > 1:
        out[-1] = "and " + out[-1]
    return ", ".join(out)


def slug(authors, year, title):
    first = re.sub(r"[^a-z]", "", re.split(r"[,\s]", authors.strip())[0].lower()) or "anon"
    words = [w for w in re.sub(r"[^a-z ]", " ", (title or "").lower()).split() if len(w) > 3]
    return f"{first}{year or 'na'}{words[0] if words else 'paper'}"


# ---------------------------------------------------------------- 数据源

def from_serpapi(author_id, key):
    import urllib.parse, urllib.request
    arts, start = [], 0
    while True:
        q = urllib.parse.urlencode({
            "engine": "google_scholar_author", "author_id": author_id,
            "api_key": key, "num": 100, "start": start, "sort": "pubdate",
        })
        with urllib.request.urlopen("https://serpapi.com/search.json?" + q, timeout=90) as r:
            d = json.loads(r.read().decode())
        if d.get("error"):
            raise RuntimeError(d["error"])
        batch = d.get("articles", [])
        arts += batch
        if len(batch) < 100:
            break
        start += 100
    out = []
    for a in arts:
        venue, year, detail = parse_publication(a.get("publication", ""))
        out.append({
            "title": (a.get("title") or "").strip(),
            "authors": format_authors(a.get("authors", "")),
            "venue": venue,
            "year": int(a["year"]) if str(a.get("year", "")).isdigit() else year,
            "detail": detail,
            "citations": int((a.get("cited_by") or {}).get("value") or 0),
            "scholar_id": a.get("citation_id"),
            "url": a.get("link"),
        })
    return out


def from_scholarly(author_id):
    from scholarly import scholarly
    author = scholarly.search_author_id(author_id)
    author = scholarly.fill(author, sections=["publications"])
    out = []
    for pub in author.get("publications", []):
        bib = pub.get("bib", {})
        title = (bib.get("title") or "").strip()
        # 列表页会把长标题截断成 "…"，只对这些补一次详情，尽量少发请求
        if title.endswith(("…", "...")):
            try:
                pub = scholarly.fill(pub)
                bib = pub.get("bib", {})
                title = (bib.get("title") or title).strip()
            except Exception:
                pass
        venue, year, detail = parse_publication(
            " ".join(filter(None, [bib.get("citation", ""), str(bib.get("pub_year", ""))])))
        out.append({
            "title": title,
            "authors": format_authors(bib.get("author", "").replace(" and ", ", ")),
            "venue": venue or bib.get("journal", "") or bib.get("venue", ""),
            "year": int(bib["pub_year"]) if str(bib.get("pub_year", "")).isdigit() else year,
            "detail": detail,
            "citations": int(pub.get("num_citations") or 0),
            "scholar_id": pub.get("author_pub_id"),
            "url": None,
        })
    return out


# ---------------------------------------------------------------- 合并

def main():
    import yaml
    prof = yaml.safe_load(open(PROFILE, encoding="utf-8"))
    author_id = prof["scholar"]["author_id"]

    key = os.getenv("SERPAPI_KEY")
    fetched = from_serpapi(author_id, key) if key else from_scholarly(author_id)
    fetched = [f for f in fetched if f["title"] and (f["year"] or 0) >= MIN_YEAR]
    print(f"谷歌学术返回 {len(fetched)} 条")

    existing = json.load(open(PUBS, encoding="utf-8")) if os.path.exists(PUBS) else []
    index = {norm_key(x["title"]): x for x in existing}
    by_sid = {x["scholar_id"]: x for x in existing if x.get("scholar_id")}

    added, updated = [], 0
    for f in fetched:
        old = by_sid.get(f["scholar_id"]) or index.get(norm_key(f["title"]))
        if old:
            if f["citations"] != old.get("citations"):
                old["citations"] = f["citations"]; updated += 1
            old.setdefault("scholar_id", f["scholar_id"])
            old["scholar_id"] = old.get("scholar_id") or f["scholar_id"]
            if not old.get("url"):
                old["url"] = f["url"]
            continue

        cat, src = classify(f["title"], f["venue"], f["authors"])
        rec = {
            "id": slug(f["authors"], f["year"], f["title"]),
            "title": f["title"], "authors": f["authors"], "venue": f["venue"],
            "year": f["year"], "detail": f["detail"],
            "category": cat, "category_source": src,
            "corresponding": False, "selected": False,
            "pdf": None, "url": f["url"], "scholar_id": f["scholar_id"],
            "citations": f["citations"], "added": str(date.today()),
            "needs_review": True,
        }
        existing.append(rec); index[norm_key(rec["title"])] = rec
        added.append(rec)

    existing.sort(key=lambda x: (-(x.get("year") or 0), -(x.get("citations") or 0), x["title"]))
    json.dump(existing, open(PUBS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 给 PR 正文用的摘要
    lines = [f"从谷歌学术同步：新增 **{len(added)}** 篇，更新引用数 **{updated}** 篇。", ""]
    for r in added:
        lines.append(f"- **{r['title']}** — {r['venue']}, {r['year']}  \n"
                     f"  归类 `{r['category']}`（依据：{r['category_source']}）")
    if added:
        lines += ["", "分类不对就改 `data/publications.json` 里的 `category`，"
                      "或在 `data/overrides.json` 里写死。确认无误后合并即可。"]
    open(os.path.join(ROOT, "SYNC_REPORT.md"), "w", encoding="utf-8").write("\n".join(lines))
    print(f"新增 {len(added)} 篇，更新引用数 {updated} 篇")
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"added={len(added)}\nupdated={updated}\n")


if __name__ == "__main__":
    main()
