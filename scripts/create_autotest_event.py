"""在数据库里建一条「自动化验收专用」活动，用于验证写入类按钮，验完删除。

为什么需要：审核台的 通过/驳回/补录/全部核查 等按钮会写生产数据，
不能对着真实活动乱点；建一条可回滚的测试活动，既验证了按钮，又不污染业务数据。
"""
import json
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/srv/menduner")
from backend.database import connect

DB = "/srv/menduner/data/menduner.sqlite3"
EVENT_ID = "evt-autotest-" + uuid.uuid4().hex[:8]
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")

with connect(DB) as con:
    source_row = con.execute("SELECT id FROM sources LIMIT 1").fetchone()
    source_id = source_row["id"] if source_row else None
    con.execute(
        "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
        "verification_status,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (EVENT_ID, "【自动化验收】按钮测试活动", "culture", "2026-11-01", None, None, None, source_id,
         "Needs Review", json.dumps({"demo": False, "autoTest": True}, ensure_ascii=False)),
    )
    rows = [
        ("name", "【自动化验收】按钮测试活动", "Needs Review"),
        ("sourceUrl", "https://example.com/autotest", "Unverified"),
        ("venueName", None, "Missing"),
        ("organizer", None, "Missing"),
    ]
    for field, value, status in rows:
        evidence_id = "ev-" + EVENT_ID + "-" + field
        payload = {"id": evidence_id, "entityId": EVENT_ID, "field": field, "value": value,
                   "status": status, "sourceUrl": "https://example.com/autotest"}
        con.execute(
            "INSERT INTO evidence(id, event_id, entity_id, field, value, source_url, "
            "verification_status, payload) VALUES(?,?,?,?,?,?,?,?)",
            (evidence_id, EVENT_ID, EVENT_ID, field, value, "https://example.com/autotest",
             status, json.dumps(payload, ensure_ascii=False)),
        )
    con.commit()

print(EVENT_ID)
