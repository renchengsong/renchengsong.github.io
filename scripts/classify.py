#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一篇论文归到三个研究方向之一。

方向定义（2026-08 起）：
  vision — 视觉智能感知：视觉信息 → 生理信号 → 行为/心理状态
  em     — 电磁智能感知：电磁响应 → 正演建模 → 反演 → 结构/参数
  fusion — 多模态融合与物理驱动感知：跨模态互补 + 物理先验 + 不确定性

归属原则：看论文最终解决什么感知问题，不看用了什么算法。
物理驱动深度学习是贯穿三个方向的方法学主线，不单独成类——
用在逆散射上就归 em，用在跨模态或通用鲁棒学习上才归 fusion。

自检：python3 scripts/classify.py --selftest
"""
import json, os, re, sys, urllib.request

CATEGORIES = ["vision", "em", "fusion"]

# 权重 3 = 强特征词，出现基本定性；权重 1 = 弱线索
KEYWORDS = {
    "vision": {
        3: ["photoplethysmograph", "rppg", "ippg", "remote ppg", "heart rate", "pulse rate",
            "heart rate variability", "respiratory rate", "respiration rate", "blood pressure",
            "ballistocardiograph", "vital sign", "facial video", "face video", "imaging ppg",
            "pulse signal", "pulse waveform", "atrial fibrillation", "coronary artery",
            "deception detection", "arterial stiffness", "photoplethysmography",
            "cardiopulmonary coupling", "driver monitoring", "mental stress",
            "video-based", "video based"],
        1: ["camera", "video", "facial", "non-contact", "noncontact", "contactless",
            "webcam", "illumination", "skin", "blood volume", "cardiac", "physiological",
            "blind source separation", "spectrogram", "behaviour", "behavior",
            "心率", "脉搏", "呼吸率", "血压", "视频", "面部", "非接触", "测谎", "生理信号"],
    },
    "em": {
        3: ["inverse scattering", "electromagnetic", "scatterer", "permittivity", "dielectric",
            "subspace-based optimization", "som-net", "microwave imaging", "antenna",
            "born approximation", "contrast source", "induced current", "forward solver",
            "logging", "resistivity", "bed boundary", "geosteering", "music algorithm",
            "full-wave", "integral equation", "waveguide", "tomography", "hyperspectral",
            "unmixing", "meshless", "t-matrix", "helmholtz", "boundary element",
            "obstacle", "green's function", "wavefield", "through-the-wall", "through-wall",
            "computational imaging", "casing corrosion", "earth model", "well log",
            "downhole", "formation", "scattering"],
        1: ["inversion", "imaging", "reconstruction", "medium", "aperture", "conductivity",
            "borehole", "anisotropic", "microwave", "optical", "radar", "signal classification",
            "电磁", "逆散射", "散射", "微波成像", "测井", "天线", "介电", "波导", "高光谱"],
    },
    "fusion": {
        3: ["eeg", "electroencephalogram", "seizure", "epilep", "brain-computer", "brain computer",
            "emg", "semg", "sleep staging", "motor imagery", "multimodal", "multi-modal",
            "cross-modal", "fmcw radar", "modality fusion", "multi-source", "machine unlearning",
            "domain generalization", "domain generalisation", "measurement uncertainty",
            "uncertainty propagation", "uncertainty evaluation", "evidential"],
        1: ["fusion", "domain adaptation", "test-time adaptation", "uncertainty", "robust",
            "physics-informed", "physics-constrained", "calibration", "generalization",
            "incremental learning", "small samples", "interpretab",
            "脑电", "癫痫", "情绪识别", "多模态", "跨模态", "域适应", "不确定度", "不确定性"],
    },
}

# 期刊只作为很弱的先验，防止某个刊把所有论文都吸过去
VENUE_HINTS = {
    "em": ["antennas and propagation", "microwave theory", "geoscience and remote sensing",
           "computational imaging", "inverse problems", "applied computational electromagnetics",
           "optics express", "lightwave technology", "remote sensing"],
    "fusion": ["affective computing", "neural systems and rehabilitation",
               "cognitive and developmental", "biomedical and health informatics",
               "neural networks and learning"],
    "vision": ["physiological measurement", "biomedical signal processing",
               "biomedical optics express", "multimedia"],
}

PROMPT = """You classify a paper by Prof. Rencheng Song into exactly one research area.
Decide by WHAT SENSING PROBLEM the paper solves, not by which algorithm it uses.

vision = non-contact sensing of a person's physiological, behavioural or psychological state
         from visual information (rPPG, heart rate, HRV, respiration, blood pressure,
         ballistocardiography, facial-video screening, video deception detection,
         video emotion recognition, driver monitoring).
em     = electromagnetic response modelling and sensing of intrinsic target properties
         (forward modelling, inverse scattering, microwave/computational imaging, antennas,
         well logging, geosteering, through-wall radar, waveguides, hyperspectral unmixing).
         Physics-informed or unrolled networks applied to EM problems belong HERE, not to fusion.
fusion = multimodal fusion and physics-driven learning as the sensing problem itself
         (EEG-based emotion recognition and seizure prediction, video+radar or video+audio+
         physiology fusion, EEG+facial fusion, general uncertainty quantification,
         domain generalization and robust-learning methodology).

Title: {title}
Venue: {venue}
Authors: {authors}

Answer with JSON only, no prose, no markdown fence:
{{"category": "vision|em|fusion", "confidence": 0.0-1.0, "reason": "<=12 words"}}"""


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
            s[cat] += 1
    for w in ("脑电", "癫痫", "情绪识别", "多模态"):
        if w in text:
            s["fusion"] += 2
    for w in ("逆散射", "电磁", "测井"):
        if w in text:
            s["em"] += 2
    # 明确出现两种以上感知模态时，判为多模态融合
    modal = sum(bool(re.search(pat, text)) for pat in (
        r"video|camera|facial|视频|面部",
        r"radar|雷达",
        r"audio|speech|voice|音频|语音",
        r"\beeg\b|electroencephalogram|脑电",
        r"ppg|physiolog|生理",
    ))
    if modal >= 2 and re.search(r"fusion|multimodal|multi-modal|融合|多模态", text):
        s["fusion"] += 4

    # EEG 出现时，视觉线索不应该把它拉走
    if re.search(r"\beeg\b|electroencephalogram|seizure|epilep|脑电|癫痫", text):
        s["vision"] = max(0, s["vision"] - 4)
    # 逆散射/测井类论文即使谈不确定性或物理约束，仍归 em
    if re.search(r"inverse scattering|microwave imaging|logging|geosteering|scatterer", text):
        s["fusion"] = max(0, s["fusion"] - 4)
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
    except Exception as e:
        print(f"  [llm] 调用失败，回退到关键词结果: {e}", file=sys.stderr)
        return None, 0.0


def classify(title, venue="", authors="", abstract=""):
    """返回 (category, source)，source in {rule, llm, rule-fallback}"""
    cat, hi, confident, _ = classify_by_rules(title, venue, abstract)
    if confident:
        return cat, "rule"
    llm_cat, conf = classify_by_llm(title, venue, authors)
    if llm_cat and conf >= 0.5:
        return llm_cat, "llm"
    return cat, "rule-fallback"


# ---------------------------------------------------------------- 自检

def selftest(path="data/publications.json"):
    data = [x for x in json.load(open(path, encoding="utf-8")) if not x.get("hidden")]
    ok = amb = 0
    wrong = []
    for x in data:
        cat, hi, confident, s = classify_by_rules(x["title"], x.get("venue", ""))
        if not confident:
            amb += 1
        if cat == x.get("category"):
            ok += 1
        else:
            wrong.append((x["title"][:70], x.get("category"), cat, s, confident))
    n = max(1, len(data))
    print(f"规则与当前分类一致 {ok}/{n} = {ok/n:.1%}；{amb} 篇判为不确定，会转交大模型")
    for t, gold, got, s, c in wrong:
        print(f"  [{gold}->{got}] conf={c} {s}  {t}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        q = " ".join(sys.argv[1:]) or "Uncertainty quantification for deep learning-based remote photoplethysmography"
        print(classify(q))
