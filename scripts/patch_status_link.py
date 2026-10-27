"""12 轮第 11 轮修复：核对字段后，图谱里的关系状态必须跟着变。

问题（实测）：在审核台把 venueName 字段核对通过（POST /api/review 返回 200）之后，
GET /graph/query/event/{id} 的 HELD_AT 边仍然是 Needs Review —— 因为边状态取的是
events.verification_status（整条活动的状态），而字段级核对只改 evidence。

修复：HELD_AT 边的状态优先由该活动「场馆相关字段」的证据决定：
  有 Verified 且无冲突 → Verified；有 Conflicting → Conflicting；否则 Needs Review。
找不到任何场馆字段证据时，退回活动整体状态。
"""
from pathlib import Path

path = Path(__file__).resolve().parent.parent / "backend" / "graph_chain.py"
s = path.read_text(encoding="utf-8")

if "def _venue_link_status" not in s:
    helper = '''
def _venue_link_status(fields: list[dict], fallback: str | None) -> str:
    """活动↔场馆这条关系的状态：以场馆相关字段的证据为准，而不是整条活动的状态。

    字段级核对（POST /api/review）只改 evidence，不会改 events.verification_status；
    如果边状态只看整条活动，核对完页面上仍然是"待核实"，形成假死状态。
    """
    statuses = {_recorded_status(item.get("verification_status")) for item in fields}
    if "Conflicting" in statuses:
        return "Conflicting"
    if statuses == {"Verified"}:
        return "Verified"
    return "Needs Review" if fields else _recorded_status(fallback)

'''
    s = s.replace("def _recorded_status(", helper + "def _recorded_status(", 1)
    # 上面把 helper 插到 _recorded_status 之前；需确保 _recorded_status 已定义后再用（运行时无碍）。

    s = s.replace('''            "verificationStatus": _recorded_status(target["verification_status"]),
            "evidenceRefs": [
                {"table": "events", "recordId": target["id"], "field": "venue",''',
'''            "verificationStatus": _venue_link_status(field_evidence, target["verification_status"]),
            "evidenceRefs": [
                {"table": "events", "recordId": target["id"], "field": "venue",''', 1)

    s = s.replace('''        if _recorded_status(target["verification_status"]) != "Verified":
            warnings.append("活动与场馆的关联来自原始记录，尚未核验（Needs Review），不视为已确认事实")''',
'''        if _venue_link_status(field_evidence, target["verification_status"]) != "Verified":
            warnings.append("活动与场馆的关联来自原始记录，尚未核验（Needs Review），不视为已确认事实")''', 1)

    path.write_text(s, encoding="utf-8")

print("  关系状态改为按字段证据:", "_venue_link_status" in path.read_text(encoding="utf-8"))
