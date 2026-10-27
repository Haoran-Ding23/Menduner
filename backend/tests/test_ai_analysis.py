"""AI 商圈分析的测试（GPT Round 21 的约束全部要有测试兜底）。

重点不是"模型能不能生成"，而是：
  1) 模型编造数字必须被拦下，不能进页面；
  2) 引用白名单之外的指标必须被拒；
  3) 出现经营预测措辞必须被拒；
  4) 模型不可用 / 报错时必须返回 available=false，不许编内容。
"""
import json

import pytest

from backend import ai_analysis, llm, market_area
from backend.database import connect, initialize


def add(con, table, ident, payload):
    con.execute(f"INSERT INTO {table}(id,payload) VALUES(?,?)", (ident, json.dumps(payload, ensure_ascii=False)))


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    with connect(path) as con:
        con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                    ("s1", "来源", "government", 0, "https://a.test", "2026-10-01T00:00:00+00:00"))
        add(con, "districts", "area-a", {"id": "area-a", "name": "观前", "kind": "business_area",
                                         "status": "official",
                                         "center": {"lng": 120.62, "lat": 31.31, "system": "GCJ-02",
                                                    "radiusMeters": 800, "matchLevel": "verified"}})
        add(con, "venues", "v1", {"id": "v1", "name": "场馆",
                                  "coordinates": {"lng": 120.6205, "lat": 31.3105, "system": "GCJ-02",
                                                  "status": "Verified"}})
        add(con, "hotels", "h1", {"id": "h1", "name": "酒店",
                                  "coordinates": {"lng": 120.6210, "lat": 31.3110, "system": "GCJ-02",
                                                  "status": "Verified"}})
        con.execute(
            "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
            "verification_status,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("e1", "活动一", "culture", "2026-11-10", "2026-11-12", "v1", "area-a", "s1",
             "Verified", "{}"))
    return path


def test_llm_unavailable_returns_not_available(db, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    result = ai_analysis.analyze_area(db, "area-a", 800)
    assert result["available"] is False
    assert result["findings"] == []
    assert "不可用" in result["reason"]
    assert result["verificationStatus"] == "ai_analysis_unverified"


def test_llm_error_returns_not_available(db, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    def boom(*_args, **_kwargs):
        raise llm.LLMError("模型调用失败")

    monkeypatch.setattr(llm, "chat_json", boom)
    result = ai_analysis.analyze_area(db, "area-a", 800)
    assert result["available"] is False
    assert result["findings"] == []


def test_invented_numbers_are_rejected(db, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {
        "summary": "样本里活动集中",
        "findings": [
            {"claim": "本月约有 35 场活动", "metricKeys": ["uniqueNearbyEvents"]},   # 编造数字
            {"claim": "这个地点周边有已收录活动", "metricKeys": ["uniqueNearbyEvents"]},  # 合法
        ],
        "unknowns": ["真实客流"],
        "limitations": ["近邻不是边界"],
        "businessQuestions": ["哪些活动值得跟进"],
    })
    result = ai_analysis.analyze_area(db, "area-a", 800)
    assert result["available"] is True
    claims = [item["claim"] for item in result["findings"]]
    assert claims == ["这个地点周边有已收录活动"]
    assert any("不存在的数字" in item["reason"] for item in result["rejected"])


def test_unknown_metric_keys_are_rejected(db, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {
        "summary": "x",
        "findings": [{"claim": "周边酒店很多", "metricKeys": ["hotelCount"]}],
        "unknowns": [], "limitations": [], "businessQuestions": [],
    })
    result = ai_analysis.analyze_area(db, "area-a", 800)
    assert result["findings"] == []
    assert any("未引用可用指标" in item["reason"] for item in result["rejected"])


def test_forbidden_prediction_wording_is_rejected(db, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {
        "summary": "该商圈潜力第一",
        "findings": [{"claim": "预计入住率会提升", "metricKeys": ["uniqueNearbyEvents"]}],
        "unknowns": [], "limitations": [], "businessQuestions": [],
    })
    result = ai_analysis.analyze_area(db, "area-a", 800)
    assert result["findings"] == []
    assert result["summary"].startswith("（概要含禁止措辞")
    assert any("禁止的经营预测措辞" in item["reason"] for item in result["rejected"])


def test_valid_findings_pass_with_metrics(db, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {
        "summary": "这个地点周边以文化活动为主",
        "findings": [{"claim": "周边有已收录的活动与住宿", "metricKeys": ["uniqueNearbyEvents", "hotelsInRadius"]}],
        "unknowns": ["真实客流"], "limitations": ["中心点近邻不是边界"], "businessQuestions": ["哪些值得跟进"],
    })
    result = ai_analysis.analyze_area(db, "area-a", 800)
    assert result["available"] is True
    assert result["findings"][0]["metricKeys"] == ["uniqueNearbyEvents", "hotelsInRadius"]
    assert result["metrics"]["uniqueNearbyEvents"] == 1
    assert result["unknowns"] == ["真实客流"]
