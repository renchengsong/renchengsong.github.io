#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据本次同步新增的论文，往 data/profile.yml 的 news 里写一条自动摘要。

设计上的三个约束：

1. **不用 PyYAML 重写整个文件。** yaml.dump 会丢掉注释、引号风格和段落顺序，
   profile.yml 是你手工维护的文件，不能被机器格式化。这里只做一次定点的
   文本插入，其余每一行原样保留。

2. **可重复运行。** 自动生成的条目带 `auto: true` 标记。同一个月再跑一次，
   会替换掉上次那条，而不是堆两条。你手写的 News 永远不会被碰。

3. **失败不影响主流程。** 解析不了就原样返回，同步照常完成。

单独测试：
    python3 scripts/news.py            # 打印几个示例句子
"""
import re
from datetime import date

# 常见期刊的通行缩写。没列到的走下面的通用规则。
VENUE_ABBR = {
    "ieee transactions on instrumentation and measurement": "IEEE TIM",
    "ieee transactions on antennas and propagation": "IEEE TAP",
    "ieee transactions on geoscience and remote sensing": "IEEE TGRS",
    "ieee transactions on microwave theory and techniques": "IEEE TMTT",
    "ieee transactions on affective computing": "IEEE TAFFC",
    "ieee transactions on neural systems and rehabilitation engineering": "IEEE TNSRE",
    "ieee transactions on cognitive and developmental systems": "IEEE TCDS",
    "ieee transactions on industrial informatics": "IEEE TII",
    "ieee transactions on computational imaging": "IEEE TCI",
    "ieee transactions on multimedia": "IEEE TMM",
    "ieee transactions on image processing": "IEEE TIP",
    "ieee transactions on biomedical engineering": "IEEE TBME",
    "ieee transactions on neural networks and learning systems": "IEEE TNNLS",
    "ieee journal of biomedical and health informatics": "IEEE JBHI",
    "ieee geoscience and remote sensing letters": "IEEE GRSL",
    "ieee sensors journal": "IEEE Sensors Journal",
    "ieee internet of things journal": "IEEE IoT Journal",
    "computers in biology and medicine": "Computers in Biology and Medicine",
    "expert systems with applications": "Expert Systems with Applications",
    "physiological measurement": "Physiological Measurement",
    "pattern recognition": "Pattern Recognition",
    "measurement": "Measurement",
}

STOP = {"on", "and", "the", "of", "in", "for", "a", "an"}

ONES = ["zero", "one", "two", "three", "four", "five", "six",
        "seven", "eight", "nine", "ten", "eleven", "twelve"]

# 预印本与会议不值得在 News 里点名
SKIP_VENUE = re.compile(r"arxiv|ssrn|preprint|biorxiv|researchsquare|proceedings|conference",
                        re.I)


def abbreviate(venue):
    """把冗长的期刊名压成同行一眼认得的缩写。"""
    v = re.sub(r"\s+", " ", (venue or "").strip()).strip(" ,.")
    if not v:
        return ""
    key = v.lower()
    if key in VENUE_ABBR:
        return VENUE_ABBR[key]

    # IEEE Transactions on X and Y -> IEEE TXY
    m = re.match(r"ieee (transactions|journal) (?:on|of) (.+)$", key)
    if m:
        head = "T" if m.group(1) == "transactions" else "J"
        initials = "".join(w[0] for w in re.findall(r"[a-z]+", m.group(2))
                           if w not in STOP).upper()
        if 2 <= len(initials) <= 5:
            return f"IEEE {head}{initials}"

    v = re.sub(r"^The\s+", "", v)
    return v if len(v) <= 42 else v[:40].rstrip() + "…"


def spell(n):
    return ONES[n] if n < len(ONES) else str(n)


def summarize(new_pubs, max_venues=3):
    """把新增论文列表写成一句 News。没有可写的就返回 None。"""
    pubs = [p for p in new_pubs if (p.get("title") or "").strip()]
    if not pubs:
        return None

    # 预印本不算"发表"，既不点名也不计数
    formal, seen, venues = [], set(), []
    for p in pubs:
        raw = p.get("venue", "") or ""
        name = abbreviate(raw)
        if not name or SKIP_VENUE.search(raw):
            continue
        formal.append(p)
        if name.lower() not in seen:
            seen.add(name.lower())
            venues.append(name)

    n = len(formal) or len(pubs)
    noun = "paper" if n == 1 else "papers"
    verb = "has" if n == 1 else "have"

    if not venues:
        return f"{spell(n).capitalize()} new {noun} {verb} been added to the publication list."

    shown = venues[:max_venues]
    if len(shown) == 1:
        where = shown[0]
    else:
        where = ", ".join(shown[:-1]) + " and " + shown[-1]
    tail = ", among others" if len(venues) > max_venues else ""

    return f"{spell(n).capitalize()} new {noun} published in {where}{tail}."


# ---------------------------------------------------------------- 写回 profile.yml

ITEM = re.compile(r'^  - date:\s*"?(?P<date>[\d-]+)"?\s*$')


def _split_block(lines):
    """返回 (news 起始行号, news 块结束行号)。没有 news 段则返回 (None, None)。"""
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^news:\s*$", ln):
            start = i
            break
    if start is None:
        return None, None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if ln.strip() and not ln.startswith((" ", "\t")):
            end = j
            break
    return start, end


def _item_ranges(block):
    """把 news 块切成一个个条目，返回 [(起, 止, date, is_auto), ...]"""
    idx = [i for i, ln in enumerate(block) if ITEM.match(ln)]
    out = []
    for k, s in enumerate(idx):
        e = idx[k + 1] if k + 1 < len(idx) else len(block)
        chunk = block[s:e]
        d = ITEM.match(block[s]).group("date")
        is_auto = any(re.match(r"^\s+auto:\s*true\s*$", c) for c in chunk)
        out.append((s, e, d, is_auto))
    return out


def escape(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def update_profile(path, text, when=None, keep=12):
    """把一条自动 News 插到最前面。返回 True 表示文件被改动。"""
    when = when or date.today().strftime("%Y-%m")
    try:
        raw = open(path, encoding="utf-8").read()
    except OSError:
        return False
    lines = raw.split("\n")

    entry = [f'  - date: "{when}"', f'    text: "{escape(text)}"', "    auto: true"]

    start, end = _split_block(lines)
    if start is None:
        # 没有 news 段就在文件末尾补一个
        tail = lines[:] 
        while tail and not tail[-1].strip():
            tail.pop()
        new_lines = tail + ["", "news:"] + entry + [""]
        open(path, "w", encoding="utf-8").write("\n".join(new_lines))
        return True

    block = lines[start + 1:end]
    items = _item_ranges(block)

    # 同月的旧自动条目先删掉，手写的一律保留
    drop = {i for (s, e, d, a) in items if a and d == when for i in range(s, e)}
    block = [ln for i, ln in enumerate(block) if i not in drop]

    block = entry + block

    # 控制长度，超出部分只砍自动条目
    items = _item_ranges(block)
    if len(items) > keep:
        drop = set()
        for (s, e, d, a) in items[keep:]:
            if a:
                drop.update(range(s, e))
        block = [ln for i, ln in enumerate(block) if i not in drop]

    lines[start + 1:end] = block
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    return True


if __name__ == "__main__":
    demo = [
        [{"title": "A", "venue": "IEEE Transactions on Instrumentation and Measurement"}],
        [{"title": "A", "venue": "IEEE Transactions on Antennas and Propagation"},
         {"title": "B", "venue": "Measurement"}],
        [{"title": "A", "venue": "IEEE Transactions on Geoscience and Remote Sensing"},
         {"title": "B", "venue": "IEEE Transactions on Microwave Theory and Techniques"},
         {"title": "C", "venue": "IEEE Journal of Biomedical and Health Informatics"},
         {"title": "D", "venue": "Expert Systems with Applications"},
         {"title": "E", "venue": "arXiv preprint arXiv:2601.00001"}],
        [{"title": "A", "venue": "arXiv preprint arXiv:2601.00001"}],
    ]
    for d in demo:
        print("-", summarize(d))
