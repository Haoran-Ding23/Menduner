"""把 B 的三块内容接到商圈洞察页：已收录酒店分布 / 酒店周边活动日历 / 集中度提示。"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

# ---- 类型 ----
api = root / "frontend" / "src" / "services" / "api.ts"
t = api.read_text(encoding="utf-8")
if "hotelDistribution" not in t:
    t = t.replace("""  supplyProfile: MarketSupplyProfile;""",
"""  supplyProfile: MarketSupplyProfile;
  hotelDistribution: {
    count: number;
    bands: { label: string; count: number }[];
    note: string;
  };
  hotelCalendar: {
    name: string;
    distanceMeters: number;
    nearbyActivities: number;
    coveredDays: number;
    weeks: [string, number][];
    topActivities: { name: string; startDate: string; endDate: string | null; source: string | null }[];
  }[];
  concentration: {
    top1Share: number;
    top5Share: number;
    totalMatched: number;
    topVenueShare: number;
    topVenue: string;
    note: string;
  };""")
    api.write_text(t, encoding="utf-8")
print("  api.ts 类型:", "hotelDistribution" in api.read_text(encoding="utf-8"))

# ---- 页面 ----
page = root / "frontend" / "src" / "pages" / "DistrictInsights" / "index.tsx"
s = page.read_text(encoding="utf-8")

old_hotels = """              <div>
                <h4>周边酒店（半径内）</h4>
                {profile.hotels.length === 0 ? (
                  <p className="muted">半径内没有已收录酒店</p>
                ) : (
                  <ul className="plain-list">
                    {profile.hotels.slice(0, 8).map((hotel) => (
                      <li key={hotel.name}>
                        {hotel.name}
                        <span className="muted">
                          {" · "}
                          {hotel.distanceMeters} 米 · {hotel.starLabel ?? "星级未标注"}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>"""

new_hotels = """              <div>
                <h4>已收录酒店分布（半径内）</h4>
                <p className="muted">{profile.hotelDistribution.note}</p>
                <div className="stat-row">
                  <div>
                    <strong>{profile.hotelDistribution.count}</strong>
                    <small>已收录酒店</small>
                  </div>
                  {profile.hotelDistribution.bands.map((band) => (
                    <div key={band.label}>
                      <strong>{band.count}</strong>
                      <small>{band.label}</small>
                    </div>
                  ))}
                </div>
                {profile.hotelCalendar.length > 0 && (
                  <ul className="plain-list">
                    {profile.hotelCalendar.slice(0, 6).map((hotel) => (
                      <li key={hotel.name}>
                        {hotel.name}
                        <span className="muted">
                          {" · "}
                          {hotel.distanceMeters} 米 · 周边活动 {hotel.nearbyActivities} 个 · 覆盖{" "}
                          {hotel.coveredDays} 天
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>"""
if "已收录酒店分布" not in s:
    s = s.replace(old_hotels, new_hotels, 1)

# 日历 + 集中度：加在「窗口内可归属活动」表之前
calendar_block = """            <h4 style={{ marginTop: 16 }}>酒店周边活动日历（供给视角，不是酒店需求）</h4>
            {profile.hotelCalendar.length === 0 ? (
              <p className="muted">半径内没有已收录且有可信坐标的酒店，无法生成日历</p>
            ) : (
              profile.hotelCalendar.slice(0, 3).map((hotel) => (
                <div key={hotel.name} className="calendar-block">
                  <div className="muted">
                    {hotel.name} · {hotel.distanceMeters} 米 · 周边活动 {hotel.nearbyActivities} 个 ·
                    活动覆盖 {hotel.coveredDays} 天
                  </div>
                  {hotel.weeks.length === 0 ? (
                    <p className="muted">当前窗口内没有活动</p>
                  ) : (
                    hotel.weeks.map(([week, count]) => (
                      <div className="bar-row" key={week}>
                        <span>{week}</span>
                        <div className="bar-track">
                          <div
                            className="bar-fill"
                            style={{
                              width:
                                Math.round(
                                  (count / Math.max(1, Math.max(...hotel.weeks.map(([, n]) => n)))) * 100,
                                ) + "%",
                            }}
                          />
                        </div>
                        <strong>{count}</strong>
                      </div>
                    ))
                  )}
                  {hotel.topActivities.length > 0 && (
                    <p className="muted">
                      主要活动：{hotel.topActivities.map((item) => item.name + "（" + item.startDate + "）").join("；")}
                    </p>
                  )}
                </div>
              ))
            )}

            <h4 style={{ marginTop: 16 }}>集中度提示</h4>
            <p className="muted">
              前 1 个商圈占可归属活动的 {Math.round(profile.concentration.top1Share * 100)}%，前 5 个占{" "}
              {Math.round(profile.concentration.top5Share * 100)}%（分母 {profile.concentration.totalMatched} 个可归属活动）；
              单一场馆「{profile.concentration.topVenue}」占本商圈可归属活动的{" "}
              {Math.round(profile.concentration.topVenueShare * 100)}%。
            </p>
            <p className="muted">{profile.concentration.note}</p>

"""
anchor = """            <h4 style={{ marginTop: 16 }}>窗口内可归属活动</h4>"""
if "集中度提示" not in s:
    s = s.replace(anchor, calendar_block + anchor, 1)

page.write_text(s, encoding="utf-8")
print("  酒店分布:", "已收录酒店分布" in s)
print("  活动日历:", "酒店周边活动日历" in s)
print("  集中度:", "集中度提示" in s)
