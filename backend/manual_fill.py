"""人工补录缺失字段。

规则（与既有审核口径一致）：
1. 只允许补录白名单字段，避免把任意键写进证据表；
2. **必须给来源链接**，没有来源的补录不接受（否则等于凭空造数据）；
3. 补录写入的证据状态为 Verified，但要记录是谁补的、什么时候补的、来源是什么，
   方法标为 manual_entry —— 可追溯，且与"AI 建议"严格区分（AI 永远不写核验状态）；
4. 同一活动同一字段已有记录时，不新增重复行，而是把原记录更新为补录内容并保留历史说明。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from backend.database import connect

# 允许补录的字段（与审核台展示的字段名一致）
FIELD_LABELS = {
    "name": "活动名字",
    "venueName": "活动场地",
    "sourceUrl": "来源链接",
    "startDate": "开始日期",
    "endDate": "结束日期",
    "organizer": "主办方",
    "district": "所属地区",
    "address": "场馆地址",
    "participants": "参与人数",
    "sponsor": "赞助方",
}


class FillError(ValueError):
    """补录被拒绝（字段非法、缺来源等）。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fill(db_path, *, event_id: str, field: str, value: str, source_url: str,
         reviewer: str, note: str | None = None) -> dict:
    if field not in FIELD_LABELS:
        raise FillError(f"字段不在可补录范围：{field}")
    value = (value or "").strip()
    source_url = (source_url or "").strip()
    if not value:
        raise FillError("补录值不能为空")
    if not source_url:
        raise FillError("必须提供来源链接，没有来源的补录不予接受")
    if not reviewer.strip():
        raise FillError("必须记录补录人")
    # 日期字段必须真的是日期：否则会写出 endDate="某乐团" 这种脏数据（真实发生过）
    if field in ("startDate", "endDate"):
        import re

        date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        if not date_pattern.match(value):
            raise FillError("日期字段必须写成 YYYY-MM-DD，例如 2026-11-05")

    payload = {
        "id": None,
        "entityId": event_id,
        "field": field,
        "value": value,
        "status": "Verified",
        "sourceUrl": source_url,
        "sourceName": "人工补录",
        "method": "manual_entry",
        "providedBy": reviewer,
        "updatedAt": _now(),
        "note": note or "",
    }

    with connect(db_path) as con:
        event = con.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone()
        if not event:
            raise KeyError(event_id)

        existing = con.execute(
            "SELECT id FROM evidence WHERE event_id=? AND field=? LIMIT 1", (event_id, field)
        ).fetchone()
        if existing:
            evidence_id = existing["id"]
            previous = con.execute(
                "SELECT verification_status, value FROM evidence WHERE id=?", (evidence_id,)
            ).fetchone()
            payload["id"] = evidence_id
            payload["note"] = (
                (note or "") + f"（覆盖原状态 {previous['verification_status']}，原值 {previous['value']}）"
            ).strip()
            con.execute(
                "UPDATE evidence SET value=?, source_url=?, verification_status='Verified', payload=? "
                "WHERE id=?",
                (value, source_url, json.dumps(payload, ensure_ascii=False), evidence_id),
            )
            action = "updated"
        else:
            evidence_id = "ev-manual-" + uuid.uuid4().hex[:12]
            payload["id"] = evidence_id
            con.execute(
                "INSERT INTO evidence(id, event_id, entity_id, field, value, source_url, "
                "verification_status, payload) VALUES(?,?,?,?,?,?,?,?)",
                (evidence_id, event_id, event_id, field, value, source_url, "Verified",
                 json.dumps(payload, ensure_ascii=False)),
            )
            action = "created"

        # 只回写确实存在的列；绝不覆盖 events.payload
        # （payload 存整条活动的结构化数据，覆盖会让 /dataset 序列化 KeyError，真实踩过）
        column = {"name": "name", "startDate": "startDate", "endDate": "endDate"}.get(field)
        if column:
            try:
                con.execute(f"UPDATE events SET {column}=? WHERE id=?", (value, event_id))
            except Exception:
                pass
        con.commit()

    return {
        "ok": True,
        "action": action,
        "evidenceId": evidence_id,
        "field": field,
        "fieldLabel": FIELD_LABELS[field],
        "value": value,
        "sourceUrl": source_url,
        "reviewer": reviewer,
        "verificationStatus": "Verified",
    }
