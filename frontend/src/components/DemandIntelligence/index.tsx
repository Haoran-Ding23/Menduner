import { Button, Descriptions, Space, Tag, Tooltip } from "antd";
import type { Event } from "../../types";
import { usePlatform } from "../../hooks/usePlatform";
import { assessDemand, impactColors } from "../../services/intelligence";

/**
 * How much attention an event deserves, as stars.
 *
 * The old tag printed 「关注等级：UNKNOWN」 in a box, and because the level is UNKNOWN for almost
 * every event - it needs every date and category field settled - the list became a column of the
 * same grey word saying nothing. A star reads at a glance: three yellow stars is worth planning
 * around, one grey star is background, and no star means nobody can say yet, which is honest by
 * being absent rather than by printing a word nobody can act on.
 */
const STARS: Record<string, number> = { HIGH: 3, MEDIUM: 2, LOW: 1 };
const LEVEL_LABEL: Record<string, string> = {
  HIGH: "高关注",
  MEDIUM: "中关注",
  LOW: "低关注",
};

export function ImpactTag({ event }: { event: Event }) {
  const { dataset } = usePlatform();
  const assessment = assessDemand(event, dataset);
  const count = STARS[assessment.level] ?? 0;
  // Unknown renders nothing: an empty spot reads as "no signal", which is the truth, whereas a
  // grey UNKNOWN box invites the reader to hunt for a meaning it does not have.
  if (!count) return null;
  const highlight = assessment.level === "HIGH";
  return (
    <Tooltip
      title={`${LEVEL_LABEL[assessment.level]}${event.demo ? " · DEMO" : ""}。${assessment.reasons.join("；")}`}
    >
      <span
        className="impact-stars"
        aria-label={`${LEVEL_LABEL[assessment.level]}（共 ${count} 星）`}
      >
        {Array.from({ length: count }, (_, i) => (
          <span
            key={i}
            style={{ color: highlight ? "#FAAD14" : "#CBD5E1" }}
            aria-hidden="true"
          >
            ★
          </span>
        ))}
      </span>
    </Tooltip>
  );
}
export function DemandExplanation({ event }: { event: Event }) {
  const { dataset, go } = usePlatform();
  const a = assessDemand(event, dataset);
  return (
    <section className="intelligence-card">
      <div className="section-heading">
        <h3>为什么值得关注</h3>
        <ImpactTag event={event} />
      </div>
      <p className="muted">
        {event.demo
          ? "DEMO / 合成数据，非真实活动情报"
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
