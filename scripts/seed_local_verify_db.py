"""为本地写入验证准备一个隔离的小数据库（不碰生产）。

内容刻意做出"待处理"状态，好让审核台的 补录/通过/全部核查 都有对象可点：
- 1 个来源；1 个场馆（有坐标）；1 个酒店；
- 2 个活动：一个字段齐全但未核验，一个故意缺 organizer/venueName；
- 每个字段都有 evidence 行（部分 Missing）；
- 1 个企业版账号 menduner / 123456（写入验证要审核身份）。
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / ".local" / "verify.sqlite3"
DB.parent.mkdir(parents=True, exist_ok=True)
if DB.exists():
    DB.unlink()

os.environ["MENDUNER_DB_PATH"] = str(DB)

from backend.database import initialize  # noqa: E402
from backend.accounts import hash_password  # noqa: E402

initialize(DB)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# ---- 来源 ----
con.execute(
    "INSERT INTO sources(id,name,kind,mock,source_url,updated_at) VALUES(?,?,?,?,?,datetime('now'))",
    ("verify-source", "本地验证来源", "venue", 0, "https://example.com/verify"),
)

# ---- 场馆与酒店 ----
# venues/hotels 只有 id + payload：按真实结构写 JSON
import json as _json
con.execute("INSERT INTO venues(id,payload) VALUES(?,?)", ("venue-verify", _json.dumps({
    "id": "venue-verify", "name": "验证用场馆", "address": "苏州市姑苏区验证路 1 号",
    "district": "姑苏区", "longitude": 120.62, "latitude": 31.30,
    "coordinates": [120.62, 31.30], "demo": False,
}, ensure_ascii=False)))
con.execute("INSERT INTO hotels(id,payload) VALUES(?,?)", ("hotel-verify", _json.dumps({
    "id": "hotel-verify", "name": "验证用酒店", "address": "苏州市姑苏区验证路 2 号",
    "longitude": 120.621, "latitude": 31.301, "coordinates": [120.621, 31.301], "demo": False,
}, ensure_ascii=False)))

EVENTS = [
    {
        "id": "evt-verify-full",
        "name": "【本地验证】字段齐全的活动",
        "fields": {"name": "【本地验证】字段齐全的活动", "startDate": "2026-11-05",
                   "endDate": "2026-11-06", "sourceUrl": "https://example.com/verify/full",
                   "venueName": "验证用场馆", "organizer": "验证主办方"},
    },
    {
        "id": "evt-verify-missing",
        "name": "【本地验证】缺字段的活动",
        "fields": {"name": "【本地验证】缺字段的活动", "startDate": "2026-11-08",
                   "endDate": None, "sourceUrl": "https://example.com/verify/missing",
                   "venueName": None, "organizer": None},
    },
]

for event in EVENTS:
    con.execute(
        "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
        "verification_status,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (event["id"], event["name"], "culture", event["fields"]["startDate"],
         event["fields"]["endDate"], None, "姑苏区", "verify-source", "Needs Review",
         json.dumps({"demo": False, "venueId": "venue-verify"}, ensure_ascii=False)),
    )
    for field, value in event["fields"].items():
        status = "Missing" if value is None else "Needs Review"
        evidence_id = f"ev-{event['id']}-{field}"
        payload = {"id": evidence_id, "entityId": event["id"], "field": field, "value": value,
                   "status": status, "sourceUrl": "https://example.com/verify"}
        con.execute(
            "INSERT INTO evidence(id, event_id, entity_id, field, value, source_url, "
            "verification_status, payload) VALUES(?,?,?,?,?,?,?,?)",
            (evidence_id, event["id"], event["id"], field, value, "https://example.com/verify",
             status, json.dumps(payload, ensure_ascii=False)),
        )

# ---- 账号：menduner / 123456（enterprise，长期有效）----
con.execute(
    "INSERT INTO customer_accounts(id, login, name, hotel, password_hash, plan, "
    "trial_ends_at, subscription_ends_at, invite_code, suspended, created_at) "
    "VALUES(?,?,?,?,?,?,?,?,?,0,datetime('now'))",
    ("cus_verify", "menduner", "验证管理员", "验证酒店", hash_password("123456"),
     "enterprise", None, "2036-01-01T00:00:00+00:00", "verify"),
)
con.commit()

counts = {table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
          for table in ("events", "evidence", "venues", "hotels", "sources", "customer_accounts")}
con.close()
print("  本地验证库:", DB)
print("  行数:", json.dumps(counts, ensure_ascii=False))
