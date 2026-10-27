"""修「工作台 → 地图」定位断链（GPT/用户都指出的 P0）。

根因：工作台只传 district/year/month，没有 event id；地图页也从不读 URL 参数。
修法：
  * 工作台跳转时带上 event=<id>
  * 地图页挂载时读 ?event=，用 openEvent 同等语义 update({event, detail}) 打开详情，
    再把参数从地址栏去掉，避免刷新重复触发
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

workbench = root / "frontend" / "src" / "pages" / "Workbench" / "index.tsx"
text = workbench.read_text(encoding="utf-8")
old = '    if (event.startDate) {\n      params.set("year", event.startDate.slice(0, 4));'
new = '    // 关键：必须带上活动 id，否则地图无法定位这条活动（用户已指出这个断链）\n    params.set("event", event.id);\n    if (event.startDate) {\n      params.set("year", event.startDate.slice(0, 4));'
if 'params.set("event", event.id)' not in text:
    text = text.replace(old, new, 1)
workbench.write_text(text, encoding="utf-8")
print("  工作台已传 event:", 'params.set("event", event.id)' in text)

map_page = root / "frontend" / "src" / "pages" / "CityEventMap" / "index.tsx"
s = map_page.read_text(encoding="utf-8")
if "URLSearchParams" not in s:
    anchor = "  const { dataset, allEvents, filters, update } = usePlatform();"
    block = anchor + '''

  // 从工作台等页面跳进来时带 ?event=<id>，直接打开该活动详情并定位，
  // 而不是只按月份/地区筛一遍让人自己找（用户已指出这是断链）。
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const eventId = params.get("event");
    if (!eventId) return;
    update({ event: eventId, detail: eventId });
    params.delete("event");
    const next = params.toString();
    window.history.replaceState(null, "", window.location.pathname + (next ? "?" + next : ""));
    // 只在挂载时执行一次：后续改筛选不重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
'''
    s = s.replace(anchor, block, 1)
    map_page.write_text(s, encoding="utf-8")
print("  地图页已读 event 参数:", 'params.get("event")' in map_page.read_text(encoding="utf-8"))
