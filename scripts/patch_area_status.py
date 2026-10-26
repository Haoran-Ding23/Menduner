"""区分「官方商圈」与「候选商业集聚点」：数据层加 status，页面加标识。

GPT Round 15：候选点不得冒充正式商圈。所以接口必须能区分，页面必须标出来。
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

# ---- 后端 ----
backend = root / "backend" / "market_area.py"
text = backend.read_text(encoding="utf-8")

text = text.replace('''        result.append({
            "id": district["id"],
            "name": district.get("name"),
            "parentId": district.get("parentId"),''',
'''        # official = 政府/地图方确认的名称；candidate = 我们用 POI 聚类得到的候选点
        status = district.get("status") or (
            "official" if center.get("matchLevel") in ("verified", "unverified") else "candidate"
        )
        result.append({
            "id": district["id"],
            "name": district.get("name"),
            "status": status,
            "parentId": district.get("parentId"),''')

text = text.replace('''        "areaVerified": sum(1 for a in result["areas"] if a["quality"] == "verified"),''',
'''        "areaVerified": sum(1 for a in result["areas"] if a["quality"] == "verified"),
        "officialCount": sum(1 for a in result["areas"] if a["status"] == "official"),
        "candidateCount": sum(1 for a in result["areas"] if a["status"] == "candidate"),''')

text = text.replace('''        rows.append({
            "id": area_id,
            "name": area["name"],''',
'''        rows.append({
            "id": area_id,
            "name": area["name"],
            "status": area["status"],''')

text = text.replace('''        "area": {
            "id": area_id, "name": area["name"],''',
'''        "area": {
            "id": area_id, "name": area["name"], "status": area["status"],''')

backend.write_text(text, encoding="utf-8")

# ---- 前端类型 ----
api = root / "frontend" / "src" / "services" / "api.ts"
t = api.read_text(encoding="utf-8")
t = t.replace('''  areaVerified: number;''', '''  areaVerified: number;
  officialCount: number;
  candidateCount: number;''')
t = t.replace('''export interface MarketAreaRow {
  id: string;
  name: string;''', '''export interface MarketAreaRow {
  id: string;
  name: string;
  status: "official" | "candidate";''')
t = t.replace('''  area: {
    id: string;
    name: string;''', '''  area: {
    id: string;
    name: string;
    status: "official" | "candidate";''')
api.write_text(t, encoding="utf-8")

print("  后端 status / coverage 计数 / 前端类型 已改")
