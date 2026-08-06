#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性迁移脚本：把旧版 publications.html / index.html / students.html
解析成 data/ 下的结构化数据。跑完一次就可以删掉（保留仅作存档）。

用法: python3 scripts/migrate_legacy.py <旧文件目录>
"""
import json, os, re, sys, unicodedata
from datetime import date

SRC = sys.argv[1] if len(sys.argv) > 1 else "legacy"
OUT = "data"

CAT_MAP = {
    "Vision-based vital sign monitoring": "vision",
    "Human-machine natural interaction": "hmi",
    "Electromagnetic modeling and inverse scattering": "em",
}

ENTRY = re.compile(
    r"^\s*\d+\.\s*(?P<authors>.+?),\s*<i>(?P<title>.+?)</i>\s*(?P<rest>.*?)\s*(?:<p>)?\s*$"
)


def strip_comments(s):
    return re.sub(r"<!--.*?-->", "", s, flags=re.S)


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ").strip()


def norm_key(title):
    """用于去重的标题指纹：小写、去标点、压空格。"""
    t = unicodedata.normalize("NFKD", title).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def slug(authors, year, title):
    first = re.split(r"[,\s]", authors.strip())[0].lower()
    first = re.sub(r"[^a-z]", "", first) or "anon"
    words = [w for w in re.sub(r"[^a-z ]", " ", title.lower()).split() if len(w) > 3]
    return f"{first}{year or 'na'}{words[0] if words else 'paper'}"


def split_rest(rest):
    """把 'IEEE Trans. xxx, 2023. <b>70</b>(8): p. 6218-6228.' 拆成 venue / year / detail"""
    txt = strip_tags(rest)
    m = list(re.finditer(r",\s*(\d{4})\b", txt))
    if m:
        last = m[-1]
        venue = txt[: last.start()].strip(" ,.")
        year = int(last.group(1))
        detail = txt[last.end():].strip(" .:")
    else:
        venue, year, detail = txt.strip(" ,."), None, ""
    detail = re.sub(r"^\.?\s*", "", detail).strip(" .")
    return venue, year, detail


def parse_pub_file(path):
    raw = strip_comments(open(path, encoding="utf-8").read())
    lines = raw.replace("\r\n", "\n").split("\n")
    pubs, conf, cat, in_conf = [], [], None, False
    for line in lines:
        h = re.search(r'size="4">([^<]+?)\s*(?:\(sort by date\))?:?\s*</font>', line)
        if h:
            name = h.group(1).strip().rstrip(":")
            if name.lower().startswith("conference"):
                in_conf, cat = True, None
            else:
                in_conf, cat = False, CAT_MAP.get(name)
            continue
        if in_conf and "<li>" in line:
            t = strip_tags(line)
            if t:
                conf.append(t)
            continue
        m = ENTRY.match(line.strip())
        if not m or cat is None:
            continue
        authors = strip_tags(m.group("authors"))
        title = strip_tags(m.group("title")).rstrip(".")
        venue, year, detail = split_rest(m.group("rest"))
        pubs.append({
            "id": slug(authors, year, title),
            "title": title,
            "authors": authors.replace("Song*", "Song"),
            "venue": venue,
            "year": year,
            "detail": detail,
            "category": cat,
            "category_source": "legacy",
            "corresponding": "Song*" in m.group("authors") or "Song*" in authors,
            "selected": False,
            "pdf": None,
            "url": None,
            "scholar_id": None,
            "citations": 0,
            "added": str(date.today()),
        })
    return pubs, conf


def parse_index(path):
    raw = strip_comments(open(path, encoding="utf-8").read().replace("\r\n", "\n"))
    sel_titles, patents = set(), []
    section = None
    for line in raw.split("\n"):
        if "Selected Journal Papers" in line:
            section = "sel"; continue
        if "<strong>Patents" in line:
            section = "pat"; continue
        if "<strong>Teaching" in line:
            section = None; continue
        m = ENTRY.match(line.strip())
        if not m:
            continue
        title = strip_tags(m.group("title")).rstrip(".")
        if section == "sel":
            sel_titles.add(norm_key(title))
        elif section == "pat":
            venue, year, detail = split_rest(m.group("rest"))
            num = re.search(r"US Patent ([\d,]+)", strip_tags(m.group("rest")))
            patents.append({
                "inventors": strip_tags(m.group("authors")),
                "title": title,
                "year": year or (int(re.search(r"(\d{4})", strip_tags(m.group('rest'))).group(1))
                                 if re.search(r"(\d{4})", strip_tags(m.group("rest"))) else None),
                "number": ("US " + num.group(1)) if num else strip_tags(m.group("rest")).strip(" ."),
            })
    return sel_titles, patents


def parse_students(path):
    raw = strip_comments(open(path, encoding="utf-8").read().replace("\r\n", "\n"))
    grads, current = [], []
    for m in re.finditer(r"<li>(.*?)</li>", raw, re.S):
        t = strip_tags(m.group(1))
        if not t:
            continue
        if "graduate student of year" in t:
            name = t.split(",")[0].strip()
            topic = t.split("working on")[-1].strip(" .") if "working on" in t else ""
            current.append({"name": name, "stage": "在读", "topic": topic})
        else:
            ym = re.search(r"\((\d{4})\)", t)
            name = t.split("(")[0].strip()
            rest = t.split(")", 1)[1].strip(" ,.") if ")" in t else ""
            honor = ""
            if "outstanding" in rest:
                parts = re.split(r"(?=(?:He|She) was awarded)", rest, maxsplit=1)
                rest, honor = parts[0].strip(" ,."), (parts[1].strip() if len(parts) > 1 else "")
            grads.append({"name": name, "year": int(ym.group(1)) if ym else None,
                          "position": rest, "honor": honor})
    return grads, current


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    pubs, conf = parse_pub_file(os.path.join(SRC, "publications.html"))
    sel, patents = parse_index(os.path.join(SRC, "index.html"))

    # 去重（同一篇可能出现在多个板块）+ 标记 selected
    seen, merged = {}, []
    for p in pubs:
        k = norm_key(p["title"])
        if k in seen:
            continue
        p["selected"] = k in sel
        seen[k] = p
        merged.append(p)
    merged.sort(key=lambda x: (-(x["year"] or 0), x["title"]))

    json.dump(merged, open(f"{OUT}/publications.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump({"conferences": conf}, open(f"{OUT}/conferences.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(patents, open(f"{OUT}/patents.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    g, c = parse_students(os.path.join(SRC, "students.html"))
    json.dump({"graduated": g, "current": c},
              open(f"{OUT}/students.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"论文 {len(merged)} 篇 (selected {sum(p['selected'] for p in merged)}), "
          f"会议 {len(conf)}, 专利 {len(patents)}, 学生 {len(g)}+{len(c)}")
    from collections import Counter
    print(Counter(p["category"] for p in merged))
