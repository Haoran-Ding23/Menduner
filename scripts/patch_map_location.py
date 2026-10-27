"""地图居中：把「场馆关联未核验」与「坐标不可用」区分开。

根因（生产实测）：419 条活动里**已核验 0 条**，而 eventCoordinates() 要求
「该活动的 venueId 证据必须是 Verified」，否则返回 null —— 结果对**任何**活动都不定位，
地图定位功能等于关闭。

正确做法（保持诚实但可用）：
  * 坐标本身不可用（缺失 / 非 GCJ-02 / 未核验）→ 确实不能定位；
  * 坐标可用、只是「活动↔场馆」这条关联尚未核验 → **可以给参考位置**，
    但必须标注「场馆关联未核验，位置仅供参考」，不能当成已确认事实。

实现：新增 eventLocation() 返回 {coords, verifiedLink, caveat}；
地图与提示条改用它。eventCoordinates() 保留原语义不动（别的地方仍在用）。
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

# 1) utils/data.ts：加 eventLocation
data = root / "frontend" / "src" / "utils" / "data.ts"
s = data.read_text(encoding="utf-8")
if "export function eventLocation" not in s:
    anchor = "export function eventCoordinates("
    block = '''/**
 * 地图定位用的坐标判定：区分「坐标不可用」与「场馆关联未核验」。
 *
 * eventCoordinates() 会在「活动↔场馆」关联未核验时返回 null（严格语义，其它页面仍在用）。
 * 但定位功能需要更细的区分：坐标本身可用、只是关联待核验时，应给出**参考位置**并标注，
 * 否则 0 条已核验活动会导致地图对任何活动都不定位。
 */
export function eventLocation(
  event: Event,
  data: import("../types").Dataset,
): { coords: Coordinates | null; verifiedLink: boolean; caveat: string | null } {
  const venue = data.venues.find((v) => v.id === event.venueId);
  if (!venue) return { coords: null, verifiedLink: false, caveat: "该活动没有关联场馆" };
  if (!verifiedCoords(venue.coordinates)) {
    return { coords: null, verifiedLink: false, caveat: "该活动场馆坐标缺失或未核验，无法定位" };
  }
  const linkVerified =
    !event.demo &&
    data.evidence.some(
      (item) =>
        item.entityId === event.id &&
        item.field === "venueId" &&
        item.value === event.venueId &&
        effectiveStatus(item) === "Verified",
    );
  return {
    coords: venue.coordinates,
    verifiedLink: linkVerified,
    caveat: linkVerified ? null : "场馆关联尚未核验，地图位置仅供参考",
  };
}

''' + anchor
    s = s.replace(anchor, block, 1)
    data.write_text(s, encoding="utf-8")
print("  eventLocation:", "export function eventLocation" in data.read_text(encoding="utf-8"))

# 2) Map 组件：用 eventLocation 居中，并暴露调试钩子
map_file = root / "frontend" / "src" / "components" / "Map" / "index.tsx"
m = map_file.read_text(encoding="utf-8")
if "eventLocation" not in m:
    m = m.replace("  eventCoordinates,", "  eventCoordinates,\n  eventLocation,", 1)
    old = """    // 关键：在全量数据集里找，避免该活动被当前筛选条件筛掉后无法定位
    const focusEvent =
      dataset.events.find((e) => e.id === selected) ?? events.find((e) => e.id === selected);
    const focus = focusEvent ? eventCoordinates(focusEvent, dataset) : null;
    if (focus && lastFocusedId.current !== selected) {
      lastFocusedId.current = selected;
      map.current.setZoomAndCenter(15, [focus.lng, focus.lat]);
    }"""
    new = """    // 关键：在全量数据集里找，避免该活动被当前筛选条件筛掉后无法定位；
    // 用 eventLocation 区分「坐标不可用」与「场馆关联未核验（给参考位置）」。
    const focusEvent =
      dataset.events.find((e) => e.id === selected) ?? events.find((e) => e.id === selected);
    const located = focusEvent ? eventLocation(focusEvent, dataset) : null;
    if (located?.coords && lastFocusedId.current !== selected) {
      lastFocusedId.current = selected;
      map.current.setZoomAndCenter(15, [located.coords.lng, located.coords.lat]);
      // 便于自动化核验：记录本次定位目标（只读，不改地图行为）
      (window as unknown as Record<string, unknown>).__mapFocus = {
        eventId: selected,
        lng: located.coords.lng,
        lat: located.coords.lat,
        verifiedLink: located.verifiedLink,
        focusedAt: Date.now(),
      };
    }"""
    if old in m:
        m = m.replace(old, new, 1)
    map_file.write_text(m, encoding="utf-8")
print("  Map 使用 eventLocation:", "eventLocation(focusEvent" in map_file.read_text(encoding="utf-8"))
