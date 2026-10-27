import { useEffect, useMemo, useState } from "react";
import { Button, Collapse, Space, Table, Tag } from "antd";

/**
 * 活动关系摘要（GPT Round 29，以酒店经理身份定稿的版本）。
 *
 * 为什么不直接放图谱：酒店员工看不懂 HELD_AT / NEARBY / calculation 这类字段，
 * 也不该先读技术说明。所以默认给"人话摘要"，图谱退到「查看关系图」按钮后面。
 *
 * 术语映射（页面上不许出现英文边类型与坐标系/算法名）：
 *   HELD_AT → 在哪举办    REPORTED_BY → 信息来自   NEARBY → 离得多近
 *   WITHIN_RADIUS → 中心点周边        recorded → 资料记载   computed → 测距结果
 *   verificationStatus → 核实情况     evidenceRefs → 来源依据   calculation → 距离怎么算
 *
 * 三条"会让人不信"的坑（经理原话，必须避开）：
 *   1. 没核实却说得很确定；2. 把"靠近"说成"属于"；3. 数字很精确却不说怎么算。
 */

type Edge = {
  id: string;
  fromId: string;
  toId: string;
  type: string;
  kind: string;
  verificationStatus: string;
  evidenceRefs?: { table?: string; recordId?: string; field?: string; sourceUrl?: string | null }[];
  calculation?: {
    method: string;
    coordinateSystem: string;
    distanceMeters: number;
    radiusMeters: number;
    calculatedAt: string;
    inputCoordinateRefs?: (string | null | undefined)[];
  };
};

type Chain = {
  eventId: string;
  radiusMeters: number;
  nodes: { id: string; type: string; name: string; attributes?: Record<string, unknown> }[];
  edges: Edge[];
  venue: { id: string; name: string } | null;
  nearbyHotels: { id: string; name: string; distanceMeters: number }[];
  nearbyPlaces: { id: string; name: string; distanceMeters: number; category: string | null }[];
  nearbyAreaCenter: { id: string; name: string; kind: string; distanceMeters: number; insideRadius: boolean } | null;
  warnings: string[];
};

const EDGE_LABEL: Record<string, string> = {
  HELD_AT: "在哪举办",
  REPORTED_BY: "信息来自",
  NEARBY: "离得多近",
  WITHIN_RADIUS: "中心点周边",
};

const KIND_LABEL: Record<string, string> = {
  recorded: "资料记载",
  computed: "测距结果",
};

const STATUS_LABEL: Record<string, string> = {
  Verified: "已核实",
  "Needs Review": "待核实",
  Unknown: "未标注",
};


/** 后端 places 没有可靠的类型字段，这里按名称关键词做**展示用**分类，并在标题里注明。 */
function placeKind(name: string): "dining" | "transport" | "other" {
  const text = name || "";
  if (/(餐厅|饭店|火锅|咖啡|肯德基|麦当劳|星巴克|小吃|面馆|酒楼|餐饮)/.test(text)) return "dining";
  if (/(公交站|地铁|轻轨|车站|停车场|码头|轮渡)/.test(text)) return "transport";
  return "other";
}

function statusTag(value: string) {
  const label = STATUS_LABEL[value] ?? value;
  return <Tag color={value === "Verified" ? "green" : value === "Needs Review" ? "gold" : "default"}>{label}</Tag>;
}

export default function GraphRelationSummary({ eventId }: { eventId: string }) {
  const [chain, setChain] = useState<Chain | null>(null);
  const [error, setError] = useState<string>("");
  const [showGraph, setShowGraph] = useState(false);

  useEffect(() => {
    if (!eventId) return undefined;
    let alive = true;
    setChain(null);
    setError("");
    fetch(`/api/graph/query/event/${encodeURIComponent(eventId)}?radius=800`, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("关系数据加载失败");
        return (await response.json()) as Chain;
      })
      .then((data) => alive && setChain(data))
      .catch((reason: Error) => alive && setError(reason.message));
    return () => {
      alive = false;
    };
  }, [eventId]);

  const eventNode = useMemo(() => chain?.nodes.find((node) => node.type === "Event"), [chain]);
  const venueNode = useMemo(() => chain?.nodes.find((node) => node.type === "Venue"), [chain]);
  const sourceNode = useMemo(() => chain?.nodes.find((node) => node.type === "Source"), [chain]);
  const heldEdge = useMemo(() => chain?.edges.find((edge) => edge.type === "HELD_AT"), [chain]);

  if (error) return <p className="muted">关系数据加载失败：{error}</p>;
  if (!chain) return <p className="muted">正在读取这条活动的关系…</p>;

  const kindOf = (place: { name: string; category: string | null }) =>
    place.category === "dining" || place.category === "transport"
      ? place.category
      : placeKind(place.name);
  const dining = chain.nearbyPlaces.filter((place) => kindOf(place) === "dining");
  const transport = chain.nearbyPlaces.filter((place) => kindOf(place) === "transport");
  const others = chain.nearbyPlaces.filter((place) => kindOf(place) === "other");

  return (
    <section className="panel gap-bottom" aria-label="活动关系摘要">
      <div className="panel-heading">
        <h3 style={{ margin: 0 }}>
          {eventNode?.name ?? "活动"}
          {heldEdge && <span style={{ marginLeft: 8 }}>{statusTag(heldEdge.verificationStatus)}</span>}
        </h3>
        <small className="muted">
          距离为场馆到对应地点的直线距离（{chain.radiusMeters} 米内）
        </small>
      </div>

      {/* ① 在哪举办、什么时候 */}
      <div className="relation-line">
        <span className="relation-key">在哪举办</span>
        <span className="relation-value">
          {venueNode?.name ?? "未关联场馆"}
          {eventNode?.attributes?.startDate ? (
            <span className="muted">
              {" "}
              · {String(eventNode.attributes.startDate)}
              {eventNode.attributes.endDate ? " 至 " + String(eventNode.attributes.endDate) : ""}
            </span>
          ) : null}
        </span>
      </div>
      <div className="relation-line">
        <span className="relation-key">信息来自</span>
        <span className="relation-value">
          {sourceNode?.name ?? "未知来源"}
          {heldEdge?.evidenceRefs?.[0]?.sourceUrl && (
            <a href={heldEdge.evidenceRefs[0].sourceUrl} target="_blank" rel="noreferrer">
              {" "}
              查看原始记录
            </a>
          )}
        </span>
      </div>

      {/* ② 离我的酒店多远 */}
      <h4 className="relation-title">附近有什么</h4>
      {chain.nearbyHotels.length === 0 ? (
        <p className="muted">该场馆周边 800 米内没有已收录的住宿设施（不代表附近没有酒店）</p>
      ) : (
        <ul className="relation-list">
          {chain.nearbyHotels.slice(0, 6).map((hotel) => (
            <li key={hotel.id}>
              {hotel.name}
              <span className="muted"> · 距活动场馆约 {hotel.distanceMeters} 米 · 直线距离</span>
            </li>
          ))}
        </ul>
      )}

      {dining.length > 0 && (
        <>
          <h4 className="relation-title">附近餐饮（按名称判断）</h4>
          <ul className="relation-list">
            {dining.slice(0, 4).map((place) => (
              <li key={place.id}>
                {place.name}
                <span className="muted"> · 约 {place.distanceMeters} 米</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {transport.length > 0 && (
        <>
          <h4 className="relation-title">附近交通（按名称判断）</h4>
          <ul className="relation-list">
            {transport.slice(0, 4).map((place) => (
              <li key={place.id}>
                {place.name}
                <span className="muted"> · 约 {place.distanceMeters} 米</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {others.length > 0 && (
        <>
          <h4 className="relation-title">附近其他设施</h4>
          <ul className="relation-list">
            {others.slice(0, 4).map((place) => (
              <li key={place.id}>
                {place.name}
                <span className="muted"> · 约 {place.distanceMeters} 米</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {chain.nearbyAreaCenter && (
        <div className="relation-line">
          <span className="relation-key">中心点周边</span>
          <span className="relation-value">
            最近参考点「{chain.nearbyAreaCenter.name}」约 {chain.nearbyAreaCenter.distanceMeters} 米
            {chain.nearbyAreaCenter.insideRadius ? "（在半径内）" : "（超出半径，不计入归属）"}
          </span>
        </div>
      )}

      <p className="relation-caveat">
        活动场馆关联仍待核实；距离由位置计算，不代表酒店与活动存在合作关系。
      </p>

      {/* ③ 靠不靠谱 */}
      <Space wrap>
        <Button size="small" onClick={() => setShowGraph((value) => !value)}>
          {showGraph ? "收起关系图" : "查看关系图"}
        </Button>
        <Button size="small" href={`/map?event=${encodeURIComponent(chain.eventId)}`}>
          在地图上看
        </Button>
      </Space>

      <Collapse
        ghost
        items={[
          {
            key: "evidence",
            label: `查看来源与依据（${chain.edges.length} 条关系）`,
            children: (
              <Table
                size="small"
                pagination={false}
                rowKey="id"
                dataSource={chain.edges}
                columns={[
                  {
                    title: "关系",
                    dataIndex: "type",
                    width: 110,
                    render: (value: string) => EDGE_LABEL[value] ?? value,
                  },
                  {
                    title: "性质",
                    dataIndex: "kind",
                    width: 96,
                    render: (value: string) => KIND_LABEL[value] ?? value,
                  },
                  {
                    title: "核实情况",
                    dataIndex: "verificationStatus",
                    width: 96,
                    render: (value: string) => statusTag(value),
                  },
                  {
                    title: "来源依据 / 距离怎么算",
                    render: (_: unknown, edge: Edge) => {
                      if (edge.type === "NEARBY" && edge.calculation) {
                        return (
                          <span className="muted">
                            两点坐标直线距离 {edge.calculation.distanceMeters} 米；
                            半径上限 {edge.calculation.radiusMeters} 米；
                            计算于 {edge.calculation.calculatedAt.slice(0, 16).replace("T", " ")}
                          </span>
                        );
                      }
                      const ref = edge.evidenceRefs?.[0];
                      if (!ref) return <span className="muted">暂无可靠依据</span>;
                      return (
                        <span className="muted">
                          {ref.table}.{ref.field}
                          {ref.sourceUrl && (
                            <a href={ref.sourceUrl} target="_blank" rel="noreferrer">
                              {" "}
                              打开来源
                            </a>
                          )}
                        </span>
                      );
                    },
                  },
                ]}
              />
            ),
          },
        ]}
      />

      {chain.warnings.length > 0 && (
        <ul className="relation-warnings">
          {chain.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
