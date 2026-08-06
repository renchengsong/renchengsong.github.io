#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一篇论文归到三个研究方向之一。

两级策略：
  1) 关键词加权打分——免费、确定、可复现，绝大多数论文一步到位；
  2) 分数不够或前两名咬得太紧时，才调一次大模型（DeepSeek 或 Claude）。

单独运行可以自检规则准确率：
    python3 scripts/classify.py --selftest
"""
import json, os, re, sys, urllib.request

CATEGORIES = ["vision", "hmi", "em"]

# 权重 3 = 该方向的强特征词，出现基本就能定性；权重 1 = 弱线索
KEYWORDS = {
    "vision": {
        3: ["photoplethysmograph", "rppg", "ippg", "remote ppg", "heart rate", "pulse rate",
            "respiratory rate", "respiration rate", "blood pressure", "ballistocardiograph",
            "vital sign", "facial video", "face video", "imaging ppg", "pulse signal",
            "atrial fibrillation screening", "heart rate variability", "photoplethysmography"],
        1: ["camera", "video", "facial", "non-contact", "noncontact", "contactless", "webcam",
            "illumination", "skin", "physiological measurement", "fmcw radar", "cardiac"],
    },
    "hmi": {
        3: ["eeg", "electroencephalogram", "emotion recognition", "seizure prediction",
            "seizure detection", "brain-computer", "brain computer", "emg", "semg",
            "sleep staging", "affective computing", "epilep", "motor imagery", "gaze",
            "gesture recognition", "eye movement", "fatigue detection", "mental workload"],
        1: ["interaction", "capsule network", "domain adaptation", "attention", "transformer",
            "contrastive learning", "neural architecture search", "human-machine", "cognitive"],
    },
    "em": {
        3: ["inverse scattering", "electromagnetic", "scatterer", "permittivity", "dielectric",
            "subspace-based optimization", "som-net", "microwave imaging", "antenna",
            "born approximation", "contrast source", "induced current", "forward solver",
            "logging", "resistivity", "bed boundary", "geosteering", "music algorithm",
            "full-wave", "integral equation", "anisotropic", "waveguide", "tomography",
            "hyperspectral", "unmixing", "meshless", "t-matrix", "helmholtz",
            "boundary element", "obstacle scattering", "green's function", "wavefield"],
        1: ["inversion", "imaging", "scattering", "reconstruction", "medium", "aperture",
            "frequency", "conductivity", "borehole", "downhole", "formation"],
    },
}

VENUE_HINTS = {
    "em": ["antennas and propagation", "microwave theory", "geoscience and remote sensing",
           "computational imaging", "inverse problems", "applied computational electromagnetics"],
    "hmi": ["affective computing", "neural systems and rehabilitation", "cognitive and developmental",
            "biomedical and health informatics", "neural networks and learning"],
    "vision": ["instrumentation and measurement", "physiological measurement", "measurement",
               "biomedical signal processing"],
}

PROMPT = """You classify a paper by Prof. Rencheng Song into exactly one research area.

vision = camera/video-based contactless measurement of human vital signs (rPPG, heart rate,
         respiration, blood pressure, ballistocardiography, facial-video health screening).
hmi    = human-machine natural interaction from physiological signals, mainly EEG
         (emotion recognition, seizure prediction, BCI, EMG, sleep, affective computing).
em     = electromagnetic modeling, inverse scattering, microwave/geophysical imaging,
         antennas, well logging, forward/inverse solvers.

Title: {title}
Venue: {venue}
Authors: {authors}

Answer with JSON only, no prose, no markdown fence:
{{"category": "vision|hmi|em", "confidence": 0.0-1.0, "reason": "<=12 words"}}"""


# ---------------------------------------------------------------- 规则

def score(title, venue="", abstract=""):
    text = f"{title} {abstract}".lower()
    v = (venue or "").lower()
    s = {c: 0 for c in CATEGORIES}
    for cat, groups in KEYWORDS.items():
        for weight, words in groups.items():
            for w in words:
                if w in text:
                    s[cat] += weight
    for cat, hints in VENUE_HINTS.items():
        if any(h in v for h in hints):
            s[cat] += 1  # 期刊只作为很弱的先验，防止 TIM 把一切都吸过去
    return s


def classify_by_rules(title, venue="", abstract=""):
    s = score(title, venue, abstract)
    ranked = sorted(s.items(), key=lambda kv: -kv[1])
    (top, hi), (_, second) = ranked[0], ranked[1]
    confident = hi >= 3 and (hi - second) >= 2
    return top, hi, confident, s


# ---------------------------------------------------------------- LLM 兜底

def _post(url, payload, headers, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def classify_by_llm(title, venue="", authors=""):
    prompt = PROMPT.format(title=title, venue=venue, authors=authors)
    try:
        if os.getenv("DEEPSEEK_API_KEY"):
            d = _post("https://api.deepseek.com/chat/completions",
                      {"model": "deepseek-chat", "temperature": 0,
                       "messages": [{"role": "user", "content": prompt}]},
                      {"Authorization": "Bearer " + os.environ["DEEPSEEK_API_KEY"]})
            txt = d["choices"][0]["message"]["content"]
        elif os.getenv("ANTHROPIC_API_KEY"):
            d = _post("https://api.anthropic.com/v1/messages",
                      {"model": "claude-sonnet-4-6", "max_tokens": 200,
                       "messages": [{"role": "user", "content": prompt}]},
                      {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                       "anthropic-version": "2023-06-01"})
            txt = d["content"][0]["text"]
        else:
            return None, 0.0
        txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
        obj = json.loads(txt)
        cat = obj.get("category")
        return (cat if cat in CATEGORIES else None), float(obj.get("confidence", 0))
    except Exception as e:                                  # 网络/额度/格式出错都不能让构建挂掉
        print(f"  [llm] 调用失败，回退到关键词结果: {e}", file=sys.stderr)
        return None, 0.0


def classify(title, venue="", authors="", abstract=""):
    """返回 (category, source)，source ∈ {rule, llm, rule-fallback}"""
    cat, hi, confident, _ = classify_by_rules(title, venue, abstract)
    if confident:
        return cat, "rule"
    llm_cat, conf = classify_by_llm(title, venue, authors)
    if llm_cat and conf >= 0.5:
        return llm_cat, "llm"
    return cat, "rule-fallback"


# ---------------------------------------------------------------- 自检

def selftest(path="data/publications.json"):
    data = json.load(open(path, encoding="utf-8"))
    ok = amb = 0
    wrong = []
    for x in data:
        cat, hi, confident, s = classify_by_rules(x["title"], x.get("venue", ""))
        if not confident:
            amb += 1
        if cat == x["category"]:
            ok += 1
        else:
            wrong.append((x["title"][:72], x["category"], cat, s, confident))
    n = len(data)
    print(f"规则命中 {ok}/{n} = {ok/n:.1%}；其中 {amb} 篇判为「不确定」会转交大模型")
    print("--- 与人工分类不一致的条目 ---")
    for t, gold, got, s, c in wrong:
        print(f"  [{gold}->{got}] conf={c} {s}  {t}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        print(classify(" ".join(sys.argv[1:]) or "Uncertainty quantification for deep learning-based remote photoplethysmography"))
