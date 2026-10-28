import { useMemo, useState, useEffect } from "react";
import { multiDayCaveat, selectGraphSample } from "../../utils/graphSample";
import GraphQueries from "../../components/GraphQueries";
import GraphRelationSummary from "../../components/GraphRelationSummary";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Select,
  Switch,
  Tag,
  Button,
  Empty,
  Alert,
  Descriptions,
  Space, Collapse } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import useIsSmallScreen from "../../hooks/useIsSmallScreen";
import { valueText } from "../../utils/data";
import { assessDemand, evidenceSummary } from "../../services/intelligence";
import { ImpactTag } from "../../components/DemandIntelligence";
const colors: Record<string, string> = {
  Shopping: "#0ea5e9",
  Other: "#64748b",
  Event: "#1677ff",
  Related: "#5b8def",
  Venue: "#13aaba",
  District: "#a56be2",
  Hotel: "#d39725",
  Restaurant: "#e8695a",
  Transport: "#2f9e6f",
  Audience: "#8a6fd6",
};
/**
 * Layer per node kind.
 *
 * The chain 活动 → 场馆 → 商圈 → 酒店 runs left to right, and the things around the venue stack in
 * the next column in their own bands so 5 restaurants, 6 stations and 15 hotels cannot overlap.
 * Audience nodes sit above the event: they are a hypothesis ABOUT the event, not a place around it.
 */
// ---- 太阳发散布局（GPT Round 35 规格：5 扇区 × 3 距离环）----
// 角度从正上方（12 点方向）顺时针计算，扇区两侧各留 6°。
const SECTOR_MARGIN = 6;
// [起始角, 结束角]，单位度
const SECTORS: Record<string, [number, number]> = {
  Hotel: [324, 36],
  Restaurant: [36, 108],
  Transport: [108, 180],
  Shopping: [180, 252],
  Other: [252, 324],
};
// 距离环 → 半径区间（px）。画布比 GPT 示例大，等比放大以免标签重叠。
const RINGS: { max: number; from: number; to: number }[] = [
  { max: 500, from: 230, to: 330 },
  { max: 1500, from: 350, to: 480 },
  { max: 3000, from: 500, to: 640 },
];
const MAX_NEARBY_NODES = 30;
/** 距离未写明时使用的半径：比最外环再远一档，避免与真实距离环混淆 */
const UNKNOWN_DISTANCE_RADIUS = 760;

/** 类别 → 扇区（未知类别归入「其他」，绝不猜成别的类别）。 */
function sectorOf(kind: string): [number, number] {
  return SECTORS[kind] ?? SECTORS.Other;
}

/** 距离 → 半径：环内线性映射；超过 3000m 不进环（由调用方过滤）。 */
function radiusForDistance(meters: number | null): number | null {
  if (meters === null || meters > RINGS[RINGS.length - 1].max) return null;
  const ring = RINGS.find((item) => meters <= item.max) ?? RINGS[RINGS.length - 1];
  const lower = ring === RINGS[0] ? 0 : RINGS[RINGS.indexOf(ring) - 1].max;
  const span = ring.max - lower;
  const ratio = span <= 0 ? 0 : (meters - lower) / span;
  return ring.from + (ring.to - ring.from) * Math.min(1, Math.max(0, ratio));
}

/** 扇区内第 index/n 个节点的角度（GPT 给的公式）。 */
function angleInSector(kind: string, index: number, total: number): number {
  const [rawFrom, rawTo] = sectorOf(kind);
  const from = rawFrom + SECTOR_MARGIN;
  const to = (rawTo <= rawFrom ? rawTo + 360 : rawTo) - SECTOR_MARGIN;
  const span = to - from;
  const theta = total <= 0 ? from + span / 2 : from + ((index + 0.5) / total) * span;
  return theta % 360;
}

/** 极坐标 → 画布坐标（θ 从正上方顺时针）。 */
function polarFromTop(thetaDeg: number, radius: number): { x: number; y: number } {
  const rad = (thetaDeg * Math.PI) / 180;
  return { x: Math.sin(rad) * radius, y: -Math.cos(rad) * radius };
}

export default function KnowledgeGraph() {
  const { repository, dataset, selected, update, openEvent, go, params } =
    usePlatform();
  // F06：默认样例由 selectGraphSample 按「关系完整度」选出，规则可复核、结果可复现，
  // 不再固定取 dataset.events[0]（那可能是一条没有场馆的孤立记录）。
  const sample = selectGraphSample(dataset);
  const id = selected ?? sample.eventId ?? "";
  // The MiniMap is a 200x150 overlay that would cover a third of a phone screen, and React
  // Flow measures it for the fit calculation. It is not rendered below the 760px breakpoint.
  const small = useIsSmallScreen();
  // The two layers live in the URL, matching how the rest of the workspace keeps view state
  // there (?past=1, ?event=…). A reviewer can then send a link that shows exactly the view
  // they mean, and a test can reach a state it could otherwise only click into.
  const expanded = params.get("layers") !== "0";
  const showRelated = params.get("related") === "1";
  const showPlaces = params.get("places") !== "0";
  const showAudience = params.get("audience") !== "0";
  const setExpanded = (next: boolean) => update({ layers: next ? null : "0" });
  const setShowRelated = (next: boolean) => update({ related: next ? "1" : null });
  const setShowPlaces = (next: boolean) => update({ places: next ? null : "0" });
  const setShowAudience = (next: boolean) =>
    update({ audience: next ? null : "0" });
  // 渐进式披露：默认不渲染关系画布（初始 DOM 里没有 ReactFlow）
  const [showCanvas, setShowCanvas] = useState(false);
  // 关系图全屏：节点多的时候小画布看不清，给一个不离开页面的放大方式
  const [graphFullscreen, setGraphFullscreen] = useState(false);
  // 全屏后必须能退出：Esc 直接关（用户反馈"点开收不回去"）
  useEffect(() => {
    if (!graphFullscreen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setGraphFullscreen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [graphFullscreen]);
  const [nodeId, setNodeId] = useState<string | null>(null),
    [edgeId, setEdgeId] = useState<string | null>(null);
  const graph = useMemo(
    () =>
      repository.getGraph(id, {
        related: showRelated,
        places: showPlaces,
        audience: showAudience,
      }),
    [repository, id, showRelated, showPlaces, showAudience],
  );
  // The related-event edges are the event->event ones; the venue/demand chain is unchanged.
  const relatedIds = useMemo(
    () => graph.edges.filter((e) => e.id.startsWith("related-")).map((e) => e.target),
    [graph.edges],
  );
  // How many same-venue events exist in total, so the panel can say what is not shown.
  const relatedTotal = useMemo(() => {
    const event = repository.getEventById(id);
    if (!event?.venueId) return 0;
    return dataset.events.filter(
      (e) => e.venueId === event.venueId && e.id !== event.id,
    ).length;
  }, [repository, dataset.events, id]);
  const relatedOrder = new Map(relatedIds.map((rid, index) => [rid, index]));

  // 每条 NEARBY 边都带后端算好的距离（标签形如 "NEAR · 358 m" / "1.2 km"）
  const distanceOf = new Map<string, number>();
  graph.edges.forEach((edge) => {
    const label = String(edge.label ?? "");
    const meters = label.match(/([\d.]+)\s*m\b/);
    const kilometers = label.match(/([\d.]+)\s*km/);
    if (meters) distanceOf.set(edge.target, Number(meters[1]));
    else if (kilometers) distanceOf.set(edge.target, Number(kilometers[1]) * 1000);
  });

  const NEARBY_KINDS = ["Hotel", "Restaurant", "Transport", "Shopping", "Other"];
  const visibleNodes = graph.nodes.filter((n) => expanded || !["District", "Hotel"].includes(n.kind));

  // 周边节点：只保留有距离的（无坐标不进环），并按 GPT 规格限制最多 30 个
  // 注意：不能要求"必须解析出距离"才显示——解析失败会让整类节点消失，
  // 用户看到的是"开关没用"。距离未知的节点放到最外环并标注。
  const nearbyNodes = visibleNodes
    .filter((n) => NEARBY_KINDS.includes(n.kind))
    .sort((a, b) => (distanceOf.get(a.id)! - distanceOf.get(b.id)!) || a.id.localeCompare(b.id));
  const shownNearby = new Set(nearbyNodes.slice(0, MAX_NEARBY_NODES).map((n) => n.id));
  const hiddenNearbyCount = Math.max(0, nearbyNodes.length - MAX_NEARBY_NODES);

  // 扇区内按「距离升序、稳定 ID 升序」排序，保证刷新后位置一致
  const ordered = [...visibleNodes].sort((a, b) => {
    const ak = NEARBY_KINDS.includes(a.kind) ? (distanceOf.get(a.id) ?? Number.MAX_SAFE_INTEGER) : -1;
    const bk = NEARBY_KINDS.includes(b.kind) ? (distanceOf.get(b.id) ?? Number.MAX_SAFE_INTEGER) : -1;
    if (a.kind !== b.kind) return a.kind.localeCompare(b.kind);
    return ak - bk || a.id.localeCompare(b.id);
  });
  const sectorCounts = new Map<string, number>();
  ordered.forEach((n) => {
    if (NEARBY_KINDS.includes(n.kind)) {
      if (!shownNearby.has(n.id)) return;
      sectorCounts.set(n.kind, (sectorCounts.get(n.kind) ?? 0) + 1);
    } else {
      sectorCounts.set(n.kind, (sectorCounts.get(n.kind) ?? 0) + 1);
    }
  });
  const sectorSeen = new Map<string, number>();

  const nodes: Node[] = visibleNodes
    .map((n) => {
      const relatedIndex = relatedOrder.get(n.id);
      const isRelated = relatedIndex !== undefined && n.id !== id;
      const kindColor = isRelated ? colors.Related : colors[n.kind];
      return {
        id: n.id,
        data: {
          label: (
            <div>
              <small style={{ color: kindColor }}>
                {n.kind.toUpperCase()}
                {isRelated ? " · 关联活动" : ""}
                {n.demo ? " · DEMO" : n.analytical ? " · 规则假设" : ""}
              </small>
              <strong>{n.label}</strong>
            </div>
          ),
        },
        position: (() => {
          // 中心：当前活动（场馆放在正上方内环）
          if (n.kind === "Event" && n.id === id) return { x: 0, y: 0 };
          if (n.kind === "Venue") return polarFromTop(0, 150);
          if (isRelated) {
            const total = Math.max(1, relatedIds.length);
            return polarFromTop(200 + (relatedIndex! / total) * 140, 760);
          }
          if (n.kind === "Audience") return polarFromTop(180, 120);

          const group = NEARBY_KINDS.includes(n.kind) ? n.kind : "Other";
          const total = sectorCounts.get(group) ?? 1;
          const seen = sectorSeen.get(group) ?? 0;
          sectorSeen.set(group, seen + 1);
          const angle = angleInSector(group, seen, total);
          const meters = distanceOf.get(n.id) ?? null;
          // 距离未知时放到最外环（比 3km 环更外），并在节点标签上说明
          const radius = radiusForDistance(meters) ?? UNKNOWN_DISTANCE_RADIUS;
          return polarFromTop(angle, radius);
        })(),
        style: {
          border: `1px ${n.analytical ? "dashed" : "solid"} ${kindColor}`,
          borderRadius: 12,
          width: 190,
          background: "#fff",
          boxShadow:
            nodeId === n.id
              ? `0 0 0 3px ${kindColor}44`
              : "0 5px 18px #162b4710",
        },
      };
    });
  const edges: Edge[] = graph.edges
    .filter(
      (e) =>
        nodes.some((n) => n.id === e.source) &&
        nodes.some((n) => n.id === e.target),
    )
    .map((e) => ({
      ...e,
      label: e.label + (e.demo ? " · DEMO" : e.analytical ? " · 规则" : ""),
      animated: e.id === edgeId,
      style: {
        stroke: e.id === edgeId ? "#1677ff" : "#aab9cb",
        strokeWidth: e.id === edgeId ? 3 : 1.5,
        strokeDasharray: e.demo || e.analytical ? "5 4" : undefined,
      },
      labelStyle: { fontSize: 10 },
    }));
  const node = graph.nodes.find((n) => n.id === nodeId),
    event = repository.getEventById(id);
  const assessment = event ? assessDemand(event, dataset) : null,
    summary = event ? evidenceSummary(event, dataset) : null;
  const entity =
    node?.kind === "Event"
      ? repository.getEventById(node.entityId)
      : node?.kind === "Venue"
        ? dataset.venues.find((v) => v.id === node.entityId)
        : node?.kind === "Hotel"
          ? dataset.hotels.find((h) => h.id === node.entityId)
          : node?.kind === "District"
            ? dataset.districts.find((d) => d.id === node.entityId)
            : node?.kind === "Restaurant" || node?.kind === "Transport"
              ? repository.getPlaceById(node.entityId)
              : null;
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">城市数据关联</div>
        <h1>知识图谱</h1>
        <p className="graph-sample-note">
          默认样例：{dataset.events.find((e) => e.id === sample.eventId)?.name ?? "无可用真实活动"}
          （选择依据：{sample.reasons.join("、")}）
        </p>
        <p>活动 → 场馆 → 位置语境 → 周边酒店 / 餐饮 / 交通 → 目标客群(按规则自动生成)</p>
      </div>

<p className="page-lead">先看活动在哪里举办、与哪些地区相关；有疑问，再核对关系和来源。</p>
      <GraphRelationSummary
          eventId={id}
          onOpenGraph={() => setShowCanvas(true)}
          onVerify={(field) => go("/review", id, { field })}
        />

      <section className="panel gap-bottom" aria-label="图谱业务查询">
        <Collapse
          ghost
          size="small"
          items={[
            {
              key: "queries",
              // 默认收起：关系图是这一页的主角，查询面板不该把画布挤到屏幕外
              label: (
                <span>
                  用问题查图谱
                  <small className="muted" style={{ marginLeft: 8 }}>
                    同一商圈关联哪些活动和酒店；结果显示来源、生成方式与假设
                  </small>
                </span>
              ),
              children: <GraphQueries />,
            },
          ]}
        />
      </section>
      <div className="panel graph-toolbar">
        <Space wrap>
          <span>选择活动</span>
          <Select
            aria-label="图谱活动"
            value={id || undefined}
            style={{ width: 300 }}
            options={dataset.events.map((e) => ({
              value: e.id,
              label: e.name + (e.demo ? " · DEMO" : ""),
            }))}
            onChange={(event) => {
              update({ event });
              setNodeId(null);
              setEdgeId(null);
            }}
          />
          <Switch
            aria-label="展开商圈酒店"
            checked={expanded}
            onChange={setExpanded}
          />
          <span>展开商圈与酒店</span>
          <Switch
            aria-label="显示周边餐饮交通"
            checked={showPlaces}
            onChange={setShowPlaces}
          />
          <span>周边餐饮/交通</span>
          <Switch
            aria-label="显示目标客群"
            checked={showAudience}
            onChange={setShowAudience}
          />
          <span>目标客群(规则)</span>
          <Switch
            aria-label="显示关联活动"
            checked={showRelated}
            onChange={setShowRelated}
          />
          <span>显示关联活动</span>
        </Space>
        <Space wrap>
          {Object.entries(colors).map(([k, c]) => (
            <Tag color={c} key={k}>
              {k}
            </Tag>
          ))}
        </Space>
      </div>
      {/* 免责说明必须放在两列网格之外：放进 .graph-layout 会占掉画布那一格，
          把关系图挤成右下一小块（真实踩过的坑）。 */}
      <p className="muted graph-note">
        按场馆直线距离与设施类别组织的关系示意图，不代表实际地理方位；空间邻近不等于经济贡献。
        {hiddenNearbyCount > 0 && <span>（另有 {hiddenNearbyCount} 个周边设施未显示，可切换活动或缩小范围查看）</span>}
      </p>
      {/* 图谱稀疏时说明原因：不是画布坏了，而是场地关系还没核验 */}
      {event && !graph.nodes.some((n) => n.kind === "Venue") && (
        <Alert
          className="graph-sparse-hint"
          type="info"
          showIcon
          style={{marginBottom: 12 }}
          message="这条活动的场地关系还没核验，所以关系图里只有活动本身"
          description="核验「在哪举办」之后，场馆、周边酒店与商圈才会出现在图上。距离都是场馆到对应地点的直线距离。"
          action={
            <Button size="small" type="primary" onClick={() => go("/review", id, { field: "venueName" })}>
              去核验场地
            </Button>
          }
        />
      )}
      <div className="graph-layout">
        <div className={"panel graph-canvas" + (graphFullscreen ? " graph-canvas-full" : "")}>
          {!showCanvas ? (
            <div style={{ padding: 18 }}>
              <p className="muted" style={{ margin: "0 0 10px" }}>
                关系图默认收起。上面已经用一句句话说明了这场活动在哪办、离哪些住宿多近、信息靠不靠谱；
                需要看节点与连线时再展开。
              </p>
              <Button onClick={() => setShowCanvas(true)}>展开关系图</Button>
            </div>
          ) : nodes.length ? (
            <>
            <Button
              size="small"
              className="graph-fullscreen-toggle"
              onClick={() => setGraphFullscreen((v) => !v)}
            >
              {graphFullscreen ? "退出全屏（Esc）" : "全屏查看"}
            </Button>
            <ReactFlow
              // The key must change whenever the node set changes shape. React Flow only
              // runs fitView on mount, so toggling the related layer without remounting left
              // the new nodes outside the framed viewport - the caption counted them while
              // the canvas showed none.
              key={id + expanded + showRelated + showPlaces + showAudience}
              nodes={nodes}
              edges={edges}
              fitView
              fitViewOptions={{ padding: small ? 0.25 : 0.1 }}
              nodesDraggable={false}
              proOptions={{ hideAttribution: small }}
              onNodeClick={(_, n) => {
                setNodeId(n.id);
                setEdgeId(null);
              }}
              onEdgeClick={(_, e) => setEdgeId(e.id)}
            >
              <Background color="#dce4ed" gap={22} />
              <Controls showInteractive={false} />
              {!small && (
                <MiniMap
                  nodeColor={(n) =>
                    colors[
                      graph.nodes.find((g) => g.id === n.id)?.kind ?? "Event"
                    ]
                  }
                />
              )}
            </ReactFlow>
            </>
          ) : (
            <Empty description="没有可展示的图谱数据" />
          )}
        </div>
        <section className="panel node-panel">
          <h3>节点详情</h3>
          {node ? (
            <>
              <Tag color={colors[node.kind]}>
                {node.kind}
                {node.demo ? " · DEMO" : node.analytical ? " · 规则假设" : ""}
              </Tag>
              <h2>{node.label}</h2>
              {node.rule && (
                <Alert
                  type={node.analytical ? "warning" : "info"}
                  showIcon
                  message={`生成规则：${node.rule}`}
                  description={node.reason}
                />
              )}
              {node.sourceUrl && (
                <p>
                  <a href={node.sourceUrl} target="_blank" rel="noreferrer">
                    打开来源记录
                  </a>
                </p>
              )}
              {node.kind === "Event" && event && assessment && summary ? (
                <>
                  <ImpactTag event={event} />
                  <Descriptions
                    column={1}
                    items={[
                      {
                        key: "date",
                        label: "日期",
                        children: `${event.startDate ?? "—"} → ${event.endDate ?? event.startDate ?? "—"}`,
                      },
                      {
                        key: "venue",
                        label: "场馆",
                        children:
                          dataset.venues.find((v) => v.id === event.venueId)
                            ?.name ?? "—",
                      },
                      {
                        key: "hotels",
                        label: "邻近酒店资源",
                        children: `${assessment.nearbyHotels.length} 家 · 当前配置样本`,
                      },
                      {
                        key: "sources",
                        label: "核验来源",
                        children: `活动 ${summary.eventUrls.length} 个 / 场馆 ${summary.venueUrls.length} 个`,
                      },
                    ]}
                  />
                  <Button type="primary" onClick={() => openEvent(event.id)}>
                    打开活动详情
                  </Button>
                </>
              ) : (
                <Descriptions
                  column={1}
                  items={Object.entries(entity ?? {})
                    .filter(([k]) => k !== "raw")
                    .map(([label, value]) => ({
                      key: label,
                      label,
                      children: valueText(value),
                    }))}
                />
              )}{" "}
              {node.kind === "Venue" && (
                <Button onClick={() => go("/map", id)}>在地图中查看</Button>
              )}
            </>
          ) : (
            <Empty description="点击节点查看详情；点击关系线高亮" />
          )}
          {edgeId && (
            <Alert
              className="gap-top"
              type="info"
              message={graph.edges.find((e) => e.id === edgeId)?.label}
              description={graph.edges.find((e) => e.id === edgeId)?.reason}
            />
          )}
        </section>
      </div>
      {showRelated && (
        <Alert
          className="gap-top"
          type="info"
          showIcon
          message={
            relatedIds.length
              ? `已展开 ${relatedIds.length} 个关联活动（同场馆按同期天数排序）。` +
                (relatedTotal > relatedIds.length
                  ? `该场馆共有 ${relatedTotal} 个其他活动，其余未展开以免图不可读。`
                  : "")
              : "该活动没有可关联的同场馆活动，或它尚未归入场馆。"
          }
        />
      )}
    </>
  );
}
