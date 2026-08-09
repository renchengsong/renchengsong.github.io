#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性清洗 data/publications.json：

  1. 合并重复条目（标题写法不同导致的同一篇论文）
  2. 隐藏被谷歌学术当成论文抓进来的专利（Patents 板块已单独列出）
  3. 预印本（arXiv / SSRN）若已有正式发表版本，隐藏预印本
  4. 按新的三方向体系重新归类：vision / em / fusion
  5. 输出一份清洗报告 CLEANUP_REPORT.md

用法：
    python3 scripts/cleanup.py            # 真的改
    python3 scripts/cleanup.py --dry-run  # 只看报告，不动文件

data/overrides.json 里写死的条目不会被改动。
"""
import json, os, re, sys, unicodedata
from difflib import SequenceMatcher

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from classify import classify_by_rules, classify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBS = os.path.join(ROOT, "data", "publications.json")
OVERRIDES = os.path.join(ROOT, "data", "overrides.json")

DRY = "--dry-run" in sys.argv

# 旧方向 -> 新方向的兜底映射（EEG 类原本在 hmi）
LEGACY_MAP = {"hmi": "fusion", "vision": "vision", "em": "em"}

PREPRINT = re.compile(r"arxiv|ssrn|available at|preprint|researchsquare|biorxiv", re.I)
PATENT = re.compile(r"\bus patent\b|patent app", re.I)


def norm(title):
    """标题指纹：小写、去连字符差异、去标点、压空格。"""
    t = unicodedata.normalize("NFKD", title or "").lower()
    t = t.replace("-", " ").replace("–", " ").replace("—", " ")
    t = re.sub(r"\b(non|multi|inter|intra|sub|pre|post)\s+", r"\1", t)  # non contact -> noncontact
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


def completeness(x):
    """同一篇的多条记录里，挑信息最全的那条留下。"""
    v = (x.get("venue") or "")
    return (
        0 if PREPRINT.search(v) else 1,          # 正式发表 > 预印本
        1 if (x.get("authors") or "").strip() else 0,
        1 if (x.get("detail") or "").strip() else 0,
        x.get("citations") or 0,
        1 if x.get("selected") else 0,
    )


def merge(keep, drop):
    """把被丢弃条目里的有用信息并进保留条目。"""
    keep["citations"] = max(keep.get("citations") or 0, drop.get("citations") or 0)
    for field in ("authors", "detail", "venue", "url", "pdf", "scholar_id"):
        if not (keep.get(field) or "") and drop.get(field):
            keep[field] = drop[field]
    keep["selected"] = bool(keep.get("selected") or drop.get("selected"))
    keep["corresponding"] = bool(keep.get("corresponding") or drop.get("corresponding"))
    if not keep.get("year"):
        keep["year"] = drop.get("year")


def main():
    pubs = json.load(open(PUBS, encoding="utf-8"))
    locked = set(json.load(open(OVERRIDES, encoding="utf-8")).keys()) \
        if os.path.exists(OVERRIDES) else set()

    report = {"dupes": [], "patents": [], "preprints": [], "recat": [], "review": []}

    # ---------- 1. 专利：谷歌学术把它们当论文抓进来了 ----------
    for x in pubs:
        if x.get("id") in locked or x.get("hidden"):
            continue
        blob = f"{x.get('venue','')} {x.get('detail','')} {x.get('title','')}"
        if PATENT.search(blob):
            x["hidden"] = True
            x["hidden_reason"] = "patent — 已在 Patents 板块单独列出"
            report["patents"].append(x["title"])

    # ---------- 2. 合并重复 ----------
    live = [x for x in pubs if not x.get("hidden")]
    keys = [(x, norm(x["title"])) for x in live]
    used = set()
    for i, (a, ka) in enumerate(keys):
        if id(a) in used:
            continue
        group = [a]
        for j in range(i + 1, len(keys)):
            b, kb = keys[j]
            if id(b) in used:
                continue
            if ka == kb or similar(ka, kb) >= 0.90:
                group.append(b)
        if len(group) == 1:
            continue
        group.sort(key=completeness, reverse=True)
        keep, drops = group[0], group[1:]
        for d in drops:
            if d.get("id") in locked:
                continue
            merge(keep, d)
            d["hidden"] = True
            d["hidden_reason"] = f"duplicate of: {keep['title'][:60]}"
            used.add(id(d))
            is_pre = bool(PREPRINT.search(d.get("venue") or ""))
            (report["preprints"] if is_pre else report["dupes"]).append(
                (d["title"], keep["title"]))
        used.add(id(keep))

    # ---------- 3. 按新体系重新归类 ----------
    for x in pubs:
        if x.get("id") in locked or x.get("hidden"):
            continue
        old = x.get("category")
        cat, hi, confident, s = classify_by_rules(x["title"], x.get("venue", ""))
        if confident:
            x.pop("needs_review", None)
            src = "rule"
        else:
            # 规则不自信：有 DEEPSEEK_API_KEY 就交给大模型，否则用得分最高项，
            # 三项全零才退回旧方向的映射
            cat, src = classify(x["title"], x.get("venue", ""), x.get("authors", ""))
            if max(s.values()) == 0 and src != "llm":
                cat = LEGACY_MAP.get(old, cat)
            x["needs_review"] = True
            report["review"].append((x["title"], cat, s))
        if cat != old:
            report["recat"].append((x["title"], old, cat))
        x["category"] = cat
        x["category_source"] = src

    # ---------- 4. 写文件与报告 ----------
    live_n = sum(1 for x in pubs if not x.get("hidden"))
    lines = [
        "# 论文库清洗报告", "",
        f"清洗前 **{len(pubs)}** 条，清洗后可见 **{live_n}** 条"
        f"（隐藏 {len(pubs) - live_n} 条）。", "",
        f"- 专利条目：{len(report['patents'])}",
        f"- 重复条目：{len(report['dupes'])}",
        f"- 预印本与正式版重复：{len(report['preprints'])}",
        f"- 方向调整：{len(report['recat'])}",
        f"- 待人工确认：{len(report['review'])}", "",
    ]

    def block(title, rows, fmt):
        if not rows:
            return
        lines.append(f"## {title}")
        lines.append("")
        lines.extend(fmt(r) for r in rows)
        lines.append("")

    block("隐藏的专利条目", report["patents"], lambda t: f"- {t}")
    block("合并的重复条目", report["dupes"],
          lambda r: f"- 隐藏「{r[0][:70]}」\n  保留「{r[1][:70]}」")
    block("隐藏的预印本", report["preprints"],
          lambda r: f"- 隐藏「{r[0][:70]}」\n  保留「{r[1][:70]}」")
    block("方向发生变化", report["recat"],
          lambda r: f"- `{r[1]}` → `{r[2]}`  {r[0][:70]}")
    block("规则不确定、建议人工过一眼", report["review"],
          lambda r: f"- `{r[1]}` {r[2]}  {r[0][:70]}")

    if DRY:
        print("\n".join(lines))
        return

    json.dump(pubs, open(PUBS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(os.path.join(ROOT, "CLEANUP_REPORT.md"), "w", encoding="utf-8").write("\n".join(lines))
    print(f"清洗完成：可见 {live_n} 条，隐藏 {len(pubs) - live_n} 条")
    for k, v in report.items():
        print(f"  {k}: {len(v)}")


if __name__ == "__main__":
    main()
