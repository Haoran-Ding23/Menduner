"""按 GPT Round 15 落地：默认 800m「近邻分析范围」、三档半径对照、商圈供给画像指标。

GPT 的硬要求：
  * 800m 只能叫「近邻分析范围」，不是经过真实商圈边界验证的最优半径；
  * 页面必须同时显示 416 身份 / 370 可用坐标 / 61 唯一近邻 / 2 歧义 / 353 未匹配，
    并给出 1200m 与 1500m 的对照；
  * 新增中心点后必须重新测算，不得沿用旧结果；
  * 不批准「商圈总消费额」，替代指标是「商圈周边活动供给画像」。
"""
from pathlib import Path

target = Path(__file__).resolve().parent.parent / "backend" / "market_area.py"
text = target.read_text(encoding="utf-8")

text = text.replace("DEFAULT_RADIUS = 1200", "DEFAULT_RADIUS = 800\nCOMPARISON_RADII = (800, 1200, 1500)")

# coverage：补可用坐标数、唯一近邻、三档对照
text = text.replace('''def coverage(db_path, radius: int = DEFAULT_RADIUS) -> dict:
    data = load(db_path)
    result = assign(data, radius)
    venues_with_coords = sum(1 for v in data["venues"] if _coords(v))
    total_identities = len({e["identity"] for e in data["events"]})
    return {
        "radiusMeters": radius,''',
'''def usable_coord_identities(data: dict) -> int:
    """有多少去重身份的活动拿到了可用场馆坐标（Verified + GCJ-02）。"""
    venues = {v["id"]: v for v in data["venues"]}
    seen = set()
    for event in data["events"]:
        venue = venues.get(event.get("venue") or "")
        if venue and _coords(venue):
            seen.add(event["identity"])
    return len(seen)


def coverage(db_path, radius: int = DEFAULT_RADIUS) -> dict:
    data = load(db_path)
    result = assign(data, radius)
    venues_with_coords = sum(1 for v in data["venues"] if _coords(v))
    total_identities = len({e["identity"] for e in data["events"]})
    comparisons = []
    for value in COMPARISON_RADII:
        other = result if value == radius else assign(data, value)
        comparisons.append({
            "radiusMeters": value,
            "uniqueNear": other["counts"]["nearby"],
            "ambiguous": other["counts"]["ambiguous"],
            "unmatched": other["counts"]["none"],
        })
    return {
        "radiusMeters": radius,
        "radiusLabel": "近邻分析范围（未经验证的商圈边界）",
        "identitiesTotal": total_identities,
        "coordsUsable": usable_coord_identities(data),
        "comparisons": comparisons,''')

# profile：供给画像指标
text = text.replace('''    parent_events = sum(1 for e in data["events"] if e["district"] == area["parentId"])
    return {''',
'''    parent_events = sum(1 for e in data["events"] if e["district"] == area["parentId"])

    # 供给画像：只描述「我们观测到的活动供给」，不叫消费、不叫经济贡献
    covered_days = 0
    for item in nearby:
        begin = item.get("startDate")
        if not begin:
            continue
        finish = item.get("endDate") or begin
        if finish < begin:
            finish = begin
        if start and begin < start:
            begin = start
        if end and finish > end:
            finish = end
        try:
            covered_days += max(0, (date.fromisoformat(finish) - date.fromisoformat(begin)).days + 1)
        except ValueError:
            continue
    venue_ids = {item.get("venue") for item in nearby if item.get("venue")}
    with_source_url = 0
    if nearby:
        with connect(db_path) as con:
            source_rows = {row[0]: row[1] for row in con.execute("SELECT id, source_url FROM sources")}
        for item in nearby:
            if source_rows.get(item.get("source")):
                with_source_url += 1

    return {''')

text = text.replace('''        "categories": sorted(categories.items(), key=lambda kv: -kv[1]),''',
'''        "supplyProfile": {
            "uniqueActivities": len(nearby),
            "coveredDays": covered_days,
            "venues": len(venue_ids),
            "sourceCoverageRate": round(with_source_url / len(nearby), 3) if nearby else 0.0,
            "spatialMatchRate": round(len(nearby) / parent_events, 3) if parent_events else 0.0,
            "ambiguityRate": round(len(ambiguous) / (len(nearby) + len(ambiguous)), 3)
            if (nearby or ambiguous) else 0.0,
            "note": "供给画像只描述我们观测到的活动供给，不代表消费额、客流或经济贡献。",
        },
        "categories": sorted(categories.items(), key=lambda kv: -kv[1]),''')

# profile 里的项目需要 source 与 venue 字段
text = text.replace('''            per_area[hit["id"]][bucket].append({
                "identity": event["identity"], "name": event["name"], "category": event["category"],
                "startDate": event["startDate"], "endDate": event["endDate"],
                "district": event["district"], "distanceMeters": hit["distanceMeters"],
            })''',
'''            per_area[hit["id"]][bucket].append({
                "identity": event["identity"], "name": event["name"], "category": event["category"],
                "startDate": event["startDate"], "endDate": event["endDate"],
                "district": event["district"], "distanceMeters": hit["distanceMeters"],
                "venue": event["venue"], "source": event["source"],
            })''')

# events 查询需要 source 列
text = text.replace('''            f"SELECT id, {canonical} AS identity, name, category, startDate, endDate, venue, "
            "district FROM events")]''',
'''            f"SELECT id, {canonical} AS identity, name, category, startDate, endDate, venue, "
            "district, source FROM events")]''')

target.write_text(text, encoding="utf-8")
print("  market_area.py 已更新：默认 800m、三档对照、供给画像")
