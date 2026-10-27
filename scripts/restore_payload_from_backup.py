"""从备份恢复被补录代码覆盖的 events.payload，并清理测试写入的证据。

只影响 1 条活动（evt-033324f0d292defe01cb2c4c）：
  - payload 被覆盖成 {"organizer": ...}，导致 /dataset KeyError 'demo'
  - organizer 证据被写成 Verified（测试写入），恢复为 Missing
"""
import json
import sys

sys.path.insert(0, "/srv/menduner")
from backend.database import connect

LIVE = "/srv/menduner/data/menduner.sqlite3"
BACKUP = "/srv/menduner/data/backups/menduner-before-suzhou-hotels-20261026-143134.sqlite3"
EVENT = "evt-033324f0d292defe01cb2c4c"

with connect(BACKUP) as bak:
    row = bak.execute("SELECT payload FROM events WHERE id=?", (EVENT,)).fetchone()
if not row:
    print("  备份里没有这条活动，放弃恢复")
    sys.exit(1)
payload = row["payload"]
data = json.loads(payload)
print("  备份 payload 键:", sorted(data.keys())[:8])

with connect(LIVE) as con:
    con.execute("UPDATE events SET payload=? WHERE id=?", (payload, EVENT))
    con.execute(
        "UPDATE evidence SET value=NULL, verification_status='Missing', payload=? "
        "WHERE event_id=? AND field='organizer'",
        (json.dumps({"status": "Missing"}, ensure_ascii=False), EVENT),
    )
    con.commit()
    restored = con.execute("SELECT payload FROM events WHERE id=?", (EVENT,)).fetchone()["payload"]
    ev = con.execute(
        "SELECT value, verification_status FROM evidence WHERE event_id=? AND field='organizer'", (EVENT,)
    ).fetchone()
print("  恢复后 demo 键存在:", '"demo"' in restored)
print("  organizer 证据:", ev["value"], ev["verification_status"])
