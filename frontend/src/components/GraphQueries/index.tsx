import { useMemo, useState } from "react";
import { Alert, Button, Segmented, Select, Space, Table, Tag } from "antd";
import { usePlatform } from "../../hooks/usePlatform";

/**
 * 图谱业务查询：用三个真实问题去查图，而不是让用户自己在画布上找。
 *
 * 结果区固定显示三段元信息，这是这个面板存在的理由：
 *   * 出处：来源标识与生成方式（采集 / 人工录入 / 规则推断）；
 *   * 假设：客群这类规则推断的结论，标成「假设」而不是事实；
 *   * 待补充：本该有关系但数据里没有的（活动未挂场馆、场馆缺坐标），显示出来而不是省略。
 */

type Preset = "venue" | "hotel" | "district";

interface GraphResult {
  ok: boolean;
  reason?: string;
  query?: string;
  counts?: Record<string, number>;
  events?: {
    id: string;
    label: string;
    startDate: string | null;
    endDate: string | null;
    category: string | null;
    distanceKm?: number;
    audience?: string | null;
    audienceIsAssumption?: boolean;
    relations?: { heldAt?: string | null; inDistrict?: string | null };
    provenance?: { source?: string; generatedBy?: string };
  }[];
  venues?: { id: string; name: string; eventCount: number; hasCoordinates: boolean }[];
  hotels?: { id: string; name: string; tierLabel?: string | null; hasCoordinates: boolean }[];
  categoryBreakdown?: Record<string, number>;
  provenance?: { source?: string; generatedBy?: string };
  assumptions?: string[];
  missing?: string[];
}

export default function GraphQueries() {
  const { dataset } = usePlatform();
  const [preset, setPreset] = useState<Preset>("district");
  const [venueId, setVenueId] = useState<string>("");
  const [hotelId, setHotelId] = useState<string>("");
  const [districtId, setDistrictId] = useState<string>("");
  const [result, setResult] = useState<GraphResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const districtOptions = useMemo(
    () =>
      dataset.districts
        .filter((item) => (item.kind === "district" || item.kind === "county_city") && !item.demo)
        .map((item) => ({ value: item.id, label: item.name })),
    [dataset.districts],
  );

  const run = async () => {
    const target =
      preset === "venue" ? venueId : preset === "hotel" ? hotelId : districtId;
    if (!target) {
      setError("请先选择要查询的对象");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const url =
        preset === "venue"
          ? `/api/graph/venue/${encodeURIComponent(target)}`
          : preset === "hotel"
            ? `/api/graph/hotel/${encodeURIComponent(target)}`
            : `/api/graph/district/${encodeURIComponent(target)}`;
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) throw new Error(`查询失败（HTTP ${response.status}）`);
      setResult((await response.json()) as GraphResult);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "查询失败");
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const presetLabel: Record<Preset, string> = {
    venue: "某场馆未来有哪些活动",
    hotel: "某酒店附近有哪些匹配客群的活动",
    district: "同一商圈关联哪些活动和酒店",
  };

  return (
    <div className="graph-queries">
      <Space wrap size={10}>
        <Segmented
          value={preset}
          onChange={(value) => {
            setPreset(value as Preset);
            setResult(null);
            setError("");
          }}
          options={[
            { label: "场馆", value: "venue" },
            { label: "酒店", value: "hotel" },
            { label: "商圈", value: "district" },
          ]}
        />
        {preset === "venue" && (
          <Select
            style={{ width: 260 }}
            placeholder="选择场馆"
            value={venueId || undefined}
            onChange={setVenueId}
            showSearch
            optionFilterProp="label"
            options={dataset.venues.map((item) => ({ value: item.id, label: item.name }))}
          />
        )}
        {preset === "hotel" && (
          <Select
            style={{ width: 260 }}
            placeholder="选择酒店"
            value={hotelId || undefined}
            onChange={setHotelId}
            showSearch
            optionFilterProp="label"
            options={dataset.hotels.map((item) => ({ value: item.id, label: item.name }))}
          />
        )}
        {preset === "district" && (
          <Select
            style={{ width: 220 }}
            placeholder="选择商圈 / 行政区"
            value={districtId || undefined}
            onChange={setDistrictId}
            showSearch
            optionFilterProp="label"
            options={districtOptions}
          />
        )}
        <Button type="primary" loading={loading} onClick={() => void run()}>
          查询
        </Button>
        <small className="muted">{presetLabel[preset]}</small>
      </Space>

      {error && <Alert className="gap-top" type="warning" showIcon message={error} />}

      {result && !result.ok && (
        <Alert className="gap-top" type="info" showIcon message={result.reason ?? "没有结果"} />
      )}

      {result?.ok && (
        <div className="gap-top">
          <Space wrap size={8} className="gap-bottom">
            {Object.entries(result.counts ?? {}).map(([key, value]) => (
              <Tag key={key}>
                {COUNT_LABELS[key] ?? key} {value}
              </Tag>
            ))}
            {result.provenance?.source && (
              <Tag color="blue">来源：{result.provenance.source}</Tag>
            )}
            {result.provenance?.generatedBy && <Tag>生成方式：{result.provenance.generatedBy}</Tag>}
          </Space>

          {(result.events?.length ?? 0) > 0 && (
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={result.events}
              columns={[
                { title: "活动", dataIndex: "label" },
                {
                  title: "时间",
                  width: 190,
                  render: (_, row) => `${row.startDate ?? "待核验"} → ${row.endDate ?? "待核验"}`,
                },
                {
                  title: "场馆 / 商圈",
                  width: 200,
                  render: (_, row) =>
                    [row.relations?.heldAt, row.relations?.inDistrict].filter(Boolean).join(" · ") ||
                    "关系待补充",
                },
                {
                  title: "距离",
                  width: 90,
                  render: (_, row) =>
                    row.distanceKm === undefined ? "—" : `${row.distanceKm.toFixed(1)} km`,
                },
                {
                  title: "客群（规则推断）",
                  width: 160,
                  render: (_, row) =>
                    row.audience ? (
                      <span>
                        {row.audience} <Tag>假设</Tag>
                      </span>
                    ) : (
                      "—"
                    ),
                },
              ]}
            />
          )}

          {(result.venues?.length ?? 0) > 0 && (
            <Space wrap size={6} className="gap-top">
              {result.venues?.map((venue) => (
                <Tag key={venue.id} color={venue.hasCoordinates ? "blue" : "default"}>
                  {venue.name} · {venue.eventCount} 场
                  {venue.hasCoordinates ? "" : "（缺坐标）"}
                </Tag>
              ))}
            </Space>
          )}

          {(result.hotels?.length ?? 0) > 0 && (
            <Space wrap size={6} className="gap-top">
              {result.hotels?.map((hotel) => (
                <Tag key={hotel.id} color={hotel.hasCoordinates ? "cyan" : "default"}>
                  {hotel.name}
                  {hotel.tierLabel ? ` · ${hotel.tierLabel}` : ""}
                  {hotel.hasCoordinates ? "" : "（缺坐标）"}
                </Tag>
              ))}
            </Space>
          )}

          {(result.assumptions?.length ?? 0) > 0 && (
            <div className="gap-top">
              <small className="muted">假设（非事实）：</small>
              {result.assumptions?.map((note) => (
                <small key={note} className="block muted">· {note}</small>
              ))}
            </div>
          )}

          {(result.missing?.length ?? 0) > 0 && (
            <div className="gap-top">
              <small className="rank-unknown">待补充：</small>
              {result.missing?.map((note) => (
                <small key={note} className="block rank-unknown">· {note}</small>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const COUNT_LABELS: Record<string, string> = {
  events: "活动",
  matched: "匹配",
  venues: "场馆",
  hotels: "酒店",
  excludedNoCoordinates: "因缺坐标排除",
  excludedOutOfRadius: "超出半径排除",
};
