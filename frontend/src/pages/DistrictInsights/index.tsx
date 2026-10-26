import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Select, Space, Table, Tag } from "antd";
import CaliberBar from "../../components/CaliberBar";
import OpportunityAnalysis from "../../components/OpportunityAnalysis";
import ScenarioPanel from "../../components/ScenarioPanel";
import { usePlatform } from "../../hooks/usePlatform";
import { useAccount } from "../../hooks/useEntitlements";
import { categories, monthRange, overlaps } from "../../utils/data";
import { distinctByCanonical } from "../../utils/dedupe";
import {
  loadMarketAreaProfile,
  loadMarketAreas,
  loadMarketCoverage,
  type MarketAreaProfile,
  type MarketAreaRow,
  type MarketCoverage,
} from "../../services/api";

/**
 * 商圈洞察。
 *
 * 这个页面以前叫「商圈洞察」，但内容其实是按行政区统计的 —— 属于产品定位问题（GPT Round 14）。
 * 现在拆成两个口径，并在页面上写清楚：
 *   1. 商圈口径：商圈没有官方边界，只有「中心点 + 半径」，所以一律显示为
 *      **商圈中心点周边活动（估算范围）**；落在多个商圈里的活动保留歧义，不强行归属。
 *   2. 行政区口径：活动本来就挂在行政区上，这是原始归属；两个口径不能相加，也不能互相冒充。
 */
const RADII = [800, 1200, 1500];

export default function DistrictInsights() {
  const { dataset, filters } = usePlatform();
  const { state: accountState } = useAccount();

  const [radius, setRadius] = useState(1200);
  const [coverage, setCoverage] = useState<MarketCoverage | null>(null);
  const [areas, setAreas] = useState<MarketAreaRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [profile, setProfile] = useState<MarketAreaProfile | null>(null);
  const [error, setError] = useState<string | null>(null);

  const monthWindow = useMemo(() => {
    const [start, end] = monthRange(filters.year, filters.month);
    return { start, end };
  }, [filters.year, filters.month]);

  useEffect(() => {
    let alive = true;
    Promise.all([loadMarketCoverage(radius), loadMarketAreas(radius)])
      .then(([nextCoverage, nextAreas]) => {
        if (!alive) return;
        setCoverage(nextCoverage);
        setAreas(nextAreas);
        setSelected((current) => current ?? nextAreas[0]?.id ?? null);
      })
      .catch((reason: Error) => {
        if (alive) setError(reason.message);
      });
    return () => {
      alive = false;
    };
  }, [radius]);

  useEffect(() => {
    if (!selected) return undefined;
    let alive = true;
    loadMarketAreaProfile(selected, { radius, start: monthWindow.start, end: monthWindow.end })
      .then((next) => {
        if (alive) setProfile(next);
      })
      .catch((reason: Error) => {
        if (alive) setError(reason.message);
      });
    return () => {
      alive = false;
    };
  }, [selected, radius, monthWindow.start, monthWindow.end]);

  const adminEvents = useMemo(() => {
    const inWindow = dataset.events.filter((event) => overlaps(event, monthWindow.start, monthWindow.end));
    const distinct = distinctByCanonical(inWindow);
    const byDistrict = new Map<string, number>();
    distinct.forEach((event) => {
      const key = event.districtId ?? "未归属";
      byDistrict.set(key, (byDistrict.get(key) ?? 0) + 1);
    });
    return { distinct, byDistrict };
  }, [dataset.events, monthWindow.start, monthWindow.end]);

  const caliberWindow = {
    kind: "custom" as const, start: monthWindow.start, end: monthWindow.end,
    label: monthWindow.start + " 至 " + monthWindow.end,
  };
  const districtName = (id: string) =>
    dataset.districts.find((district) => district.id === id)?.name ??
    (id === "未归属" ? "未归属" : id);

  const adminRows = [...adminEvents.byDistrict.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([id, count]) => ({ id, name: districtName(id), count }));
  const maxAdmin = adminRows[0]?.count ?? 1;

  const categoryRows = (Object.keys(categories) as (keyof typeof categories)[])
    .map((category) => ({
      category,
      count: adminEvents.distinct.filter((event) => event.category === category).length,
    }))
    .filter((row) => row.count > 0)
    .sort((a, b) => b.count - a.count);
  const maxCategory = categoryRows[0]?.count ?? 1;

  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">商圈与地区</div>
        <h1>商圈洞察</h1>
        <p>先看商圈中心点周边活动（估算范围），再看行政区归属。两个口径分开统计，不能相加。</p>
      </div>

      <Alert
        type="info"
        showIcon
        className="gap-bottom"
        message="商圈没有官方边界，这里的数字是「中心点周边活动（估算范围）」"
        description={
          coverage
            ? coverage.areaCount +
              " 个商圈已补齐中心点（高德 POI 反查，" +
              coverage.areaVerified +
              " 个行政区一致、" +
              coverage.areaLowQuality +
              " 个 POI 名偏弱）；匹配口径为「场馆已核验坐标到商圈中心点的球面距离 ≤ " +
              coverage.radiusMeters +
              " 米」；落在两个以上商圈里的活动保留歧义、不强行归属；未匹配不等于该商圈没有活动。"
            : "正在读取商圈覆盖情况…"
        }
      />

      <CaliberBar window={caliberWindow} events={adminEvents.distinct} />

      <section className="panel gap-bottom" aria-label="商圈覆盖与半径">
        <div className="panel-heading">
          <h3 style={{ margin: 0 }}>商圈数据能力</h3>
          <Space>
            <span className="muted">匹配半径</span>
            <Select
              size="small"
              value={radius}
              onChange={setRadius}
              aria-label="匹配半径"
              options={RADII.map((value) => ({ value, label: value + " 米" }))}
            />
          </Space>
        </div>
        {error && <Alert type="warning" showIcon message={error} />}
        {coverage && (
          <div className="stat-row">
            <div>
              <strong>{coverage.areaCount}</strong>
              <small>有中心点商圈</small>
            </div>
            <div>
              <strong>{coverage.areaVerified}</strong>
              <small>行政区一致</small>
            </div>
            <div>
              <strong>{coverage.venuesWithVerifiedCoords}</strong>
              <small>已核验坐标场馆</small>
            </div>
            <div>
              <strong>{coverage.eventsNearby}</strong>
              <small>周边活动（可归属）</small>
            </div>
            <div>
              <strong>{coverage.eventsAmbiguous}</strong>
              <small>保留歧义</small>
            </div>
            <div>
              <strong>{coverage.eventsUnmatched}</strong>
              <small>未匹配</small>
            </div>
          </div>
        )}
        <p className="muted" style={{ marginTop: 10 }}>
          分母：去重后共 {coverage?.eventsTotal ?? "—"} 个活动身份，
          {coverage?.eventsUnmatched ?? "—"} 个因缺少已核验坐标或不在任何商圈半径内而无法归属。
          切换半径可以看到归属数量的敏感性。
        </p>
      </section>

      <section className="panel gap-bottom" aria-label="单商圈画像">
        <div className="panel-heading">
          <h3 style={{ margin: 0 }}>单商圈画像</h3>
          <Space>
            <Select
              size="small"
              style={{ minWidth: 190 }}
              value={selected ?? undefined}
              onChange={setSelected}
              aria-label="选择商圈"
              placeholder="选择商圈"
              options={areas.map((area) => ({
                value: area.id,
                label: area.name + "（" + (area.parentName ?? "父级未知") + "）",
              }))}
            />
            {profile && profile.area.quality !== "verified" && (
              <Tag>中心点 POI：{profile.area.center.matchedName ?? "未知"}</Tag>
            )}
          </Space>
        </div>

        {!profile ? (
          <p className="muted">请选择商圈</p>
        ) : (
          <>
            <div className="stat-row">
              <div>
                <strong>{profile.coverage.matched}</strong>
                <small>窗口内周边活动</small>
              </div>
              <div>
                <strong>{profile.coverage.ambiguous}</strong>
                <small>窗口内保留歧义</small>
              </div>
              <div>
                <strong>{profile.coverage.matchedAll}</strong>
                <small>全年可归属</small>
              </div>
              <div>
                <strong>{profile.coverage.parentDistrictEvents}</strong>
                <small>父级行政区活动（分母）</small>
              </div>
              <div>
                <strong>{profile.hotels.length}</strong>
                <small>半径内酒店</small>
              </div>
            </div>

            <p className="muted">
              中心点：{profile.area.center.matchedName ?? "—"}（{profile.area.center.adname ?? "—"}）｜坐标系{" "}
              {profile.area.center.system ?? "—"}｜来源 {profile.area.center.source ?? "—"}｜匹配级别{" "}
              {profile.area.center.matchLevel ?? "—"}｜半径 {profile.area.radiusMeters} 米
            </p>

            <div className="two-column">
              <div>
                <h4>品类分布（窗口内）</h4>
                {profile.categories.length === 0 ? (
                  <p className="muted">窗口内没有可归属活动</p>
                ) : (
                  profile.categories.map(([name, count]) => (
                    <div className="bar-row" key={name}>
                      <span>{name}</span>
                      <div className="bar-track">
                        <div
                          className="bar-fill"
                          style={{
                            width:
                              Math.round((count / Math.max(1, profile.categories[0][1])) * 100) + "%",
                          }}
                        />
                      </div>
                      <strong>{count}</strong>
                    </div>
                  ))
                )}
              </div>
              <div>
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
              </div>
            </div>

            <h4 style={{ marginTop: 16 }}>窗口内可归属活动</h4>
            <Table
              size="small"
              pagination={false}
              rowKey="identity"
              dataSource={profile.nearbyEvents}
              locale={{ emptyText: "该商圈在当前窗口内没有可归属活动" }}
              columns={[
                { title: "活动", dataIndex: "name" },
                { title: "类别", dataIndex: "category", width: 110 },
                { title: "开始", dataIndex: "startDate", width: 110 },
                {
                  title: "距离",
                  dataIndex: "distanceMeters",
                  width: 90,
                  render: (value: number) => value + " 米",
                },
              ]}
            />

            <p className="muted" style={{ marginTop: 12 }}>
              {profile.caveat}
            </p>
          </>
        )}
      </section>

      <section className="panel gap-bottom" aria-label="行政区口径">
        <div className="panel-heading">
          <h3 style={{ margin: 0 }}>原始归属：按区县统计（与商圈口径不可相加）</h3>
        </div>
        {adminRows.map((row) => (
          <div className="bar-row" key={row.id}>
            <span>{row.name}</span>
            <div className="bar-track">
              <div
                className="bar-fill"
                style={{ width: Math.round((row.count / maxAdmin) * 100) + "%" }}
              />
            </div>
            <strong>{row.count}</strong>
          </div>
        ))}
        <h4 style={{ marginTop: 16 }}>活动类别分布（按区县）</h4>
        {categoryRows.map((row) => (
          <div className="bar-row" key={row.category}>
            <span>{row.category}</span>
            <div className="bar-track">
              <div
                className="bar-fill"
                style={{ width: Math.round((row.count / maxCategory) * 100) + "%" }}
              />
            </div>
            <strong>{row.count}</strong>
          </div>
        ))}
      </section>

      <OpportunityAnalysis events={adminEvents.distinct} />

      <ScenarioPanel eventName={profile?.nearbyEvents[0]?.name ?? "（请先选择一条活动）"} />

      <section className="panel gap-top" aria-label="导出城市简报">
        <div className="panel-heading">
          <h3 style={{ margin: 0 }}>导出城市简报</h3>
          <small className="muted">五张工作表：概览 / 活动明细 / 本期变化 / 来源证据 / 待确认事项</small>
        </div>
        <Space>
          <Button
            type="primary"
            disabled={!accountState.authenticated}
            onClick={() => {
              const query = new URLSearchParams({ start: monthWindow.start, end: monthWindow.end });
              window.location.assign(
                "/api/reports/city/" +
                  encodeURIComponent(filters.district || "suzhou") +
                  ".xlsx?" +
                  query.toString(),
              );
            }}
          >
            导出城市简报（Excel）
          </Button>
          {!accountState.authenticated && <span className="muted">登录后可导出</span>}
        </Space>
      </section>
    </>
  );
}
