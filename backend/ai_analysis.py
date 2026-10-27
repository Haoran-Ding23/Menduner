"""AI 商圈分析（GPT Round 21 批准的「证据约束型」分析，不是商业潜力评分）。

规则（不可放宽）：
1. 只允许描述输入里真实存在的指标；模型给出的 metricKeys 必须命中白名单；
2. **模型不许自己产出统计数字**：claim 里出现的数字必须能在输入指标里找到，
   否则整条 finding 被丢弃并记入 rejected（不是"改一改就用"）；
3. 必须声明 unknowns 与 limitations；缺字段就写进 unknowns；
4. 输出标 verificationStatus = "ai_analysis_unverified"，前端必须显示这是 AI 生成、未经核实；
5. 模型不可用时返回 available=false + 原因，不生成任何替代内容。
"""
from __future__ import annotations

import re

from backend import llm, market_area

# 允许被引用的指标白名单：key -> 从 profile 里取值的路径
METRIC_PATHS: dict[str, tuple[str, ...]] = {
    "uniqueNearbyEvents": ("coverage", "matched"),
    "ambiguousEvents": ("coverage", "ambiguous"),
    "coveredDays": ("supplyProfile", "coveredDays"),
    "venues": ("supplyProfile", "venues"),
    "sourceCoverageRate": ("supplyProfile", "sourceCoverageRate"),
    "spatialMatchRate": ("supplyProfile", "spatialMatchRate"),
    "ambiguityRate": ("supplyProfile", "ambiguityRate"),
    "hotelsInRadius": ("hotelDistribution", "count"),
    "parentDistrictEvents": ("coverage", "parentDistrictEvents"),
    "radiusMeters": ("area", "radiusMeters"),
}

FORBIDDEN = [
    "入住率", "RevPAR", "ADR", "房价预测", "营收", "营业额", "消费额", "客流量",
    "最赚钱", "潜力第一", "建议涨价", "预计增长",
]

SYSTEM_PROMPT = """你是一个只做「证据约束型」解读的助手。严格遵守：
1. 只能引用下面 JSON 里提供的指标值，不得自行计算、估算或补充任何数字；
2. 每条结论必须列出它用到的指标键（metricKeys），键必须来自给定列表；
3. 禁止出现：入住率、RevPAR、ADR、房价预测、营收、营业额、消费额、客流量、最赚钱、潜力第一、建议涨价、预计增长；
4. 必须输出 unknowns 与 limitations；不确定就写进 unknowns，不要猜；
5. 只输出 JSON，结构：
{"summary": "...", "findings": [{"claim": "...", "metricKeys": ["uniqueNearbyEvents"]}],
 "unknowns": ["..."], "limitations": ["..."], "businessQuestions": ["..."]}
语言：简体中文，面向酒店销售/收益人员，句子短，不用技术术语。"""


def _value(profile: dict, path: tuple[str, ...]):
    node = profile
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _numbers_in(text: str) -> list[float]:
    return [float(item) for item in re.findall(r"\d+(?:\.\d+)?", text or "")]


def _sanitize(result: dict, metrics: dict) -> tuple[dict, list[dict]]:
    """丢弃引用不存在指标、或凭空出现数字的结论。返回 (清洗后结果, 被拒清单)。"""
    allowed = {key: value for key, value in metrics.items() if value is not None}
    allowed_values = set()
    for value in allowed.values():
        if isinstance(value, (int, float)):
            allowed_values.add(float(value))
            allowed_values.add(round(float(value) * 100, 1))  # 百分比写法
            allowed_values.add(round(float(value), 1))

    findings, rejected = [], []
    for item in result.get("findings") or []:
        claim = str(item.get("claim") or "").strip()
        keys = [key for key in (item.get("metricKeys") or []) if key in allowed]
        if not claim or not keys:
            rejected.append({"claim": claim, "reason": "未引用可用指标"})
            continue
        invented = [number for number in _numbers_in(claim) if number not in allowed_values]
        if invented:
            rejected.append({"claim": claim, "reason": f"出现输入中不存在的数字：{invented}"})
            continue
        if any(word in claim for word in FORBIDDEN):
            rejected.append({"claim": claim, "reason": "包含禁止的经营预测措辞"})
            continue
        findings.append({"claim": claim, "metricKeys": keys})

    summary = str(result.get("summary") or "").strip()
    if any(word in summary for word in FORBIDDEN):
        summary = "（概要含禁止措辞，已省略）"

    cleaned = {
        "summary": summary,
        "findings": findings,
        "unknowns": [str(item) for item in (result.get("unknowns") or [])][:8],
        "limitations": [str(item) for item in (result.get("limitations") or [])][:8],
        "businessQuestions": [str(item) for item in (result.get("businessQuestions") or [])][:5],
    }
    return cleaned, rejected


def analyze_area(db_path, area_id: str, radius: int = market_area.DEFAULT_RADIUS,
                 start: str | None = None, end: str | None = None) -> dict:
    try:
        profile = market_area.profile(db_path, area_id, radius, start, end)
    except KeyError:
        raise

    metrics = {key: _value(profile, path) for key, path in METRIC_PATHS.items()}
    base = {
        "areaId": area_id,
        "areaName": profile["area"]["name"],
        "radiusMeters": radius,
        "window": profile.get("window"),
        "analysisType": "evidence_based_supply",
        "verificationStatus": "ai_analysis_unverified",
        "metrics": metrics,
        "limits": [
            "中心点近邻不是正式商圈边界",
            "平台只统计已收录数据，样本不代表完整市场",
            "地理近邻不等于业务联系",
        ],
    }

    if not llm.configured():
        return {**base, "available": False, "reason": "未配置模型密钥，AI 解读不可用",
                "findings": [], "unknowns": [], "limitations": base["limits"],
                "businessQuestions": [], "rejected": []}

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "指标（只允许引用这些）：" + str(metrics)
         + "\n可用指标键：" + ", ".join(METRIC_PATHS.keys())},
    ]
    try:
        raw = llm.chat_json(messages, temperature=0.2, max_tokens=900)
    except llm.LLMError as error:
        return {**base, "available": False, "reason": f"AI 解读暂不可用（{error}）",
                "findings": [], "unknowns": [], "limitations": base["limits"],
                "businessQuestions": [], "rejected": []}

    cleaned, rejected = _sanitize(raw, metrics)
    return {**base, **cleaned, "available": True, "reason": None, "rejected": rejected}
