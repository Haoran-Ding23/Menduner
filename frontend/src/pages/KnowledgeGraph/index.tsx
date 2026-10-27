import { useMemo, useState } from "react";
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
  Space,
} from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import useIsSmallScreen from "../../hooks/useIsSmallScreen";
import { valueText } from "../../utils/data";
import { assessDemand, evidenceSummary } from "../../services/intelligence";
import { ImpactTag } from "../../components/DemandIntelligence";
const colors: Record<string, string> = {
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
const LAYER_X: Record<string, number> = {
  Audience: -330,
  Event: 0,
  Venue: 270,
  District: 540,
  Hotel: 810,
  Restaurant: 810,
  Transport: 810,
};
const BAND_Y: Record<string, number> = {
  Audience: 60,
  Event: 180,
  Venue: 290,
  District: 290,
  Hotel: 0,
  Restaurant: 430,
  Transport: 760,
};
/** Where the related events sit: up to three columns in two rows, left of the chain. */
const RELATED_PER_ROW = 4;
function relatedPosition(index: number) {
  const column = index % RELATED_PER_ROW;
  const row = Math.floor(index / RELATED_PER_ROW);
  return { x: -340 + column * 226, y: -430 + row * 118 };
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
  const offsets: Record<string, number> = {};
  const relatedOrder = new Map(relatedIds.map((rid, index) => [rid, index]));
  const nodes: Node[] = graph.nodes
    .filter((n) => expanded || !["District", "Hotel"].includes(n.kind))
    .map((n) => {
      const relatedIndex = relatedOrder.get(n.id);
      const isRelated = relatedIndex !== undefined && n.id !== id;
      const kindColor = isRelated ? colors.Related : colors[n.kind];
      const band = BAND_Y[n.kind] ?? 290;
      const step = n.kind === "Hotel" ? 58 : 74;
      const index = offsets[n.kind] ?? 0;
      offsets[n.kind] = index + 1;
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
        position: isRelated
          ? relatedPosition(relatedIndex)
          : {
              x: LAYER_X[n.kind] ?? 0,
              y: band + (n.kind === "Audience" ? 0 : index * step),
            },
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

      <GraphRelationSummary
          eventId={id}
          onOpenGraph={() => setShowCanvas(true)}
          onVerify={(field) => go("/evidence", id, { field })}
        />

      <section className="panel gap-bottom" aria-label="图谱业务查询">
        <div className="panel-heading">
          <h3 style={{ margin: 0 }}>用问题查图谱</h3>
          <small className="muted">结果显示来源、生成方式、假设与待补充关系</small>
        </div>
        <GraphQueries />
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
      <div className="graph-layout">
        <div className="panel graph-canvas">
          {!showCanvas ? (
            <div style={{ padding: 18 }}>
              <p className="muted" style={{ margin: "0 0 10px" }}>
                关系图默认收起。上面已经用一句句话说明了这场活动在哪办、离哪些住宿多近、信息靠不靠谱；
                需要看节点与连线时再展开。
              </p>
              <Button onClick={() => setShowCanvas(true)}>展开关系图</Button>
            </div>
          ) : nodes.length ? (
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
