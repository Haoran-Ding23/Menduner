import { useEffect, useMemo, useState } from "react";
import { Button, Collapse, Select, Space, Table, Tag, Tooltip } from "antd";
import type { EChartsOption } from "echarts";
import Chart from "../../components/Charts";
import AiMarketCard from "../../components/AiMarketCard";
import EmptyHint from "../../components/EmptyHint";
import MarketAreaMap from "../../components/MarketAreaMap";
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
 * 商圈洞察（Round 17/18 重构）。
 *
 * 阅读主线（GPT Round 18）：整体分布 → 选择中心 → 活动趋势 → 业务明细。
 *   ① 页面标题 + 4 个 KPI
 *   ② 中心 Top 10（主图 60%）｜活动归属构成环形图（辅助 40%）
 *   ③ 选中中心标题 + 关键指标
 *   ④ 周度趋势（60%）｜活动类别（40%）
 *   ⑤ 酒店摘要 → 活动明细 → 分析口径（折叠）
 *
 * 口径不删但不出现在首屏：800m 中心点近邻，不是正式商圈边界；多中心命中保留歧义；
 * 未匹配不等于该商圈没有活动。
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

  const total = Math.max(
    1,
    (coverage?.eventsNearby ?? 0) + (coverage?.eventsAmbiguous ?? 0) + (coverage?.eventsUnmatched ?? 0),
  );
  const nearbyShare = Math.round(((coverage?.eventsNearby ?? 0) / total) * 1000) / 10;

  // ② 左：Top10 主图
  const topAreas = useMemo(
    () => [...areas].sort((a, b) => b.nearbyEvents - a.nearbyEvents).slice(0, 10).reverse(),
    [areas],
  );
  const rankingOption = useMemo<EChartsOption>(
    () => ({
      grid: { left: 8, right: 40, top: 8, bottom: 8, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: { type: "value", splitLine: { lineStyle: { color: "#E9EEF5" } }, axisLabel: { color: "#94A3B8", fontSize: 11 } },
      yAxis: {
        type: "category",
        data: topAreas.map((area) => (area.status === "candidate" ? "·" + area.name : area.name)),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { fontSize: 12, color: "#475569" },
      },
      series: [
        {
          type: "bar",
          barWidth: 16,
          itemStyle: {
            color: (params: { dataIndex: number }) =>
              topAreas[params.dataIndex]?.status === "candidate" ? TEAL : BLUE,
            borderRadius: [0, 4, 4, 0],
          },
          label: { show: true, position: "right", fontSize: 12, color: "#334155" },
          data: topAreas.map((area) => area.nearbyEvents),
        },
      ],
    }),
    [topAreas],
  );

  // ② 右：归属构成环形图
  const compositionOption = useMemo<EChartsOption>(
    () => ({
      tooltip: { trigger: "item", formatter: "{b}：{c}（{d}%）" },
      legend: {
        orient: "vertical",
        right: 4,
        top: "center",
        itemWidth: 10,
        itemHeight: 10,
        textStyle: { fontSize: 12, color: "#475569" },
      },
      series: [
        {
          type: "pie",
          radius: ["58%", "78%"],
          center: ["32%", "50%"],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: "#fff", borderWidth: 2 },
          label: {
            show: true,
            position: "center",
            formatter: nearbyShare + "%",
            fontSize: 22,
            fontWeight: 700,
            color: "#0f172a",
          },
          emphasis: { label: { show: true, fontSize: 22, fontWeight: 700 } },
          data: [
            { value: coverage?.eventsNearby ?? 0, name: "唯一近邻", itemStyle: { color: BLUE } },
            { value: coverage?.eventsAmbiguous ?? 0, name: "保留歧义", itemStyle: { color: ORANGE } },
            { value: coverage?.eventsUnmatched ?? 0, name: "未匹配", itemStyle: { color: GREY } },
          ],
        },
      ],
    }),
    [coverage, nearbyShare],
  );

  // ④ 左：周度趋势（GPT Round 18 指定参数）
  const weeklyOption = useMemo<EChartsOption>(
    () => ({
      grid: { left: 40, right: 20, top: 36, bottom: 32, containLabel: true },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: (profile?.weekly ?? []).map((row) => row.weekStart.slice(5)),
        axisTick: { show: false },
        axisLine: { show: false },
        axisLabel: { fontSize: 12, color: "#64748B" },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        axisLine: { show: false },
        axisLabel: { fontSize: 11, color: "#94A3B8" },
        splitLine: { lineStyle: { color: "#E9EEF5" } },
      },
      series: [
        {
          type: "bar",
          barWidth: 36,
          itemStyle: { color: BLUE, borderRadius: [5, 5, 0, 0] },
          label: { show: true, position: "top", fontSize: 12, color: "#334155" },
          data: (profile?.weekly ?? []).map((row) => row.count),
        },
      ],
    }),
    [profile],
  );

  // ④ 右：活动类别
  const categoryOption = useMemo<EChartsOption>(() => {
    const rows = [...(profile?.categories ?? [])].slice(0, 8).reverse();
    return {
      grid: { left: 8, right: 40, top: 8, bottom: 8, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: { type: "value", minInterval: 1, splitLine: { lineStyle: { color: "#E9EEF5" } }, axisLabel: { color: "#94A3B8", fontSize: 11 } },
      yAxis: {
        type: "category",
        data: rows.map(
          ([name]) => (categories as Record<string, { label: string }>)[name]?.label ?? name,
        ),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { fontSize: 12, color: "#475569" },
      },
      series: [
        {
          type: "bar",
          barWidth: 14,
          itemStyle: { color: TEAL, borderRadius: [0, 4, 4, 0] },
          label: { show: true, position: "right", fontSize: 12, color: "#334155" },
          data: rows.map(([, count]) => count),
        },
      ],
    };
  }, [profile]);

  // ⑤ 酒店距离结构（<3 家不画图）
  const hotelBands = profile?.hotelDistribution.bands ?? [];
  const hotelCount = profile?.hotelDistribution.count ?? 0;
  const hotelBandOption = useMemo<EChartsOption>(
    () => ({
      grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
      tooltip: { trigger: "axis" },
      xAxis: { type: "value", minInterval: 1, splitLine: { lineStyle: { color: "#E9EEF5" } }, axisLabel: { fontSize: 11, color: "#94A3B8" } },
      yAxis: {
        type: "category",
        data: hotelBands.map((band) => band.label),
        axisTick: { show: false },
        axisLine: { show: false },
        axisLabel: { fontSize: 12, color: "#475569" },
      },
      series: [
        {
          type: "bar",
          barWidth: 14,
          itemStyle: { color: TEAL, borderRadius: [0, 4, 4, 0] },
          label: { show: true, position: "right", fontSize: 12, color: "#334155" },
          data: hotelBands.map((band) => band.count),
        },
      ],
    }),
    [hotelBands],
  );

  // 半径敏感性（移入「分析口径」折叠）
  const sensitivityOption = useMemo<EChartsOption>(() => {
    const rows = coverage?.comparisons ?? [];
    return {
      grid: { left: 8, right: 24, top: 32, bottom: 8, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { top: 0, left: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: "#475569" } },
      xAxis: { type: "value", splitLine: { lineStyle: { color: "#E9EEF5" } }, axisLabel: { color: "#94A3B8", fontSize: 11 } },
      yAxis: {
        type: "category",
        data: rows.map((row) => row.radiusMeters + "m"),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { fontSize: 12, color: "#475569" },
      },
      series: [
        { name: "唯一近邻", type: "bar", stack: "r", itemStyle: { color: BLUE }, data: rows.map((row) => row.uniqueNear) },
        { name: "保留歧义", type: "bar", stack: "r", itemStyle: { color: ORANGE }, data: rows.map((row) => row.ambiguous) },
        { name: "未匹配", type: "bar", stack: "r", itemStyle: { color: GREY }, data: rows.map((row) => row.unmatched) },
      ],
    };
  }, [coverage]);

  const kpi = [
    { label: "分析地点", value: coverage?.areaCount ?? "—" },
    { label: "只靠近一处", value: coverage?.eventsNearby ?? "—" },
    { label: "靠近多处", value: coverage?.eventsAmbiguous ?? "—" },
    { label: "暂未匹配", value: coverage?.eventsUnmatched ?? "—" },
  ];

  return (
    <div className="insight-page">
      <header className="insight-head">
        <div>
          <h1>商圈洞察</h1>
          <p className="insight-sub">
          <Tooltip
            title={
              "只靠近一处＝活动只进入一个地点的范围；靠近多处＝同时进入多个地点范围，未强行分配；" +
              "暂未匹配＝不在任何地点范围内，不代表当地没有活动；" +
              "已匹配比例＝能对上地点的活动数 ÷ 有坐标的活动数。" +
              "所有距离都是场馆坐标到地点中心点的直线距离。"
            }
          >
            <span className="insight-help">怎么算的</span>
          </Tooltip>

            {radius}m 中心点近邻 · 非正式商圈边界
            <Select
              size="small"
              value={radius}
              onChange={setRadius}
              aria-label="匹配半径"
              style={{ marginLeft: 8, minWidth: 96 }}
              options={RADII.map((value) => ({ value, label: value + " 米" }))}
            />
          </p>
        </div>
        <div className="kpi-strip">
          {kpi.map((item) => (
            <div key={item.label}>
              <strong>{item.value}</strong>
              <small>{item.label}</small>
            </div>
          ))}
        </div>
      </header>

      {error && <p className="insight-muted">数据加载失败：{error}</p>}

      {/* 商圈地图：选中中心画 800 米范围圆，其余只画点（不画假边界） */}
      {areas.length > 0 && (
        <section className="insight-card" aria-label="商圈地图">
          <div className="card-head">
            <h3>商圈地图</h3>
            <span className="insight-muted">
              蓝＝官方商圈 · 青＝参考地点 · 选中后显示该地点 {radius} 米范围（不是正式边界）
            </span>
          </div>
          <MarketAreaMap
            height={420}
            selectedId={selected}
            onSelect={setSelected}
            areas={areas.map((area) => ({
              id: area.id,
              name: area.name,
              status: area.status,
              lng: area.centerLng,
              lat: area.centerLat,
              radiusMeters: area.radiusMeters,
            }))}
          />
        </section>
      )}

      {/* ② 主图 + 辅助图 */}
      <section className="insight-row" style={{ gridTemplateColumns: "minmax(0, 1.5fr) minmax(0, 1fr)" }}>
        <div className="insight-card">
          <div className="card-head">
            <h3>活动最多的十个地点</h3>
            <span className="insight-muted">蓝=官方商圈 · 青=参考地点 · 点击切换</span>
          </div>
          <div className="chart-md">
            <Chart
              option={rankingOption}
              onClick={(name: string) => {
                const target = areas.find((area) => area.name === name || "·" + area.name === name);
                if (target) setSelected(target.id);
              }}
            />
          </div>
        </div>
        <div className="insight-card">
          <div className="card-head">
            <h3>活动能不能对上地点</h3>
            <span className="insight-muted">分母 {coverage?.identitiesTotal ?? "—"} 个活动身份</span>
          </div>
          <div className="chart-md">
            <Chart option={compositionOption} />
          </div>
        </div>
      </section>

      {/* ③ 选中中心 */}
      <section className="insight-section">
        <div className="selection-bar">
          <h2>
            {profile?.area.name ?? "—"}
            {profile?.area.status === "candidate" && <Tag style={{ marginLeft: 8 }}>候选集聚点</Tag>}
          </h2>
          <Space>
            <span className="insight-muted">
              {profile?.area.parentName ?? ""} · {profile?.area.center.matchedName ?? ""} · 半径{" "}
              {profile?.area.radiusMeters ?? "—"} 米
            </span>
            <Select
              size="small"
              style={{ minWidth: 220 }}
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
          </Space>
        </div>

        {profile && (
          <div className="kpi-strip">
            <div>
              <strong>{profile.coverage.matched}</strong>
              <small>本月能对上的活动</small>
            </div>
            <div>
              <strong>{profile.coverage.ambiguous}</strong>
              <small>靠近多处</small>
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
              <small>已匹配比例</small>
            </div>
          </div>
        )}
      </section>

      {/* ④ 趋势 + 类别 */}
      <section className="insight-row" style={{ gridTemplateColumns: "minmax(0, 1.5fr) minmax(0, 1fr)" }}>
        <div className="insight-card">
          <div className="card-head">
            <h3>每周有多少活动</h3>
            <span className="insight-muted">周起始日 · 跨周可重复，不能相加当月度总量</span>
          </div>
          <div className="chart-md chart-tall">
            <Chart option={weeklyOption} />
          </div>
        </div>
        <div className="insight-card">
          <div className="card-head">
            <h3>活动都有哪些类型</h3>
            <span className="insight-muted">窗口内可归属活动</span>
          </div>
          <div className="chart-md chart-tall">
            <Chart option={categoryOption} />
          </div>
        </div>
      </section>

      {/* ⑤ 酒店摘要 */}
      <section className="insight-card">
        <div className="card-head">
          <h3>周边收录的住宿</h3>
          <span className="insight-muted">数据来自平台已收录的住宿 POI（高德），仅反映 800 米近邻范围内的样本分布，不代表全部在营酒店或完整竞争格局</span>
        </div>
        {hotelCount === 0 ? (
          <p className="insight-muted" style={{ padding: "8px 0" }}>暂无已收录酒店</p>
        ) : hotelCount < 3 ? (
          <p className="hotel-summary">
            周边已收录 {hotelCount} 家住宿设施
            {hotelBands.filter((band) => band.count > 0).map((band) => (
              <span key={band.label}>
                {" ｜ "}
                {band.label} {band.count} 家
              </span>
            ))}
          </p>
        ) : (
          <div className="chart-sm">
            <Chart option={hotelBandOption} />
          </div>
        )}
      </section>

      {/* AI 解读：证据约束型，明确标注未经核实 */}
      <AiMarketCard
        areaId={selected}
        radius={radius}
        start={monthWindow.start}
        end={monthWindow.end}
      />

      {/* 明细与口径 */}
      <Collapse
        ghost
        className="insight-collapse"
        defaultActiveKey={["activities"]}
        items={[
          {
            key: "activities",
            label: "窗口内可归属活动（" + (profile?.nearbyEvents.length ?? 0) + "）",
            children: (
              <Table
                size="small"
                pagination={false}
                rowKey="identity"
                dataSource={profile?.nearbyEvents ?? []}
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
            label: "周边已收录住宿设施明细（" + (profile?.hotelCalendar.length ?? 0) + "）",
            children: (
              <Table
                size="small"
                pagination={false}
                rowKey="name"
                dataSource={profile?.hotelCalendar ?? []}
                columns={[
                  { title: "酒店", dataIndex: "name" },
                  { title: "距中心", dataIndex: "distanceMeters", width: 100, render: (value: number) => value + " 米" },
                  { title: "周边活动", dataIndex: "nearbyActivities", width: 100 },
                  { title: "覆盖天数", dataIndex: "coveredDays", width: 100 },
                ]}
              />
            ),
          },
          {
            key: "method",
            label: "分析口径（半径敏感性 · 集中度 · 限制）",
            children: (
              <div className="method-block">
                <div className="chart-sm">
                  <Chart option={sensitivityOption} />
                </div>
                <p className="insight-muted">
                  {profile?.coverage.method}。
                  {profile?.caveat}
                </p>
                {profile && (
                  <p className="insight-muted">
                    前 1 个中心占可归属活动 {Math.round(profile.concentration.top1Share * 100)}%，前 5 个占{" "}
                    {Math.round(profile.concentration.top5Share * 100)}%（分母{" "}
                    {profile.concentration.totalMatched}）；单一场馆「{profile.concentration.topVenue}」占本中心{" "}
                    {Math.round(profile.concentration.topVenueShare * 100)}%。
                  </p>
                )}
                <p className="insight-muted">
                  共 {coverage?.officialCount ?? "—"} 个官方商圈与 {coverage?.candidateCount ?? "—"} 个候选集聚点；
                  候选点由 POI 聚类得到，未经政府或地图方确认为正式商圈。住宿设施坐标来自高德 POI 且通过坐标系检查，但这不等于经人工实地核验其存在、位置与营业状态。
                </p>
              </div>
            ),
          },
        ]}
      />

      <CaliberBar window={caliberWindow} events={adminEvents.distinct} />

      <Collapse
        ghost
        className="insight-collapse"
        items={[
          {
            key: "more",
            label: "更多分析（按区县统计、地区资源比较、经济情景、导出简报）",
            children: (
              <>
                <section className="insight-card gap-bottom" aria-label="按区县统计">
                  <div className="card-head">
                    <h3>原始归属：按区县统计</h3>
                    <span className="insight-muted">与商圈口径不可相加</span>
                  </div>
                  <div className="chart-sm">
                    <Chart
                      option={
                        {
                          grid: { left: 8, right: 40, top: 8, bottom: 8, containLabel: true },
                          tooltip: { trigger: "axis" },
                          xAxis: { type: "value", minInterval: 1, splitLine: { lineStyle: { color: "#E9EEF5" } }, axisLabel: { color: "#94A3B8", fontSize: 11 } },
                          yAxis: {
                            type: "category",
                            data: adminRows.map((row) => row.name).reverse(),
                            axisLine: { show: false },
                            axisTick: { show: false },
                            axisLabel: { fontSize: 12, color: "#475569" },
                          },
                          series: [
                            {
                              type: "bar",
                              barWidth: 14,
                              itemStyle: { color: GREY, borderRadius: [0, 4, 4, 0] },
                              label: { show: true, position: "right", fontSize: 12, color: "#334155" },
                              data: adminRows.map((row) => row.count).reverse(),
                            },
                          ],
                        } as EChartsOption
                      }
                    />
                  </div>
                </section>

                <OpportunityAnalysis events={adminEvents.distinct} />
                <ScenarioPanel eventName={profile?.nearbyEvents[0]?.name ?? "（请先选择一条活动）"} />

                <section className="insight-card gap-top" aria-label="导出城市简报">
                  <div className="card-head">
                    <h3>导出城市简报</h3>
                    <span className="insight-muted">
                      五张工作表：概览 / 活动明细 / 本期变化 / 来源证据 / 待确认事项
                    </span>
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
                    {!accountState.authenticated && <span className="insight-muted">登录后可导出</span>}
                  </Space>
                </section>
              </>
            ),
          },
        ]}
      />
    </div>
  );
}
