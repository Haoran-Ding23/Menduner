"""AI 审核建议（试验用）：AI 只提建议，人来判定对错，结果留档可回溯。

GPT 定的红线在这里落地：
1. AI **绝不写核验状态**——它只往 ai_suggestion_trials 里写"建议值 + 理由 + 置信度"；
2. 建议只覆盖三个关键字段（活动名字 / 活动场地 / 来源链接），不扩散；
3. 每条建议必须带证据（来源 URL 或来源名），没有证据的不生成；
4. 人的判定（对 / 错）必须留痕：labeled_by + labeled_at + verdict，可回溯、可统计误报率；
5. 模型不可用或返回不合规 → 记为 rejected 并说明原因，不静默丢弃、更不伪造建议。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from backend import llm
from backend.database import connect

FIELDS = {
    "name": "活动名字",
    "venueName": "活动场地",
    "sourceUrl": "来源链接",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_suggestion_trials (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    field TEXT NOT NULL,
    current_value TEXT,
    suggested_value TEXT,
    confidence TEXT,
    reason TEXT,
    evidence TEXT,
    model TEXT,
    prompt_version TEXT,
    batch TEXT,
    created_at TEXT,
    verdict TEXT,
    labeled_by TEXT,
    labeled_at TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_trials_event ON ai_suggestion_trials(event_id);
CREATE INDEX IF NOT EXISTS idx_trials_batch ON ai_suggestion_trials(batch);
"""

PROMPT_VERSION = "ai-review-v1"

SYSTEM = """你是数据质检助手，只做"建议"，不做决定。规则：
1. 只针对给定字段给出建议值；如果没有把握，suggestedValue 留空并说明原因；
2. 不得改变任何核验状态，不得声称已核实；
3. 每条建议必须给 confidence（high/medium/low）与一句中文理由；
4. 禁止出现：入住率、RevPAR、营收、消费额、客流预测、最赚钱 等经营预测措辞；
5. 只输出 JSON：
{"items":[{"field":"name","suggestedValue":"...","confidence":"high","reason":"..."}]}"""


def ensure_schema(con) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _candidates(con, limit: int) -> list[dict]:
    """挑选仍有待核对字段的活动（按开始日期从近到远），附带现有值与来源。"""
    rows = con.execute(
        """
        SELECT e.id AS id, e.name AS name, e.venue AS venue, e.startDate AS startDate
        FROM events e
        WHERE EXISTS (
            SELECT 1 FROM evidence ev
            WHERE ev.event_id = e.id
              AND ev.field IN ('name','venueName','sourceUrl')
              AND COALESCE(ev.verification_status,'') <> 'Verified'
        )
        ORDER BY COALESCE(e.startDate,'') DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out = []
    for row in rows:
        source = con.execute(
            "SELECT source_url, field, value FROM evidence WHERE event_id=? "
            "AND field IN ('sourceUrl','venueName','name') ORDER BY field LIMIT 8",
            (row["id"],),
        ).fetchall()
        values = {item["field"]: item["value"] for item in source}
        url = next((item["source_url"] for item in source if item["source_url"]), None)
        venue_name = None
        if row["venue"]:
            venue = con.execute("SELECT payload FROM venues WHERE id=?", (row["venue"],)).fetchone()
            if venue:
                try:
                    venue_name = json.loads(venue["payload"]).get("name")
                except Exception:
                    venue_name = None
        out.append({
            "eventId": row["id"],
            "current": {
                "name": row["name"],
                "venueName": venue_name or values.get("venueName"),
                "sourceUrl": url,
            },
            "sourceUrl": url,
        })
    return out


def _ask_llm(candidate: dict) -> list[dict]:
    message = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps({
            "eventId": candidate["eventId"],
            "字段": FIELDS,
            "当前值": candidate["current"],
            "来源URL": candidate["sourceUrl"],
        }, ensure_ascii=False)},
    ]
    payload = llm.chat_json(message, temperature=0, max_tokens=600)
    items = payload.get("items")
    return items if isinstance(items, list) else []


def generate(db_path, limit: int = 25) -> dict:
    """为 limit 条活动生成建议并入库。不改变任何核验状态。"""
    batch = "ai-review-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    created, rejected = [], []
    if not llm.configured():
        return {"batch": batch, "available": False, "reason": "未配置模型密钥", "created": 0,
                "rows": [], "rejected": []}

    with connect(db_path) as con:
        ensure_schema(con)
        candidates = _candidates(con, limit)
        for candidate in candidates:
            if not candidate["sourceUrl"]:
                rejected.append({"eventId": candidate["eventId"], "reason": "没有来源链接，不生成建议"})
                continue
            try:
                items = _ask_llm(candidate)
            except llm.LLMError as error:
                rejected.append({"eventId": candidate["eventId"], "reason": f"模型不可用：{error}"})
                continue
            for item in items:
                field = str(item.get("field") or "")
                if field not in FIELDS:
                    rejected.append({"eventId": candidate["eventId"], "reason": f"字段不在白名单：{field}"})
                    continue
                suggested = item.get("suggestedValue")
                suggested = "" if suggested is None else str(suggested).strip()
                confidence = str(item.get("confidence") or "").lower()
                if confidence not in {"high", "medium", "low"}:
                    confidence = "low"
                reason = str(item.get("reason") or "").strip()[:300]
                current = str(candidate["current"].get(field) or "")
                if not suggested or suggested == current:
                    continue  # 没有改动就不入库，避免制造噪音
                row = {
                    "id": "tri-" + uuid.uuid4().hex[:12],
                    "eventId": candidate["eventId"],
                    "field": field,
                    "currentValue": current,
                    "suggestedValue": suggested,
                    "confidence": confidence,
                    "reason": reason,
                    "evidence": candidate["sourceUrl"],
                    "model": llm.client_model(),
                    "promptVersion": PROMPT_VERSION,
                    "batch": batch,
                    "createdAt": _now(),
                }
                con.execute(
                    "INSERT INTO ai_suggestion_trials(id,event_id,field,current_value,suggested_value,"
                    "confidence,reason,evidence,model,prompt_version,batch,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (row["id"], row["eventId"], row["field"], row["currentValue"], row["suggestedValue"],
                     row["confidence"], row["reason"], row["evidence"], row["model"],
                     row["promptVersion"], row["batch"], row["createdAt"]),
                )
                created.append(row)
        con.commit()

    return {"batch": batch, "available": True, "reason": None,
            "created": len(created), "rows": created, "rejected": rejected}


def list_trials(db_path, batch: str | None = None, limit: int = 200) -> dict:
    with connect(db_path) as con:
        ensure_schema(con)
        sql = "SELECT * FROM ai_suggestion_trials"
        args: tuple = ()
        if batch:
            sql += " WHERE batch=?"
            args = (batch,)
        sql += " ORDER BY created_at DESC, event_id LIMIT ?"
        args = args + (limit,)
        rows = [dict(row) for row in con.execute(sql, args)]
        batches = [row["batch"] for row in con.execute(
            "SELECT DISTINCT batch FROM ai_suggestion_trials ORDER BY batch DESC LIMIT 10")]
    return {"trials": rows, "batches": batches}


def label_trial(db_path, trial_id: str, verdict: str, reviewer: str, note: str | None = None) -> dict:
    if verdict not in {"agree", "disagree"}:
        raise ValueError("verdict 必须是 agree 或 disagree")
    with connect(db_path) as con:
        ensure_schema(con)
        row = con.execute("SELECT * FROM ai_suggestion_trials WHERE id=?", (trial_id,)).fetchone()
        if not row:
            raise KeyError(trial_id)
        con.execute(
            "UPDATE ai_suggestion_trials SET verdict=?, labeled_by=?, labeled_at=?, note=? WHERE id=?",
            (verdict, reviewer, _now(), note, trial_id),
        )
        con.commit()
    return {"id": trial_id, "verdict": verdict, "reviewer": reviewer}


def stats(db_path) -> dict:
    with connect(db_path) as con:
        ensure_schema(con)
        total = con.execute("SELECT COUNT(*) FROM ai_suggestion_trials").fetchone()[0]
        agree = con.execute("SELECT COUNT(*) FROM ai_suggestion_trials WHERE verdict='agree'").fetchone()[0]
        disagree = con.execute(
            "SELECT COUNT(*) FROM ai_suggestion_trials WHERE verdict='disagree'").fetchone()[0]
        by_field = [dict(row) for row in con.execute(
            "SELECT field, COUNT(*) AS total, "
            "SUM(CASE WHEN verdict='agree' THEN 1 ELSE 0 END) AS agree, "
            "SUM(CASE WHEN verdict='disagree' THEN 1 ELSE 0 END) AS disagree "
            "FROM ai_suggestion_trials GROUP BY field")]
    labeled = agree + disagree
    return {
        "total": total,
        "labeled": labeled,
        "agree": agree,
        "disagree": disagree,
        "errorRate": round(disagree / labeled, 3) if labeled else None,
        "byField": by_field,
        "note": "误差率 = 人判为错的条数 / 已标注条数；未标注不算入分母。",
    }
