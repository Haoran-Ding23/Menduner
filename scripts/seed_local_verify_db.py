"""为本地写入验证准备一个隔离的小数据库（不碰生产）。

上一轮的失败原因：我手写的 payload 缺字段，/api/dataset 序列化出来是 [null, null]，
审核台拿不到活动 id，补录/通过按钮出不来。

现在改为：复制生产库里一条**真实活动的 payload** 作为结构模板，只替换标识与字段值，
保证数据结构与生产一致。测试数据仍然是假的（名称带「本地验证」），不会混入生产。
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / ".local" / "verify.sqlite3"
TEMPLATE_FILE = ROOT / ".local" / "template-payload.json"
if not TEMPLATE_FILE.exists():
    raise SystemExit("缺少模板文件 .local/template-payload.json（先从生产库导出一条活动 payload）")
TEMPLATE = json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))["payload"]

DB.parent.mkdir(parents=True, exist_ok=True)
if DB.exists():
    DB.unlink()
os.environ["MENDUNER_DB_PATH"] = str(DB)

from backend.accounts import hash_password  # noqa: E402
from backend.database import initialize  # noqa: E402

initialize(DB)
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

con.execute(
    "INSERT INTO sources(id,name,kind,mock,source_url,updated_at) VALUES(?,?,?,?,?,datetime('now'))",
    ("verify-source", "本地验证来源", "venue", 0, "https://example.com/verify"),
)
# events.district 有外键指向 districts：本地库必须先把用到的地区建出来
for district_id, district_name in (("taicang", "太仓市"), ("gusu", "姑苏区")):
    con.execute(
        "INSERT INTO districts(id,payload) VALUES(?,?)",
        (district_id, json.dumps({"id": district_id, "name": district_name, "official": True}, ensure_ascii=False)),
    )

VENUE = {
    "id": "venue-verify", "name": "验证用场馆", "address": "苏州市姑苏区验证路 1 号",
    "district": "姑苏区", "longitude": 120.62, "latitude": 31.30,
    "coordinates": [120.62, 31.30], "demo": False,
}
HOTEL = {
    "id": "hotel-verify", "name": "验证用酒店", "address": "苏州市姑苏区验证路 2 号",
    "longitude": 120.621, "latitude": 31.301, "coordinates": [120.621, 31.301], "demo": False,
}
con.execute("INSERT INTO venues(id,payload) VALUES(?,?)", ("venue-verify", json.dumps(VENUE, ensure_ascii=False)))
con.execute("INSERT INTO hotels(id,payload) VALUES(?,?)", ("hotel-verify", json.dumps(HOTEL, ensure_ascii=False)))

# 两个活动：一个字段齐全，一个故意把 organizer / venueName / endDate 抹掉
VARIANTS = [
    ("evt-verify-full", "【本地验证】字段齐全的活动", False),
    ("evt-verify-missing", "【本地验证】缺字段的活动", True),
]

for event_id, name, drop_fields in VARIANTS:
    payload = json.loads(json.dumps(TEMPLATE))  # 深拷贝模板
    payload.update({
        "id": event_id,
        "name": name,
        "demo": False,
        "sourceUrl": "https://example.com/verify",
        "startDate": "2026-11-05",
        "endDate": "2026-11-06",
        "venueId": "venue-verify",
        "venueName": "验证用场馆",
        "organizer": "验证主办方",
        "districtId": "taicang",
        "category": "culture",
    })
    if drop_fields:
        payload["organizer"] = None
        payload["venueName"] = None
        payload["venueId"] = None
        payload["endDate"] = None

    con.execute(
        "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
        "verification_status,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (event_id, name, "culture", payload["startDate"], payload.get("endDate"),
         None, "taicang", "verify-source", "Needs Review",
         json.dumps(payload, ensure_ascii=False)),
    )
    for field in ("name", "startDate", "endDate", "sourceUrl", "venueName", "organizer"):
        value = payload.get(field)
        status = "Missing" if value in (None, "") else "Needs Review"
        evidence_id = f"ev-{event_id}-{field}"
        evidence_payload = {
            "id": evidence_id, "entityId": event_id, "field": field, "value": value,
            "status": status, "sourceUrl": "https://example.com/verify",
        }
        con.execute(
            "INSERT INTO evidence(id, event_id, entity_id, field, value, source_url, "
            "verification_status, payload) VALUES(?,?,?,?,?,?,?,?)",
            (evidence_id, event_id, event_id, field, value, "https://example.com/verify",
             status, json.dumps(evidence_payload, ensure_ascii=False)),
        )

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
print("  本地验证库已重建:", DB)
print("  行数:", json.dumps(counts, ensure_ascii=False))
print("  模板来源:", TEMPLATE.get("name"))
