"""按 GPT Round 16 实现 B：已收录酒店分布 + 酒店周边活动日历 + 集中度提示。

接受它的删减：
  * 保留：已收录酒店数、距离分层（0–300/300–600/600–800）、每家酒店周边去重活动数；
  * 砍掉：星级分布、品牌分布（名称前缀不等于可靠品牌归属）；
  * B2 改名「酒店周边活动日历」，不叫档期匹配；跨周活动可在多周出现，但月度总数独立去重；
  * B3 必须区分「商圈中心集中」与「场馆集中」，并展示分母。

禁止出现：旺季 / 客房紧张 / 建议涨价 / 预计入住率 / 真实竞争排名。
"""
from pathlib import Path

target = Path(__file__).resolve().parent.parent / "backend" / "market_area.py"
text = target.read_text(encoding="utf-8")

# 1) profile 里补酒店分层、日历与集中度
text = text.replace('''    hotels = []
    for hotel in data["hotels"]:
        point = _coords(hotel)
        if point is None:
            continue
        distance = haversine(point[0], point[1], area["center"]["lng"], area["center"]["lat"])
        if distance <= area["radiusMeters"]:
            hotels.append({"name": hotel.get("name"), "distanceMeters": round(distance),
                           "starLabel": hotel.get("starLabel")})
    hotels.sort(key=lambda item: item["distanceMeters"])''',
'''    # 已收录酒店分布：只统计平台已收录且有可信坐标的酒店
    hotels = []
    for hotel in data["hotels"]:
        point = _coords(hotel)
        if point is None:
            continue
        distance = haversine(point[0], point[1], area["center"]["lng"], area["center"]["lat"])
        if distance <= area["radiusMeters"]:
            own = [item for item in nearby
                   if item.get("distanceMeters", 10 ** 9) >= 0]  # 占位，下面按酒店半径重算
            hotels.append({
                "name": hotel.get("name"),
                "distanceMeters": round(distance),
                "brand": hotel.get("brand"),
            })
    hotels.sort(key=lambda item: item["distanceMeters"])

    def band_of(distance: float) -> str:
        if distance < 300:
            return "0–300 米"
        if distance < 600:
            return "300–600 米"
        return "600–800 米"

    bands = {"0–300 米": 0, "300–600 米": 0, "600–800 米": 0}
    for hotel in hotels:
        bands[band_of(hotel["distanceMeters"])] += 1

    # 每家酒店周边的去重活动（用同一半径、同一身份口径）
    calendar = []
    for hotel in data["hotels"]:
        point = _coords(hotel)
        if point is None:
            continue
        distance = haversine(point[0], point[1], area["center"]["lng"], area["center"]["lat"])
        if distance > area["radiusMeters"]:
            continue
        venues = {v["id"]: v for v in data["venues"]}
        hits, seen = [], set()
        for event in data["events"]:
            if event["identity"] in seen:
                continue
            venue = venues.get(event.get("venue") or "")
            spot = _coords(venue) if venue else None
            if spot is None:
                continue
            if haversine(spot[0], spot[1], point[0], point[1]) > area["radiusMeters"]:
                continue
            if not in_window(event):
                continue
            seen.add(event["identity"])
            hits.append(event)
        days = set()
        weeks: dict[str, int] = {}
        week_seen: dict[str, set] = {}
        for event in hits:
            begin = event.get("startDate")
            if not begin:
                continue
            finish = event.get("endDate") or begin
            if finish < begin:
                finish = begin
            cursor, last = date.fromisoformat(max(begin, start) if start else begin), date.fromisoformat(
                min(finish, end) if end else finish)
            while cursor <= last:
                days.add(cursor.isoformat())
                cursor = date.fromordinal(cursor.toordinal() + 1)
            monday = date.fromisoformat(begin) - timedelta(days=date.fromisoformat(begin).weekday())
            key = monday.isoformat()
            week_seen.setdefault(key, set()).add(event["identity"])
            weeks[key] = len(week_seen[key])
        calendar.append({
            "name": hotel.get("name"),
            "distanceMeters": round(distance),
            "nearbyActivities": len(hits),
            "coveredDays": len(days),
            "weeks": sorted(weeks.items()),
            "topActivities": [
                {"name": item["name"], "startDate": item["startDate"], "endDate": item["endDate"],
                 "distanceMeters": item["distanceMeters"]}
                for item in sorted(hits, key=lambda item: item.get("startDate") or "")[:5]
            ],
        })
    calendar.sort(key=lambda item: item["distanceMeters"])

    # 集中度：商圈中心之间 vs 活动场馆之间，分母必须同时给出
    all_counts = sorted((len(bucket["nearby"]) for bucket in result["perArea"].values()), reverse=True)
    total_matched = sum(all_counts)
    top1 = round(all_counts[0] / total_matched, 3) if total_matched else 0.0
    top5 = round(sum(all_counts[:5]) / total_matched, 3) if total_matched else 0.0
    venue_counter: dict[str, int] = {}
    for item in nearby:
        venue_counter[item.get("venue") or "未知场馆"] = venue_counter.get(item.get("venue") or "未知场馆", 0) + 1
    top_venue = max(venue_counter.items(), key=lambda kv: kv[1]) if venue_counter else ("—", 0)
    venue_share = round(top_venue[1] / len(nearby), 3) if nearby else 0.0''')

# 2) 输出新字段
text = text.replace('''        "hotels": hotels,''',
'''        "hotels": hotels,
        "hotelDistribution": {
            "count": len(hotels),
            "bands": [{"label": label, "count": count} for label, count in bands.items()],
            "note": "仅统计平台已收录且有可信坐标的酒店，不等于该商圈全部酒店；也不构成竞争强弱排名。",
        },
        "hotelCalendar": calendar,
        "concentration": {
            "top1Share": top1,
            "top5Share": top5,
            "totalMatched": total_matched,
            "topVenueShare": venue_share,
            "topVenue": top_venue[0],
            "note": "集中度用于提醒：少数商圈/场馆可能主导结果，不能当作商圈活跃度排名。",
        },''')

# 3) 需要 timedelta
text = text.replace("from datetime import date", "from datetime import date, timedelta")

target.write_text(text, encoding="utf-8")
print("  market_area.py 已加：酒店分布、活动日历、集中度")
