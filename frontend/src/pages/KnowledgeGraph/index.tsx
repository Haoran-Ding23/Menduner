import { useMemo, useState } from "react";
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
const colors = {
  Event: "#1677ff",
  Venue: "#13aaba",
  District: "#a56be2",
  Hotel: "#d39725",
};
const positions = {
  Event: { x: 0, y: 180 },
  Venue: { x: 255, y: 290 },
  District: { x: 510, y: 290 },
  Hotel: { x: 510, y: 450 },
};
export default function KnowledgeGraph() {
  const { repository, dataset, selected, update, openEvent, go } =
    usePlatform();
  const id = selected ?? dataset.events[0]?.id ?? "";
  // The MiniMap is a 200x150 overlay that would cover a third of a phone screen, and React
  // Flow measures it for the fit calculation. It is not rendered below the 760px breakpoint.
  const small = useIsSmallScreen();
  const [expanded, setExpanded] = useState(true),
    [nodeId, setNodeId] = useState<string | null>(null),
    [edgeId, setEdgeId] = useState<string | null>(null);
  const graph = useMemo(() => repository.getGraphData(id), [repository, id]);
  const offsets = { Event: 0, Venue: 0, District: 0, Hotel: 0 };
  const nodes: Node[] = graph.nodes
    .filter((n) => expanded || !["District", "Hotel"].includes(n.kind))
    .map((n) => ({
      id: n.id,
      data: {
        label: (
          <div>
            <small style={{ color: colors[n.kind] }}>
              {n.kind.toUpperCase()}
              {n.demo ? " · DEMO" : n.analytical ? " · 规则假设" : ""}
            </small>
            <strong>{n.label}</strong>
          </div>
        ),
      },
      position: {
        ...positions[n.kind],
        y: positions[n.kind].y + offsets[n.kind]++ * 125,
      },
      style: {
        border: `1px ${n.analytical ? "dashed" : "solid"} ${colors[n.kind]}`,
        borderRadius: 12,
        width: 190,
        background: "#fff",
        boxShadow:
          nodeId === n.id
            ? `0 0 0 3px ${colors[n.kind]}44`
            : "0 5px 18px #162b4710",
      },
    }));
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
            : null;
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">城市数据关联</div>
        <h1>知识图谱</h1>
        <p>活动 → 场馆 → 位置语境 → 周边酒店资源</p>
      </div>
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
          {nodes.length ? (
            <ReactFlow
              key={id + expanded}
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
            />
          )}
        </section>
      </div>
      <Alert
        className="gap-top"
        type="info"
        showIcon
        message="HELD_AT：活动与场馆关联；LOCATED_IN：商圈位置背景；NEAR：核验坐标计算的近似直线距离（10 km 内）。虚线表示 DEMO 关系；点击节点查看信息及证据入口。"
      />
    </>
  );
}
