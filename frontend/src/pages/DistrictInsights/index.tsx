import { useEffect, useMemo, useState } from "react";
import { Button, Collapse, Select, Space, Table, Tag } from "antd";
import type { EChartsOption } from "echarts";
import Chart from "../../components/Charts";
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
 * 商圈洞察（GPT Round 17 重构版）。
 *
 * 视觉层级：先图、后数、再说明。
 *   首屏：KPI + 归属构成 100% 堆叠条 ｜ Top10 中心排行 ｜ 半径敏感性 ｜ 选中中心周度预览
 *   画像：类别构成、周度活动分布、酒店距离结构 三个真实 ECharts 图
 *   底层：明细表与「更多分析」折叠区
 *
 * 口径（不删，但不占首屏）：800m 中心点近邻，不是正式商圈边界；落在多个中心里的活动保留歧义；
 * 未匹配不等于该商圈没有活动。完整说明放在底部折叠区。
 */
const RADII = [800, 1200, 1500];
const DEFAULT_RADIUS = 800;
const BLUE = "#2563EB";
const TEAL = "#0F766E";
const ORANGE = "#D97706";
const GREY = "#CBD5E1";

export default function DistrictInsights() {
  const { dataset, filters } = usePlatform();
  const { state: accountState } = useAccount();

  const [radius, setRadius] = useState(DEFAULT_RADIUS);
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
      .catch((reason: Error) => alive && setError(reason.message));
    return () => {
      alive = false;
    };
  }, [radius]);

  useEffect(() => {
    if (!selected) return undefined;
    let alive = true;
    loadMarketAreaProfile(selected, { radius, start: monthWindow.start, end: monthWindow.end })
      .then((next) => alive && setProfile(next))
      .catch((reason: Error) => alive && setError(reason.message));
    return () => {
      alive = false;
    };
  }, [selected, radius, monthWindow.start, monthWindow.end]);

  const adminEvents = useMemo(() => {
    const inWindow = dataset.events.filter((event) =>
      overlaps(event, monthWindow.start, monthWindow.end),
    );
    const distinct = distinctByCanonical(inWindow);
    const byDistrict = new Map<string, number>();
    distinct.forEach((event) => {
      const key = event.districtId ?? "未归属";
      byDistrict.set(key, (byDistrict.get(key) ?? 0) + 1);
    });
    return { distinct, byDistrict };
  }, [dataset.events, monthWindow.start, monthWindow.end]);

  const caliberWindow = {
    kind: "custom" as const,
    start: monthWindow.start,
    end: monthWindow.end,
    label: monthWindow.start + " 至 " + monthWindow.end,
  };

  const districtName = (id: string) =>
    dataset.districts.find((district) => district.id === id)?.name ??
    (id === "未归属" ? "未归属" : id);
  const adminRows = [...adminEvents.byDistrict.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([id, count]) => ({ id, name: districtName(id), count }));

  // ---------- 图 1：归属构成（100% 堆叠） ----------
  const compositionOption = useMemo<EChartsOption>(() => {
    if (!coverage) return {};
    const total = Math.max(
      1,
      coverage.eventsNearby + coverage.eventsAmbiguous + coverage.eventsUnmatched,
    );
    return {
      grid: { left: 8, right: 8, top: 28, bottom: 8, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { top: 0, left: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11 } },
      xAxis: { type: "value", max: total, show: false },
      yAxis: { type: "category", data: ["活动归属"], show: false },
      series: [
        {
          name: "唯一近邻",
          type: "bar",
          stack: "total",
          barWidth: 38,
          itemStyle: { color: BLUE },
          label: { show: true, color: "#fff", fontSize: 11 },
          data: [coverage.eventsNearby],
        },
        {
          name: "保留歧义",
          type: "bar",
          stack: "total",
          itemStyle: { color: ORANGE },
          label: { show: true, color: "#fff", fontSize: 11 },
          data: [coverage.eventsAmbiguous],
        },
        {
          name: "未匹配",
          type: "bar",
          stack: "total",
          itemStyle: { color: GREY },
          label: { show: true, color: "#334155", fontSize: 11 },
          data: [coverage.eventsUnmatched],
        },
      ],
    };
  }, [coverage]);

  // ---------- 图 2：Top10 中心排行 ----------
  const topAreas = useMemo(
    () => [...areas].sort((a, b) => b.nearbyEvents - a.nearbyEvents).slice(0, 10).reverse(),
    [areas],
  );
  const rankingOption = useMemo<EChartsOption>(
    () => ({
      grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: { type: "value", splitLine: { lineStyle: { color: "#F1F5F9" } } },
      yAxis: {
        type: "category",
        data: topAreas.map((area) => (area.status === "candidate" ? "·" + area.name : area.name)),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { fontSize: 11 },
      },
      series: [
        {
          type: "bar",
          barWidth: 12,
          itemStyle: {
            color: (params: { dataIndex: number }) =>
              topAreas[params.dataIndex]?.status === "candidate" ? TEAL : BLUE,
            borderRadius: [0, 3, 3, 0],
          },
          label: { show: true, position: "right", fontSize: 11, color: "#475569" },
          data: topAreas.map((area) => area.nearbyEvents),
        },
      ],
    }),
    [topAreas],
  );

  // ---------- 图 3：半径敏感性 ----------
  const sensitivityOption = useMemo<EChartsOption>(() => {
    const rows = coverage?.comparisons ?? [];
    return {
      grid: { left: 8, right: 24, top: 28, bottom: 8, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { top: 0, left: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11 } },
      xAxis: { type: "value", splitLine: { lineStyle: { color: "#F1F5F9" } } },
      yAxis: {
        type: "category",
        data: rows.map((row) => row.radiusMeters + "m"),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { fontSize: 11 },
      },
      series: [
        {
          name: "唯一近邻",
          type: "bar",
          stack: "r",
          itemStyle: { color: BLUE },
          data: rows.map((row) => row.uniqueNear),
        },
        {
          name: "保留歧义",
          type: "bar",
          stack: "r",
          itemStyle: { color: ORANGE },
          data: rows.map((row) => row.ambiguous),
        },
        {
          name: "未匹配",
          type: "bar",
          stack: "r",
          itemStyle: { color: GREY },
          data: rows.map((row) => row.unmatched),
        },
      ],
    };
  }, [coverage]);

  // ---------- 图 4：选中中心周度预览 ----------
  const weeklyOption = useMemo<EChartsOption>(() => {
    const weekly = profile?.weekly ?? [];
    return {
      grid: { left: 8, right: 12, top: 12, bottom: 8, containLabel: true },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: weekly.map((row) => row.weekStart.slice(5)),
        axisLabel: { fontSize: 10, interval: 0, rotate: 0, margin: 10 },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#E2E8F0" } },
      },
      yAxis: { type: "value", splitLine: { lineStyle: { color: "#F1F5F9" } }, axisLabel: { fontSize: 10 } },
      series: [
        {
          type: "bar",
          barWidth: 14,
          itemStyle: { color: BLUE, borderRadius: [3, 3, 0, 0] },
          data: weekly.map((row) => row.count),
        },
      ],
    };
  }, [profile]);

  // ---------- 画像图：类别 / 酒店距离结构 ----------
  const categoryOption = useMemo<EChartsOption>(() => {
    const rows = [...(profile?.categories ?? [])].slice(0, 8).reverse();
    return {
      grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: { type: "value", splitLine: { lineStyle: { color: "#F1F5F9" } } },
      yAxis: {
        type: "category",
        data: rows.map(([name]) => (categories as Record<string, { label: string }>)[name]?.label ?? name),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { fontSize: 11 },
      },
      series: [
        {
          type: "bar",
          barWidth: 12,
          itemStyle: { color: TEAL, borderRadius: [0, 3, 3, 0] },
          label: { show: true, position: "right", fontSize: 11, color: "#475569" },
          data: rows.map(([, count]) => count),
        },
      ],
    };
  }, [profile]);

  const hotelBandOption = useMemo<EChartsOption>(() => {
    const bands = profile?.hotelDistribution.bands ?? [];
    return {
      grid: { left: 8, right: 12, top: 12, bottom: 8, containLabel: true },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: bands.map((band) => band.label),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#E2E8F0" } },
        axisLabel: { fontSize: 10 },
      },
      yAxis: { type: "value", splitLine: { lineStyle: { color: "#F1F5F9" } }, axisLabel: { fontSize: 10 } },
      series: [
        {
          type: "bar",
          barWidth: 38,
          itemStyle: { color: TEAL, borderRadius: [3, 3, 0, 0] },
          data: bands.map((band) => band.count),
        },
      ],
    };
  }, [profile]);

  const kpi = [
    { label: "分析中心", value: coverage?.areaCount ?? "—" },
    { label: "唯一近邻", value: coverage?.eventsNearby ?? "—" },
    { label: "歧义", value: coverage?.eventsAmbiguous ?? "—" },
    { label: "未匹配", value: coverage?.eventsUnmatched ?? "—" },
  ];

  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">商圈与地区</div>
        <h1>商圈洞察</h1>
        <p className="insight-sub">
          {radius}m 中心点近邻 · 非正式商圈边界
          <Space size={6} style={{ marginLeft: 8 }}>
            <Select
              size="small"
              value={radius}
              onChange={setRadius}
              aria-label="匹配半径"
              options={RADII.map((value) => ({ value, label: value + " 米" }))}
            />
          </Space>
        </p>
      </div>

      {error && <p className="muted">数据加载失败：{error}</p>}

      {/* ① 总览 */}
      <section className="insight-grid" aria-label="商圈总览">
        <div className="panel">
          <div className="panel-heading">
            <h3 style={{ margin: 0 }}>活动归属构成</h3>
            <small className="muted">分母 {coverage?.identitiesTotal ?? "—"} 个去重活动身份</small>
          </div>
          <div className="kpi-row">
            {kpi.map((item) => (
              <div key={item.label}>
                <strong>{item.value}</strong>
                <small>{item.label}</small>
              </div>
            ))}
          </div>
          <div className="chart-sm">
            <Chart option={compositionOption} />
          </div>
        </div>

        {/* ② 中心点分布 */}
        <div className="panel">
          <div className="panel-heading">
            <h3 style={{ margin: 0 }}>中心点近邻活动 Top 10</h3>
            <small className="muted">蓝=官方商圈 · 青=候选集聚点 · 点击切换画像</small>
          </div>
          <div className="chart-md">
            <Chart option={rankingOption} onClick={(name: string) => {
              const target = areas.find(
                (area) => area.name === name || "·" + area.name === name,
              );
              if (target) setSelected(target.id);
            }} />
          </div>
        </div>
      </section>

      {/* ③ 半径敏感性 + ④ 周度预览 */}
      <section className="insight-grid" aria-label="半径敏感性与周度预览">
        <div className="panel">
          <div className="panel-heading">
            <h3 style={{ margin: 0 }}>半径敏感性</h3>
            <small className="muted">同一份数据只改半径，看归属如何变化</small>
          </div>
          <div className="chart-sm">
            <Chart option={sensitivityOption} />
          </div>
        </div>
        <div className="panel">
          <div className="panel-heading">
            <h3 style={{ margin: 0 }}>选中中心 · 周度活动预览</h3>
            <Space>
              <Select
                size="small"
                style={{ minWidth: 200 }}
                value={selected ?? undefined}
                onChange={setSelected}
                aria-label="选择商圈"
                options={areas.map((area) => ({
                  value: area.id,
                  label:
                    (area.status === "candidate" ? "[候选] " : "") +
                    area.name +
                    "（" + (area.parentName ?? "父级未知") + "）",
                }))}
              />
              {profile?.area.status === "candidate" && <Tag>候选</Tag>}
            </Space>
          </div>
          <div className="chart-sm">
            <Chart option={weeklyOption} />
          </div>
          <p className="muted">
            各周为「与该周相交的去重活动数」，跨周可重复，不能相加当作月度总量。
          </p>
        </div>
      </section>

      {/* 单商圈画像 */}
      <section className="panel gap-bottom" aria-label="单商圈画像">
        <div className="panel-heading">
          <h3 style={{ margin: 0 }}>
            {profile?.area.name ?? "—"}
            <span className="muted" style={{ fontWeight: 400, marginLeft: 8 }}>
              {profile?.area.parentName ?? ""} · {profile?.area.center.matchedName ?? ""}（
              {profile?.area.center.adname ?? ""}）· 半径 {profile?.area.radiusMeters ?? "—"} 米
            </span>
          </h3>
        </div>

        {!profile ? (
          <p className="muted">加载中…</p>
        ) : (
          <>
            <div className="kpi-row">
              <div>
                <strong>{profile.coverage.matched}</strong>
                <small>窗口内可归属活动</small>
              </div>
              <div>
                <strong>{profile.coverage.ambiguous}</strong>
                <small>保留歧义</small>
              </div>
              <div>
                <strong>{profile.supplyProfile.coveredDays}</strong>
                <small>活动覆盖天数</small>
              </div>
              <div>
                <strong>{profile.supplyProfile.venues}</strong>
                <small>关联场馆</small>
              </div>
              <div>
                <strong>{Math.round(profile.supplyProfile.spatialMatchRate * 100)}%</strong>
                <small>空间匹配率</small>
              </div>
              <div>
                <strong>{profile.hotelDistribution.count}</strong>
                <small>半径内已收录酒店</small>
              </div>
            </div>

            <div className="insight-grid">
              <div>
                <h4>活动类别构成</h4>
                <div className="chart-sm">
                  <Chart option={categoryOption} />
                </div>
              </div>
              <div>
                <h4>周边酒店距离结构</h4>
                <div className="chart-sm">
                  <Chart option={hotelBandOption} />
                </div>
              </div>
            </div>

            <Collapse
              ghost
              items={[
                {
                  key: "activities",
                  label: "窗口内可归属活动（" + profile.nearbyEvents.length + "）",
                  children: (
                    <Table
                      size="small"
                      pagination={false}
                      rowKey="identity"
                      dataSource={profile.nearbyEvents}
                      columns={[
                        { title: "活动", dataIndex: "name" },
                        { title: "类别", dataIndex: "category", width: 110 },
                        { title: "开始", dataIndex: "startDate", width: 100 },
                        {
                          title: "距离",
                          dataIndex: "distanceMeters",
                          width: 90,
                          render: (value: number) => value + " 米",
                        },
                      ]}
                    />
                  ),
                },
                {
                  key: "hotels",
                  label: "周边已收录酒店（" + profile.hotelCalendar.length + "）",
                  children: (
                    <Table
                      size="small"
                      pagination={false}
                      rowKey="name"
                      dataSource={profile.hotelCalendar}
                      columns={[
                        { title: "酒店", dataIndex: "name" },
                        {
                          title: "距中心",
                          dataIndex: "distanceMeters",
                          width: 100,
                          render: (value: number) => value + " 米",
                        },
                        { title: "周边活动", dataIndex: "nearbyActivities", width: 100 },
                        { title: "覆盖天数", dataIndex: "coveredDays", width: 100 },
                      ]}
                    />
                  ),
                },
                {
                  key: "method",
                  label: "统计口径与限制",
                  children: (
                    <div className="method-text">
                      <p>{profile.coverage.method}。</p>
                      <p>{profile.caveat}</p>
                      <p>
                        前 1 个中心占可归属活动{" "}
                        {Math.round(profile.concentration.top1Share * 100)}%，前 5 个占{" "}
                        {Math.round(profile.concentration.top5Share * 100)}%（分母{" "}
                        {profile.concentration.totalMatched}）；单一场馆「
                        {profile.concentration.topVenue}」占本中心{" "}
                        {Math.round(profile.concentration.topVenueShare * 100)}%。
                      </p>
                      <p>{profile.concentration.note}</p>
                      <p>
                        共 {coverage?.officialCount ?? "—"} 个官方商圈与{" "}
                        {coverage?.candidateCount ?? "—"} 个候选集聚点；候选点由 POI 聚类得到，
                        未经政府或地图方确认为正式商圈。
                      </p>
                    </div>
                  ),
                },
              ]}
            />
          </>
        )}
      </section>

      <CaliberBar window={caliberWindow} events={adminEvents.distinct} />

      <Collapse
        ghost
        items={[
          {
            key: "more",
            label: "更多分析（按区县统计、地区资源比较、经济情景、导出简报）",
            children: (
              <>
                <section className="panel gap-bottom" aria-label="按区县统计">
                  <div className="panel-heading">
                    <h3 style={{ margin: 0 }}>原始归属：按区县统计</h3>
                    <small className="muted">与商圈口径不可相加</small>
                  </div>
                  <div className="chart-sm">
                    <Chart
                      option={{
                        grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
                        tooltip: { trigger: "axis" },
                        xAxis: { type: "value", splitLine: { lineStyle: { color: "#F1F5F9" } } },
                        yAxis: {
                          type: "category",
                          data: adminRows.map((row) => row.name).reverse(),
                          axisLine: { show: false },
                          axisTick: { show: false },
                          axisLabel: { fontSize: 11 },
                        },
                        series: [
                          {
                            type: "bar",
                            barWidth: 12,
                            itemStyle: { color: GREY, borderRadius: [0, 3, 3, 0] },
                            label: { show: true, position: "right", fontSize: 11, color: "#475569" },
                            data: adminRows.map((row) => row.count).reverse(),
                          },
                        ],
                      } as EChartsOption}
                    />
                  </div>
                </section>

                <OpportunityAnalysis events={adminEvents.distinct} />
                <ScenarioPanel
                  eventName={profile?.nearbyEvents[0]?.name ?? "（请先选择一条活动）"}
                />

                <section className="panel gap-top" aria-label="导出城市简报">
                  <div className="panel-heading">
                    <h3 style={{ margin: 0 }}>导出城市简报</h3>
                    <small className="muted">
                      五张工作表：概览 / 活动明细 / 本期变化 / 来源证据 / 待确认事项
                    </small>
                  </div>
                  <Space>
                    <Button
                      type="primary"
                      disabled={!accountState.authenticated}
                      onClick={() => {
                        const query = new URLSearchParams({
                          start: monthWindow.start,
                          end: monthWindow.end,
                        });
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
            ),
          },
        ]}
      />
    </>
  );
}
