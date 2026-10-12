import { Button, Descriptions, Space, Tag, Tooltip } from "antd";
import type { Event } from "../../types";
import { usePlatform } from "../../hooks/usePlatform";
import { assessDemand, impactColors } from "../../services/intelligence";

export function ImpactTag({ event }: { event: Event }) {
  const { dataset } = usePlatform();
  const assessment = assessDemand(event, dataset);
  return (
    <Tooltip title={assessment.reasons.join("；")}>
      <Tag color={impactColors[assessment.level]}>
        Attention: {assessment.level}
        {event.demo ? " · DEMO" : ""}
      </Tag>
    </Tooltip>
  );
}
export function DemandExplanation({ event }: { event: Event }) {
  const { dataset, go } = usePlatform();
  const a = assessDemand(event, dataset);
  return (
    <section className="intelligence-card">
      <div className="section-heading">
        <h3>Event Intelligence · 为什么值得关注</h3>
        <ImpactTag event={event} />
      </div>
      <p className="muted">
        {event.demo
          ? "DEMO / Synthetic data / Not real event intelligence"
          : "基于已记录活动信息的关注等级"}
      </p>
      <ul className="explanation-list">
        {a.reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
      <Descriptions
        size="small"
        column={1}
        items={[
          {
            key: "hotels",
            label: `${a.radiusKm} km 内酒店资源`,
            children: `${a.nearbyHotels.length} 家（非全市场数量）`,
          },
          {
            key: "nearest",
            label: "最近酒店",
            children:
              a.nearestDistance === null
                ? "当前样本无可计算的邻近酒店"
                : `${a.nearbyHotels[0].hotel.name} · ${a.nearestDistance.toFixed(2)} km`,
          },
        ]}
      />
      <Space wrap>
        {a.nearbyHotels.map(({ hotel, distance }) => (
          <Button
            size="small"
            key={hotel.id}
            onClick={() => go("/hotels", event.id, { hotel: hotel.id })}
          >
            {hotel.name} · {distance.toFixed(2)} km
          </Button>
        ))}
      </Space>
    </section>
  );
}
