"""AI 审核建议的测试：无论模型怎么回，都不许改核验状态、不许伪造建议、判定要留痕。"""
import json

import pytest

from backend import ai_review, llm
from backend.database import connect, initialize


def add(con, table, ident, payload):
    con.execute(f"INSERT INTO {table}(id,payload) VALUES(?,?)", (ident, json.dumps(payload, ensure_ascii=False)))


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    with connect(path) as con:
        con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                    ("s1", "来源", "government", 0, "https://a.test/event/1", "2026-10-01T00:00:00+00:00"))
        add(con, "venues", "v1", {"id": "v1", "name": "橙天嘉禾剧场"})
        con.execute(
            "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
            "verification_status,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("e1", "《信仰》影秀剧", "culture", "2026-11-01", "2026-11-03", "v1", None, "s1",
             "Needs Review", "{}"))
        con.execute(
            "INSERT INTO evidence(id,event_id,entity_id,field,value,source_url,verification_status,payload) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("ev1", "e1", "e1", "sourceUrl", "https://a.test/event/1", "https://a.test/event/1",
             "Unverified", "{}"))
    return path


def test_no_key_returns_unavailable(db, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    result = ai_review.generate(db, limit=5)
    assert result["available"] is False
    assert result["created"] == 0


def test_suggestions_are_stored_without_touching_verification(db, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"items": [
        {"field": "name", "suggestedValue": "《信仰》影秀剧（更正名）", "confidence": "high", "reason": "来源标题更完整"},
        {"field": "hack", "suggestedValue": "x", "confidence": "high", "reason": "白名单外字段"},
    ]})
    result = ai_review.generate(db, limit=5)
    assert result["created"] == 1
    assert result["rows"][0]["field"] == "name"
    assert any("白名单" in item["reason"] for item in result["rejected"])

    # 核心断言：AI 建议不得改动核验状态
    with connect(db) as con:
        status = con.execute("SELECT verification_status FROM events WHERE id='e1'").fetchone()[0]
        evidence_status = con.execute("SELECT verification_status FROM evidence WHERE id='ev1'").fetchone()[0]
        trials = con.execute("SELECT COUNT(*) FROM ai_suggestion_trials").fetchone()[0]
    assert status == "Needs Review"
    assert evidence_status == "Unverified"
    assert trials == 1


def test_short_llm_per_event_is_rejected_not_faked(db, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")

    def boom(*_a, **_k):
        raise llm.LLMError("模型调用失败")

    monkeypatch.setattr(llm, "chat_json", boom)
    result = ai_review.generate(db, limit=5)
    assert result["created"] == 0
    assert any("模型不可用" in item["reason"] for item in result["rejected"])


def test_unchanged_suggestion_is_not_stored(db, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"items": [
        {"field": "sourceUrl", "suggestedValue": "https://a.test/event/1", "confidence": "high", "reason": "一致"},
    ]})
    result = ai_review.generate(db, limit=5)
    assert result["created"] == 0


def test_label_and_stats_are_traceable(db, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"items": [
        {"field": "name", "suggestedValue": "另一个名字", "confidence": "medium", "reason": "来源标题不一致"},
    ]})
    ai_review.generate(db, limit=5)
    trials = ai_review.list_trials(db)["trials"]
    assert len(trials) == 1
    trial_id = trials[0]["id"]

    ai_review.label_trial(db, trial_id, "disagree", "manager01", note="来源标题其实一致")
    stats = ai_review.stats(db)
    assert stats["labeled"] == 1
    assert stats["disagree"] == 1
    assert stats["errorRate"] == 1.0

    with connect(db) as con:
        row = con.execute("SELECT verdict, labeled_by, note FROM ai_suggestion_trials WHERE id=?",
                          (trial_id,)).fetchone()
    assert row["verdict"] == "disagree"
    assert row["labeled_by"] == "manager01"
    assert row["note"] == "来源标题其实一致"


def test_invalid_verdict_is_refused(db):
    with pytest.raises(ValueError):
        ai_review.label_trial(db, "nope", "maybe", "manager01")
