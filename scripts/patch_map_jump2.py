"""带 ?event= 进入地图时，同步切到该活动所属地区与所属月份。

否则会出现：详情打开了「中法文化艺术周」，标题却写着「11月太仓活动」，地图停在太仓/昆山。
"""
from pathlib import Path

page = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "CityEventMap" / "index.tsx"
s = page.read_text(encoding="utf-8")

old = '''    const eventId = params.get("event");
    if (!eventId) return;
    update({ event: eventId, detail: eventId });'''
new = '''    const eventId = params.get("event");
    if (!eventId) return;
    const target = dataset.events.find((item) => item.id === eventId);
    if (target) {
      // 地区与月份必须跟着活动走，否则标题会写成一个不相干的地区
      update({
        event: eventId,
        detail: eventId,
        district: target.districtId ?? null,
        year: Number((target.startDate ?? "").slice(0, 4)) || filters.year,
        month: Number((target.startDate ?? "").slice(5, 7)) || filters.month,
      });
    } else {
      update({ event: eventId, detail: eventId });
    }'''
if "地区与月份必须跟着活动走" not in s:
    s = s.replace(old, new, 1)
    page.write_text(s, encoding="utf-8")
print("  已同步地区与月份:", "地区与月份必须跟着活动走" in page.read_text(encoding="utf-8"))
