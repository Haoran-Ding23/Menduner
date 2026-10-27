"""回滚测试写入的错误补录：endDate 被写成「苏州交响乐团」。"""
import json
import sys

sys.path.insert(0, "/srv/menduner")
from backend.database import connect

DB = "/srv/menduner/data/menduner.sqlite3"
EVENT = "evt-033324f0d292defe01cb2c4c"

with connect(DB) as con:
    row = con.execute(
        "SELECT id, value FROM evidence WHERE event_id=? AND field='endDate'", (EVENT,)
    ).fetchone()
    print("  回滚前 endDate:", row["value"] if row else None)
    con.execute(
        "UPDATE evidence SET value=NULL, verification_status='Missing', payload=? WHERE id=?",
        (json.dumps({"status": "Missing", "note": "回滚：测试误写入已撤销"}, ensure_ascii=False), row["id"]),
    )
    con.execute("UPDATE events SET endDate=NULL WHERE id=?", (EVENT,))
    con.commit()
    check = con.execute(
        "SELECT value, verification_status FROM evidence WHERE event_id=? AND field='endDate'", (EVENT,)
    ).fetchone()
print("  回滚后:", check["value"], check["verification_status"])
