"""删除自动化验收专用活动及其全部关联数据（可重复执行）。"""
import sys

sys.path.insert(0, "/srv/menduner")
from backend.database import connect


def main(event_id: str) -> int:
    with connect("/srv/menduner/data/menduner.sqlite3") as con:
        row = con.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone()
        if not row:
            print(f"  活动不存在，无需清理: {event_id}")
            return 0
        con.execute("DELETE FROM evidence WHERE event_id=?", (event_id,))
        con.execute("DELETE FROM review_decisions WHERE event_id=?", (event_id,))
        con.execute("DELETE FROM events WHERE id=?", (event_id,))
        con.commit()
    print(f"  已清理测试活动: {event_id}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: cleanup_autotest_event.py <event-id>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
